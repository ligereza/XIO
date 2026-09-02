from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest

from XIO_LAYER.adapters import (
    DuplicateHandoffError,
    HandoffIntegrityError,
    HandoffStoreError,
    JsonLineHandoffStore,
    LocalAdapterEventSource,
    PrivacyPolicy,
    SourceAdapterRegistry,
)
from XIO_LAYER.core.audit import AuditLedger
from XIO_LAYER.core.transport import Endpoint
from XIO_LAYER.tests.test_handoff import CountingAdapter


T0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "lucida_handoff_records.jsonl"


def prepared_handoffs():
    registry = SourceAdapterRegistry()
    registry.register(CountingAdapter("fixture-app"))
    selection = registry.select_candidate(
        source_app="fixture-app",
        event_type="cue.event",
        caller_id="operator-1",
        plan=registry.route_plan("cue.event"),
        selected_at=T0,
        selection_id="fixture-selection",
    )
    return LocalAdapterEventSource(FIXTURE_PATH).prepare_handoffs(
        registry,
        selection,
        source="xio-layer",
        destination=Endpoint("memory", "lucida-store"),
        audit=AuditLedger(),
        privacy_policy=PrivacyPolicy(allowed_payload_keys=frozenset({"cue"})),
    )


class JsonLineHandoffStoreTests(unittest.TestCase):
    def test_append_rejects_wrong_type_before_lock_or_file_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoffs.jsonl"
            store = JsonLineHandoffStore(path)

            with self.assertRaisesRegex(TypeError, "AdapterHandoff"):
                store.append(object())

            self.assertFalse(path.exists())
            self.assertFalse(path.with_name(path.name + ".lock").exists())

    def test_concurrent_same_content_append_is_serialized_and_idempotent(self):
        handoff = prepared_handoffs()[0]
        with tempfile.TemporaryDirectory() as directory:
            store = JsonLineHandoffStore(Path(directory) / "handoffs.jsonl")
            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(store.append, [handoff] * 16))

            self.assertEqual(results.count(True), 1)
            self.assertEqual(results.count(False), 15)
            self.assertEqual(len(store.replay(caller_id="operator-1")), 1)

    def test_concurrent_processes_share_file_lock(self):
        handoff = prepared_handoffs()[0]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoffs.jsonl"

            wire_path = Path(directory) / "handoff.json"
            wire_path.write_text(json.dumps(handoff.to_dict(), sort_keys=True), encoding="utf-8")
            script = (
                "import json, sys\n"
                "from pathlib import Path\n"
                "from XIO_LAYER.adapters import AdapterHandoff, JsonLineHandoffStore\n"
                "wire = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))\n"
                "handoff = AdapterHandoff.from_dict(wire, caller_id='operator-1')\n"
                "print(JsonLineHandoffStore(sys.argv[1]).append(handoff))\n"
            )
            processes = [
                subprocess.Popen(
                    [sys.executable, "-c", script, str(path), str(wire_path)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for _ in range(4)
            ]
            results = []
            for process in processes:
                stdout, stderr = process.communicate()
                self.assertEqual(process.returncode, 0, stderr)
                results.append(stdout.strip() == "True")

            self.assertEqual(results.count(True), 1)
            self.assertEqual(results.count(False), 3)
            self.assertEqual(len(JsonLineHandoffStore(path).replay(caller_id="operator-1")), 1)
            self.assertTrue(path.with_name(path.name + ".lock").exists())

    def test_append_is_idempotent_and_replay_restores_without_caller_storage(self):
        handoffs = prepared_handoffs()
        with tempfile.TemporaryDirectory() as directory:
            store = JsonLineHandoffStore(Path(directory) / "handoffs.jsonl")
            self.assertTrue(store.append(handoffs[0]))
            self.assertTrue(store.append(handoffs[1]))
            self.assertFalse(store.append(handoffs[0]))
            content = store.path.read_text(encoding="utf-8")
            restored = JsonLineHandoffStore(store.path).replay(caller_id="operator-1")
            self.assertFalse(JsonLineHandoffStore(store.path).append(handoffs[0]))

        self.assertNotIn("operator-1", content)
        self.assertEqual(
            [item.message.fingerprint for item in restored],
            [item.message.fingerprint for item in handoffs],
        )

    def test_same_id_with_different_prepared_content_is_rejected(self):
        handoff = prepared_handoffs()[0]
        conflicting = replace(
            handoff,
            privacy_policy=PrivacyPolicy(expose_peer_id=True),
        )
        with tempfile.TemporaryDirectory() as directory:
            store = JsonLineHandoffStore(Path(directory) / "handoffs.jsonl")
            self.assertTrue(store.append(handoff))
            with self.assertRaises(DuplicateHandoffError):
                store.append(conflicting)

    def test_public_store_requires_caller_identity_for_replay(self):
        handoff = prepared_handoffs()[0]
        with tempfile.TemporaryDirectory() as directory:
            store = JsonLineHandoffStore(Path(directory) / "handoffs.jsonl")
            store.append(handoff)
            with self.assertRaises(HandoffStoreError):
                store.replay(caller_id="")

    def test_tampered_handoff_record_is_rejected_by_integrity_chain(self):
        handoff = prepared_handoffs()[0]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoffs.jsonl"
            store = JsonLineHandoffStore(path)
            store.append(handoff)
            entry = json.loads(path.read_text(encoding="utf-8"))
            entry["handoff"]["event"]["payload"]["cue"] = "tampered"
            path.write_text(json.dumps(entry, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaises(HandoffIntegrityError):
                store.replay(caller_id="operator-1")

    def test_reordered_handoff_records_are_rejected(self):
        handoffs = prepared_handoffs()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoffs.jsonl"
            store = JsonLineHandoffStore(path)
            for handoff in handoffs:
                store.append(handoff)
            lines = path.read_text(encoding="utf-8").splitlines()
            path.write_text("\n".join(reversed(lines)) + "\n", encoding="utf-8")
            with self.assertRaises(HandoffIntegrityError):
                JsonLineHandoffStore(path).replay(caller_id="operator-1")


if __name__ == "__main__":
    unittest.main()
