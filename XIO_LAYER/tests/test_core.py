from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from XIO_LAYER.adapters.xio import XioAdapter
from XIO_LAYER.core.audit import ActionGate, AuditLedger, PermissionRegistry
from XIO_LAYER.core.contracts import Event, ExplicitAction, Proposal, TimestampError
from XIO_LAYER.core.events import DuplicateEventError, EventLog, replay_events
from XIO_LAYER.core.snapshots import CheckpointStore, RecoveryManager, SnapshotProjector
from XIO_LAYER.core.transport import Endpoint, InMemoryTransport, TransportMessage, TransportPolicy


UTC = timezone.utc
T0 = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


def add_reducer(state, event):
    next_state = dict(state)
    if event.kind == "add":
        next_state["total"] = next_state.get("total", 0) + event.payload["value"]
    elif event.kind == "set":
        next_state["total"] = event.payload["value"]
    return next_state


def make_event(event_id: str, value: int, occurred_offset: int = 0, received_offset: int = 0):
    return Event(
        stream_id="demo",
        kind="add",
        source="test-device",
        occurred_at=T0 + timedelta(seconds=occurred_offset),
        received_at=T0 + timedelta(seconds=received_offset),
        payload={"value": value},
        event_id=event_id,
    )


class EventAndReplayTests(unittest.TestCase):
    def test_duplicate_identical_event_is_idempotent_and_conflict_is_rejected(self):
        log = EventLog()
        event = make_event("event-1", 2)

        first = log.append(event)
        second = log.append(event)

        self.assertEqual(first, second)
        self.assertEqual(len(log), 1)
        with self.assertRaises(DuplicateEventError):
            log.append(make_event("event-1", 99))

    def test_out_of_order_source_timestamps_use_ingestion_sequence(self):
        log = EventLog()
        first = log.append(make_event("event-1", 1, occurred_offset=20, received_offset=1))
        second = log.append(make_event("event-2", 2, occurred_offset=10, received_offset=2))

        replay = replay_events(log.records("demo"), add_reducer)

        self.assertEqual([first.sequence, second.sequence], [1, 2])
        self.assertEqual(replay.state["total"], 3)
        self.assertEqual(replay.applied_events, 2)
        self.assertEqual(replay.source_clock_ahead_events, 2)

    def test_naive_timestamps_are_rejected(self):
        with self.assertRaises(TimestampError):
            Event(
                stream_id="demo",
                kind="sample",
                source="test",
                occurred_at=datetime(2026, 8, 31, 12, 0),
                received_at=T0,
            )

    def test_replay_materializes_snapshot_without_dispatching_action(self):
        log = EventLog()
        log.append(make_event("event-1", 3))
        log.append(make_event("event-2", 4))
        projector = SnapshotProjector(add_reducer)

        snapshot = projector.project("demo", log.records("demo"))

        self.assertEqual(snapshot.state, {"total": 7})
        self.assertEqual(snapshot.version, 2)
        self.assertEqual(snapshot.source_event_id, "event-2")


