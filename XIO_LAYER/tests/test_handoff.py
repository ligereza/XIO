from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import tempfile
import unittest
from typing import Any, Mapping

from XIO_LAYER.adapters import (
    AdapterHandoff,
    AdapterHandoffDelivery,
    AdapterHandoffError,
    AdapterSelection,
    CandidateNotAvailableError,
    InvalidSourceAdapterError,
    NoRouteMatchError,
    PrivacyPolicy,
    PrivacyPolicyError,
    SourceAdapterRegistry,
    StaleRoutePlanError,
    deliver_adapter_handoff,
    prepare_adapter_handoff,
    transport_to_application_event,
)
from XIO_LAYER.core.audit import AuditLedger, PermissionRegistry
from XIO_LAYER.core.events import ApplicationEvent, ApplicationEventLog
from XIO_LAYER.core.transport import DeliveryReceipt, Endpoint, InMemoryTransport


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
        restored = AdapterSelection.from_dict(selection.to_dict())
        registry.validate_selection(restored)
        self.assertEqual(restored, selection)
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
        restored = AdapterHandoff.from_dict(handoff.to_dict(), caller_id="operator-1")
        self.assertEqual(restored.event.to_dict(), handoff.event.to_dict())
        self.assertEqual(restored.message.fingerprint, handoff.message.fingerprint)
        self.assertEqual(restored.selection, handoff.selection)
        with self.assertRaises(AdapterHandoffError):
            AdapterHandoff.from_dict(handoff.to_dict())
        invalid_message = handoff.to_dict()
        invalid_message["message"] = {**invalid_message["message"], "message_id": 7}
        with self.assertRaises(AdapterHandoffError):
            AdapterHandoff.from_dict(invalid_message, caller_id="operator-1")
        invalid_sequence = handoff.to_dict()
        invalid_sequence["message"] = {**invalid_sequence["message"], "sequence": True}
        with self.assertRaises(AdapterHandoffError):
            AdapterHandoff.from_dict(invalid_sequence, caller_id="operator-1")

        permissions = PermissionRegistry()
        permissions.grant("operator-1", "handoff.deliver")
        first_delivery = deliver_adapter_handoff(
            handoff,
            transport,
            audit,
            permissions=permissions,
        )
        duplicate_delivery = deliver_adapter_handoff(
            handoff,
            transport,
            audit,
            permissions=permissions,
        )
        self.assertEqual(first_delivery.status, "accepted")
        self.assertEqual(duplicate_delivery.status, "duplicate")
        self.assertEqual(len(transport.messages()), 1)
        self.assertTrue(audit.verify())

    def test_direct_handoff_constructor_rejects_invalid_contracts(self):
        registry, _, _ = self.make_registry()
        selection = registry.select_candidate(
            source_app="first-app",
            event_type="cue.event",
            caller_id="operator-1",
            plan=registry.route_plan("cue.event"),
            selection_id="selection-direct",
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
            handoff_id="handoff-direct",
        )

        with self.assertRaisesRegex(TypeError, "AdapterSelection"):
            replace(handoff, selection=object())
        with self.assertRaisesRegex(TypeError, "TransportMessage"):
            replace(handoff, message=object())
        mismatched_event = ApplicationEvent(
            event_id=handoff.event.event_id,
            schema_version=handoff.event.schema_version,
            source_app=handoff.event.source_app,
            event_type=handoff.event.event_type,
            channel=handoff.event.channel,
            payload={"safe": "different"},
            source_timestamp=handoff.event.source_timestamp,
            received_timestamp=handoff.event.received_timestamp,
            session_id=handoff.event.session_id,
            peer_id=handoff.event.peer_id,
            sequence=handoff.event.sequence,
            provenance=handoff.event.provenance,
        )
        with self.assertRaisesRegex(AdapterHandoffError, "do not match"):
            replace(handoff, event=mismatched_event)

    def test_privacy_policy_rejects_ambiguous_key_collections(self):
        with self.assertRaisesRegex(PrivacyPolicyError, "allowed_payload_keys"):
            PrivacyPolicy(allowed_payload_keys="safe")
        with self.assertRaisesRegex(PrivacyPolicyError, "allowed_provenance_keys"):
            PrivacyPolicy(allowed_provenance_keys={"origin": True})
        with self.assertRaisesRegex(PrivacyPolicyError, "allowed_payload_keys"):
            PrivacyPolicy(allowed_payload_keys=["safe", 7])

    def test_privacy_projection_rejects_invalid_selection_and_handoff_id(self):
        event = ApplicationEvent(
            event_id="event-privacy-input",
            source_app="first-app",
            event_type="cue.event",
            channel="signals",
            payload={"safe": True},
            source_timestamp=T0,
            received_timestamp=T0,
            session_id="private-session",
            peer_id="private-peer",
            sequence=1,
            provenance={},
        )
        policy = PrivacyPolicy()
        with self.assertRaises(TypeError):
            policy.project(event, selection=object(), handoff_id="handoff-1")
        registry, _, _ = self.make_registry()
        selection = registry.select_candidate(
            source_app="first-app",
            event_type="cue.event",
            caller_id="operator-1",
            plan=registry.route_plan("cue.event"),
            selection_id="selection-privacy-input",
            selected_at=T0,
        )
        with self.assertRaisesRegex(PrivacyPolicyError, "handoff_id"):
            policy.project(event, selection=selection, handoff_id="bad id")

    def test_delivery_result_constructor_rejects_incoherent_receipts(self):
        with self.assertRaisesRegex(TypeError, "DeliveryReceipt"):
            AdapterHandoffDelivery("handoff-1", "accepted", object(), T0)
        with self.assertRaisesRegex(AdapterHandoffError, "require a receipt"):
            AdapterHandoffDelivery("handoff-1", "accepted", None, T0)
        with self.assertRaisesRegex(AdapterHandoffError, "duplicate receipt"):
            AdapterHandoffDelivery(
                "handoff-1",
                "duplicate",
                DeliveryReceipt("message-1", accepted=True),
                T0,
            )
        with self.assertRaisesRegex(TypeError, "error"):
            AdapterHandoffDelivery("handoff-1", "rejected", None, T0, error=7)

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
        permissions = PermissionRegistry()
        permissions.grant("operator-1", "handoff.deliver")

        class BlockedTransport:
            def send(self, message):
                raise PermissionError("blocked by injected policy")

        result = deliver_adapter_handoff(
            handoff,
            BlockedTransport(),
            audit,
            permissions=permissions,
        )

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error, "PermissionError")
        self.assertEqual(audit.entries()[-1].event_type, "adapter.handoff.delivery_rejected")
        self.assertTrue(audit.verify())

    def test_revoked_delivery_permission_blocks_transport_side_effect(self):
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
        permissions = PermissionRegistry()
        permissions.grant("operator-1", "handoff.deliver")
        permissions.revoke("operator-1", "handoff.deliver")

        class CountingTransport:
            def __init__(self):
                self.calls = 0

            def send(self, message):
                self.calls += 1
                raise AssertionError("transport must not be called after permission revocation")

        transport = CountingTransport()
        result = deliver_adapter_handoff(
            handoff,
            transport,
            audit,
            permissions=permissions,
        )

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error, "permission_missing_or_revoked")
        self.assertEqual(transport.calls, 0)
        self.assertEqual(audit.entries()[-1].outcome, "rejected")
        self.assertTrue(audit.verify())

    def test_delivery_holds_permission_through_transport_send(self):
        registry, _, _ = self.make_registry()
        selection = registry.select_candidate(
            source_app="first-app",
            event_type="cue.event",
            caller_id="operator-1",
            plan=registry.route_plan("cue.event"),
            selection_id="selection-atomic",
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
            handoff_id="handoff-atomic",
        )
        permissions = PermissionRegistry()
        permissions.grant("operator-1", "handoff.deliver")
        send_started = threading.Event()
        release_send = threading.Event()
        revoke_finished = threading.Event()

        class BlockingTransport:
            def send(self, message):
                send_started.set()
                self.assert_message(message)
                self.release.wait(1.0)
                return DeliveryReceipt(message.message_id, accepted=True)

            def assert_message(self, message):
                self.message_id = message.message_id

            @property
            def release(self):
                return release_send

        transport = BlockingTransport()
        delivery_result = []
        delivery_thread = threading.Thread(
            target=lambda: delivery_result.append(
                deliver_adapter_handoff(handoff, transport, audit, permissions=permissions)
            )
        )
        delivery_thread.start()
        self.assertTrue(send_started.wait(1.0))

        def revoke():
            permissions.revoke("operator-1", "handoff.deliver")
            revoke_finished.set()

        revoke_thread = threading.Thread(target=revoke)
        revoke_thread.start()
        self.assertFalse(revoke_finished.wait(0.05))
        release_send.set()
        delivery_thread.join(1.0)
        revoke_thread.join(1.0)

        self.assertFalse(delivery_thread.is_alive())
        self.assertTrue(revoke_finished.is_set())
        self.assertEqual(len(delivery_result), 1)
        self.assertEqual(delivery_result[0].status, "accepted")
        self.assertTrue(audit.verify())

    def test_idempotency_conflict_is_terminal_and_not_retried(self):
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
            message_id="message-conflict",
            handoff_id="handoff-1",
        )
        permissions = PermissionRegistry()
        permissions.grant("operator-1", "handoff.deliver")
        transport = InMemoryTransport()
        conflicting_message = replace(handoff.message, payload={"different": True})
        self.assertTrue(transport.send(conflicting_message).accepted)

        result = deliver_adapter_handoff(
            handoff,
            transport,
            audit,
            permissions=permissions,
        )

        self.assertEqual(result.status, "conflict")
        self.assertEqual(result.receipt.error, "idempotency_conflict")
        self.assertEqual(len(transport.messages()), 1)
        self.assertEqual(audit.entries()[-1].event_type, "adapter.handoff.delivery_conflict")
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

    def test_selection_restore_rejects_extra_fields(self):
        registry, _, _ = self.make_registry()
        selection = registry.select_candidate(
            source_app="first-app",
            event_type="cue.event",
            caller_id="operator-1",
            selection_id="selection-1",
            selected_at=T0,
        )
        invalid = {**selection.to_dict(), "unexpected": True}
        with self.assertRaises(InvalidSourceAdapterError):
            AdapterSelection.from_dict(invalid)


if __name__ == "__main__":
    unittest.main()
