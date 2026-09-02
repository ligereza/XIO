from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from typing import Any, Mapping

from XIO_LAYER.adapters import (
    AdapterSelection,
    CandidateNotAvailableError,
    NoRouteMatchError,
    PrivacyPolicy,
    PrivacyPolicyError,
    SourceAdapterRegistry,
    StaleRoutePlanError,
    deliver_adapter_handoff,
    prepare_adapter_handoff,
    transport_to_application_event,
)
from XIO_LAYER.core.audit import AuditLedger
from XIO_LAYER.core.events import ApplicationEvent, ApplicationEventLog
from XIO_LAYER.core.transport import Endpoint, InMemoryTransport


T0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
DESTINATION = Endpoint("memory", "lucida-handoff")


class CountingAdapter:
    def __init__(self, source_app: str):
        self.source_app = source_app
        self.supported_event_types = {"cue.event"}
        self.capabilities = {"source.observe"}
        self.calls: list[Mapping[str, Any]] = []

    def convert(self, record: Mapping[str, Any], event_type: str) -> ApplicationEvent:
        self.calls.append(record)
        return ApplicationEvent(
            event_id=record["event_id"],
            source_app=self.source_app,
            event_type=event_type,
            channel="signals",
            payload=record["payload"],
            source_timestamp=T0,
            received_timestamp=T0,
            session_id="private-session",
            peer_id="private-peer",
            sequence=record["sequence"],
            provenance=record["provenance"],
        )


def make_record() -> dict[str, Any]:
    return {
        "event_id": "event-handoff-1",
        "sequence": 1,
        "payload": {"safe": "stand-a", "secret": "do-not-export"},
        "provenance": {"origin": "local-stand", "secret": "private-note"},
    }