class PermissionAuditAndTransportTests(unittest.TestCase):
    def test_revoked_permission_denies_pending_explicit_action(self):
        permissions = PermissionRegistry()
        audit = AuditLedger()
        gate = ActionGate(permissions, audit)
        called = []
        permissions.grant("user-1", "device.write")
        action = ExplicitAction(
            proposal_id="proposal-1",
            action_type="device.write",
            parameters={"value": 1},
            actor_id="user-1",
            requested_at=T0,
            explicitly_confirmed=True,
        )
        permissions.revoke("user-1", "device.write")

        result = gate.execute(action, "device.write", lambda _: called.append(True))

        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error, "permission_missing_or_revoked")
        self.assertEqual(called, [])
        self.assertTrue(audit.verify())
        self.assertEqual(audit.entries()[0].outcome, "denied")

    def test_proposal_and_unconfirmed_action_cannot_execute(self):
        permissions = PermissionRegistry()
        audit = AuditLedger()
        gate = ActionGate(permissions, audit)
        proposal = Proposal(
            stream_id="demo",
            action_type="device.write",
            parameters={},
            created_at=T0,
            reason="test only",
        )
        with self.assertRaises(TypeError):
            gate.execute(proposal, "device.write", lambda _: {})

        permissions.grant("user-1", "device.write")
        action = ExplicitAction(
            proposal_id=proposal.proposal_id,
            action_type="device.write",
            parameters={},
            actor_id="user-1",
            requested_at=T0,
            explicitly_confirmed=False,
        )
        result = gate.execute(action, "device.write", lambda _: {})
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error, "explicit_confirmation_required")

    def test_local_transport_is_idempotent_and_network_policy_is_explicit(self):
        local = InMemoryTransport()
        message = TransportMessage(
            source="xio-layer",
            destination=Endpoint("memory", "local-queue"),
            channel="events",
            payload={"kind": "sample"},
        )
        first = local.send(message)
        second = local.send(message)
        self.assertTrue(first.accepted)
        self.assertTrue(second.duplicate)
        self.assertEqual(len(local.messages()), 1)

        network_disabled = InMemoryTransport(TransportPolicy(allow_network=False))
        network_message = TransportMessage(
            source="xio-layer",
            destination=Endpoint("tcp", "127.0.0.1:9000"),
            channel="events",
            payload={},
        )
        with self.assertRaises(PermissionError):
            network_disabled.send(network_message)


class RecoveryTests(unittest.TestCase):
    def test_recovery_uses_checkpoint_then_replays_remaining_events(self):
        with tempfile.TemporaryDirectory() as directory:
            event_path = Path(directory) / "events.jsonl"
            checkpoint_path = Path(directory) / "checkpoints"
            log = EventLog(event_path)
            log.append(make_event("event-1", 1))
            log.append(make_event("event-2", 2))
            log.append(make_event("event-3", 4))
            projector = SnapshotProjector(add_reducer)
            first_snapshot = projector.project("demo", log.records("demo")[:2])
            checkpoints = CheckpointStore(checkpoint_path)
            checkpoints.save(first_snapshot)

            recovered = RecoveryManager(checkpoints).recover("demo", EventLog(event_path), projector)

            self.assertTrue(recovered.used_checkpoint)
            self.assertEqual(recovered.replayed_events, 1)
            self.assertEqual(recovered.snapshot.state, {"total": 7})

    def test_corrupt_checkpoint_is_reported_and_full_replay_recovers_state(self):
        with tempfile.TemporaryDirectory() as directory:
            event_path = Path(directory) / "events.jsonl"
            checkpoint_path = Path(directory) / "checkpoints"
            log = EventLog(event_path)
            for number in range(1, 4):
                log.append(make_event(f"event-{number}", number))
            projector = SnapshotProjector(add_reducer)
            checkpoints = CheckpointStore(checkpoint_path)
            checkpoints.save(projector.project("demo", log.records("demo")))
            checkpoint_file = next(checkpoint_path.glob("*.json"))
            checkpoint_file.write_text("{not-json", encoding="utf-8")

            recovered = RecoveryManager(checkpoints).recover("demo", EventLog(event_path), projector)

            self.assertFalse(recovered.used_checkpoint)
            self.assertEqual(recovered.replayed_events, 3)
            self.assertEqual(recovered.snapshot.state, {"total": 6})
            self.assertEqual(len(recovered.issues), 1)


class XioBoundaryTests(unittest.TestCase):
    def test_xio_adapter_observes_and_requires_explicit_action(self):
        event = make_event("event-1", 1)
        executed = []

        class Observer:
            def observe(self):
                return [event]

        class Executor:
            def execute(self, action):
                executed.append(action.action_id)
                return {"ok": True}

        permissions = PermissionRegistry()
        audit = AuditLedger()
        adapter = XioAdapter(Observer(), Executor(), ActionGate(permissions, audit))
        self.assertEqual(adapter.observe(), (event,))
        unconfirmed = ExplicitAction(
            proposal_id="proposal-1",
            action_type="device.write",
            parameters={},
            actor_id="user-1",
            requested_at=T0,
            explicitly_confirmed=False,
        )
        result = adapter.execute_explicit(unconfirmed, "device.write")
        self.assertEqual(result.status, "denied")
        self.assertEqual(executed, [])


if __name__ == "__main__":
    unittest.main()
