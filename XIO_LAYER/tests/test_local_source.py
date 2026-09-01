from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from XIO_LAYER.adapters import (
    DuplicateLocalEventError,
    LocalAdapterEventSource,
    LocalEventSourceError,
    PrivacyPolicy,
    SourceAdapterRegistry,
    prepare_adapter_handoff,
    transport_to_application_event,
)
from XIO_LAYER.core.audit import AuditLedger
from XIO_LAYER.core.events import ApplicationEventLog
from XIO_LAYER.core.transport import Endpoint

from XIO_LAYER.tests.test_handoff import CountingAdapter


T0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "lucida_handoff_records.jsonl"
DESTINATION = Endpoint("memory", "lucida-fixture")


class LocalEventSourceTests(unittest.TestCase):
    def test_fixture_replay_deduplicates_and_orders_by_ingestion_sequence(self):
        records = LocalAdapterEventSource(FIXTURE_PATH).replay()

        self.assertEqual([record.event_id for record in records], ["local-event-1", "local-event-2"])
        self.assertEqual([record.sequence for record in records], [1, 2])
        self.assertGreater(records[0].source_timestamp, records[0].received_timestamp)
        self.assertEqual(records[0].payload["private_note"], "drop-me")

    def test_conflicting_duplicate_is_rejected(self):
        source = LocalAdapterEventSource(FIXTURE_PATH)
        first = source.replay()[0].to_dict()
        conflicting = dict(first)
        conflicting["payload"] = {"cue": "changed"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            path.write_text(
                json.dumps(first, sort_keys=True) + "\n" + json.dumps(conflicting, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(DuplicateLocalEventError):
                LocalAdapterEventSource(path).replay()

    def test_fixture_connects_selected_adapter_to_lucida_bridge_and_replay(self):
        registry = SourceAdapterRegistry()
        adapter = CountingAdapter("fixture-app")
        registry.register(adapter)
        selection = registry.select_candidate(
            source_app="fixture-app",
            event_type="cue.event",
            caller_id="operator-1",
            plan=registry.route_plan("cue.event", {"source.observe"}),
            required_capabilities={"source.observe"},
            selected_at=T0,
            selection_id="fixture-selection",
        )
        audit = AuditLedger()
        handoffs = LocalAdapterEventSource(FIXTURE_PATH).prepare_handoffs(
            registry,
            selection,
            source="xio-layer",
            destination=DESTINATION,
            audit=audit,
            privacy_policy=PrivacyPolicy(
                allowed_payload_keys=frozenset({"cue"}),
                allowed_provenance_keys=frozenset({"origin"}),
            ),
        )
        events = tuple(transport_to_application_event(item.message) for item in handoffs)
        with tempfile.TemporaryDirectory() as directory:
            log = ApplicationEventLog(Path(directory) / "lucida-events.jsonl")
            for event in events:
                self.assertTrue(log.append(event))
            replay = log.replay(
                lambda state, event: {
                    "count": state.get("count", 0) + 1,
                    "last_cue": event.payload["cue"],
                }
            )

        self.assertEqual(len(handoffs), 2)
        self.assertEqual([event.sequence for event in events], [1, 2])
        self.assertEqual([event.payload for event in events], [{"cue": "intro"}, {"cue": "outro"}])
        self.assertNotIn("private_note", json.dumps([event.to_dict() for event in events], sort_keys=True))
        self.assertEqual(len(adapter.calls), 2)
        self.assertEqual(replay.state, {"count": 2, "last_cue": "outro"})
        self.assertEqual(len(audit.entries()), 2)
        self.assertTrue(audit.verify())

    def test_source_refuses_records_outside_the_caller_selected_route(self):
        registry = SourceAdapterRegistry()
        adapter = CountingAdapter("other-app")
        registry.register(adapter)
        selection = registry.select_candidate(
            source_app="other-app",
            event_type="cue.event",
            caller_id="operator-1",
            plan=registry.route_plan("cue.event"),
            selection_id="selection-1",
            selected_at=T0,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            path.write_text(FIXTURE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
            with self.assertRaises(LocalEventSourceError):
                LocalAdapterEventSource(path).prepare_handoffs(
                    registry,
                    selection,
                    source="xio-layer",
                    destination=DESTINATION,
                    audit=AuditLedger(),
                )
        self.assertEqual(adapter.calls, [])


if __name__ == "__main__":
    unittest.main()