class AdapterHandoffTests(unittest.TestCase):
    def make_registry(self) -> tuple[SourceAdapterRegistry, CountingAdapter, CountingAdapter]:
        registry = SourceAdapterRegistry()
        first = CountingAdapter("first-app")
        second = CountingAdapter("second-app")
        registry.register(first)
        registry.register(second)
        return registry, first, second

    def test_caller_selection_is_explicit_and_does_not_call_adapters(self):
        registry, first, second = self.make_registry()
        plan = registry.route_plan("cue.event", {"source.observe"})

        selection = registry.select_candidate(
            source_app="second-app",
            event_type="cue.event",
            required_capabilities={"source.observe"},
            caller_id="operator-1",
            plan=plan,
            selection_id="selection-1",
            selected_at=T0,
        )

        self.assertIsInstance(selection, AdapterSelection)
        self.assertEqual(selection.source_app, "second-app")
        self.assertEqual(first.calls, [])
        self.assertEqual(second.calls, [])

    def test_selection_rejects_no_match_and_non_candidate_without_fallback(self):
        registry, first, second = self.make_registry()

        with self.assertRaises(NoRouteMatchError):
            registry.select_candidate(
                source_app="first-app",
                event_type="missing.event",
                caller_id="operator-1",
            )
        with self.assertRaises(CandidateNotAvailableError):
            registry.select_candidate(
                source_app="missing-app",
                event_type="cue.event",
                caller_id="operator-1",
            )
        self.assertEqual(first.calls, [])
        self.assertEqual(second.calls, [])

    def test_modified_plan_or_selection_is_rejected(self):
        registry, _, _ = self.make_registry()
        plan = registry.route_plan("cue.event")

        with self.assertRaises(StaleRoutePlanError):
            registry.select_candidate(
                source_app="first-app",
                event_type="cue.event",
                caller_id="operator-1",
                plan={**plan, "status": "no_match"},
            )

        selection = registry.select_candidate(
            source_app="first-app",
            event_type="cue.event",
            caller_id="operator-1",
            plan=plan,
            selection_id="selection-1",
            selected_at=T0,
        )
        audit = AuditLedger()
        with self.assertRaises(StaleRoutePlanError):
            prepare_adapter_handoff(
                registry,
                replace(selection, plan_fingerprint="stale-plan"),
                make_record(),
                source="xio-layer",
                destination=DESTINATION,
                audit=audit,
            )
        self.assertEqual(audit.entries()[0].event_type, "adapter.handoff.rejected")

    def test_handoff_projects_private_data_and_only_prepares_transport(self):
        registry, first, second = self.make_registry()
        selection = registry.select_candidate(
            source_app="second-app",
            event_type="cue.event",
            caller_id="operator-1",
            plan=registry.route_plan("cue.event"),
            selection_id="selection-1",
            selected_at=T0,
        )
        audit = AuditLedger()
        transport = InMemoryTransport()
        handoff = prepare_adapter_handoff(
            registry,
            selection,
            make_record(),
            source="xio-layer",
            destination=DESTINATION,
            audit=audit,
            privacy_policy=PrivacyPolicy(
                allowed_payload_keys=frozenset({"safe"}),
                allowed_provenance_keys=frozenset({"origin"}),
            ),
            handoff_id="handoff-1",
        )

        self.assertEqual(first.calls, [])
        self.assertEqual(len(second.calls), 1)
        self.assertEqual(handoff.event.payload, {"safe": "stand-a"})
        self.assertEqual(handoff.event.provenance["origin"], "local-stand")
        self.assertNotIn("secret", json.dumps(handoff.message.to_dict(), sort_keys=True))
        self.assertNotEqual(handoff.event.session_id, "private-session")
        self.assertNotEqual(handoff.event.peer_id, "private-peer")
        self.assertEqual(transport.messages(), ())
        self.assertTrue(audit.verify())
        self.assertEqual(audit.entries()[-1].event_type, "adapter.handoff.prepared")
        self.assertNotIn("do-not-export", json.dumps(audit.entries()[-1].to_dict(), sort_keys=True))
        self.assertNotIn("private-note", json.dumps(audit.entries()[-1].to_dict(), sort_keys=True))
        self.assertNotIn("operator-1", json.dumps(handoff.to_dict(), sort_keys=True))

        first_delivery = deliver_adapter_handoff(handoff, transport, audit)
        duplicate_delivery = deliver_adapter_handoff(handoff, transport, audit)
        self.assertEqual(first_delivery.status, "accepted")
        self.assertEqual(duplicate_delivery.status, "duplicate")
        self.assertEqual(len(transport.messages()), 1)
        self.assertTrue(audit.verify())

    def test_blocked_delivery_is_rejected_and_audited_without_retry_or_fallback(self):
        registry, _, _ = self.make_registry()
        selection = registry.select_candidate(
            source_app="first-app",
            event_type="cue.event",
            caller_id="operator-1",
            plan=registry.route_plan("cue.event"),
            selection_id="selection-1",
            selected_at=T0,
        )
        audit = AuditLedger()
        handoff = prepare_adapter_handoff(
            registry,
            selection,
            make_record(),
            source="xio-layer",
            destination=DESTINATION,
            audit=audit,
            handoff_id="handoff-1",
        )

        class BlockedTransport:
            def send(self, message):
                raise PermissionError("blocked by injected policy")

        result = deliver_adapter_handoff(handoff, BlockedTransport(), audit)

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error, "PermissionError")
        self.assertEqual(audit.entries()[-1].event_type, "adapter.handoff.delivery_rejected")
        self.assertTrue(audit.verify())

    def test_prepared_handoff_round_trips_and_replays_without_execution(self):
        registry, _, _ = self.make_registry()
        selection = registry.select_candidate(
            source_app="first-app",
            event_type="cue.event",
            caller_id="operator-1",
            plan=registry.route_plan("cue.event"),
            selection_id="selection-1",
            selected_at=T0,
        )
        audit = AuditLedger()
        handoff = prepare_adapter_handoff(
            registry,
            selection,
            make_record(),
            source="xio-layer",
            destination=DESTINATION,
            audit=audit,
            privacy_policy=PrivacyPolicy(allowed_payload_keys=frozenset({"safe"})),
            handoff_id="handoff-1",
        )
        event = transport_to_application_event(handoff.message)
        with tempfile.TemporaryDirectory() as directory:
            log = ApplicationEventLog(Path(directory) / "events.jsonl")
            self.assertTrue(log.append(event))
            replay = log.replay(
                lambda state, item: {
                    "events": state.get("events", 0) + 1,
                    "last_event": item.event_id,
                }
            )

        self.assertEqual(replay.applied_events, 1)
        self.assertEqual(replay.state["last_event"], "event-handoff-1")
        self.assertTrue(audit.verify())

    def test_privacy_policy_rejects_non_ascii_keys(self):
        with self.assertRaises(PrivacyPolicyError):
            PrivacyPolicy(allowed_payload_keys=frozenset({"se" + chr(0xF1) + "al"}))


if __name__ == "__main__":
    unittest.main()
