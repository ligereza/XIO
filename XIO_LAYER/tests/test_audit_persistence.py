from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from XIO_LAYER.core.audit import (
    AuditLedger,
    AuditLedgerPersistenceError,
    JsonLineAuditLedger,
)
from XIO_LAYER.core.contracts import AuditEntry


class JsonLineAuditLedgerTests(unittest.TestCase):
    def test_audit_entry_restore_requires_exact_typed_contract(self):
        audit_entry = AuditLedger().append("probe", "subject-1", "recorded", {"safe": True}, "actor-1")
        wire = audit_entry.to_dict()
        invalid_payloads = []

        extra_field = dict(wire)
        extra_field["extra"] = True
        invalid_payloads.append(extra_field)

        wrong_actor = dict(wire)
        wrong_actor["actor_id"] = 7
        invalid_payloads.append(wrong_actor)

        wrong_details = dict(wire)
        wrong_details["details"] = []
        invalid_payloads.append(wrong_details)

        wrong_hash_type = dict(wire)
        wrong_hash_type["entry_hash"] = 7
        invalid_payloads.append(wrong_hash_type)

        for invalid in invalid_payloads:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    AuditEntry.from_dict(invalid)

        self.assertEqual(AuditEntry.from_dict(wire).to_dict(), wire)

    def test_concurrent_processes_preserve_audit_hash_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            script = (
                "import sys\n"
                "from XIO_LAYER.core.audit import JsonLineAuditLedger\n"
                "ledger = JsonLineAuditLedger(sys.argv[1])\n"
                "ledger.append('probe', 'subject-' + sys.argv[2], 'recorded', {'worker': sys.argv[2]})\n"
            )
            processes = [
                subprocess.Popen(
                    [sys.executable, "-c", script, str(path), str(index)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for index in range(4)
            ]
            for process in processes:
                stdout, stderr = process.communicate()
                self.assertEqual(process.returncode, 0, stderr)
                self.assertEqual(stdout, "")

            loaded = JsonLineAuditLedger(path)
            lock_exists = path.with_name(path.name + ".lock").exists()

        self.assertEqual(len(loaded.entries()), 4)
        self.assertTrue(loaded.verify())
        self.assertTrue(lock_exists)

    def test_entries_survive_restart_and_hash_chain_continues(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            ledger = JsonLineAuditLedger(path)
            first = ledger.append("selection", "selection-1", "accepted", {"source_app": "fixture-app"})

            restarted = JsonLineAuditLedger(path)
            second = restarted.append("handoff", "handoff-1", "prepared", {"event_id": "event-1"})
            loaded = JsonLineAuditLedger(path)

        self.assertEqual(len(loaded.entries()), 2)
        self.assertEqual(loaded.entries()[0].to_dict(), first.to_dict())
        self.assertEqual(loaded.entries()[1].to_dict(), second.to_dict())
        self.assertEqual(second.previous_hash, first.entry_hash)
        self.assertTrue(loaded.verify())

    def test_tampered_or_malformed_file_is_rejected_before_use(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            ledger = JsonLineAuditLedger(path)
            ledger.append("handoff", "handoff-1", "prepared", {"safe": True})
            original = path.read_text(encoding="utf-8")
            tampered = original.replace('"outcome": "prepared"', '"outcome": "failed"')
            path.write_text(tampered, encoding="utf-8")
            with self.assertRaises(AuditLedgerPersistenceError):
                JsonLineAuditLedger(path)

            path.write_text("not-json\n", encoding="utf-8")
            with self.assertRaises(AuditLedgerPersistenceError):
                JsonLineAuditLedger(path)

    def test_non_json_details_do_not_change_persisted_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            ledger = JsonLineAuditLedger(path)
            with self.assertRaises(AuditLedgerPersistenceError):
                ledger.append("handoff", "handoff-1", "prepared", {"bad": object()})

            self.assertEqual(ledger.entries(), ())
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
