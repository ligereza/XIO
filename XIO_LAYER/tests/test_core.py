from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from XIO_LAYER.adapters.xio import XioAdapter
from XIO_LAYER.core.audit import ActionGate, AuditLedger, PermissionRegistry
from XIO_LAYER.core.contracts import Checkpoint, Event, EventRecord, ExplicitAction, Proposal, Snapshot, TimestampError
from XIO_LAYER.core.events import DuplicateEventError, EventLog, replay_events
from XIO_LAYER.core.snapshots import (
    CheckpointConflictError,
    CheckpointStore,
    RecoveryManager,
    SnapshotProjector,
)
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
    def test_direct_temporal_contracts_reject_boolean_scalars(self):
        event = make_event("event-temporal", 1)
        with self.assertRaises(ValueError):
            Event(
                stream_id="demo",
                kind="add",
                source="test-device",
                occurred_at=T0,
                received_at=T0,
                payload={"value": 1},
                event_id="event-bool-schema",
                schema_version=True,
            )
        with self.assertRaises(ValueError):
            EventRecord(sequence=True, event=event)
        with self.assertRaises(ValueError):
            Snapshot(stream_id="demo", version=True, state={}, captured_at=T0)
        with self.assertRaises(ValueError):
            Checkpoint(stream_id="demo", sequence=True, state={}, source_event_id=None, captured_at=T0)

    def test_event_restore_requires_exact_typed_contract(self):
        event = make_event("event-restore", 1)
        wire = event.to_dict()
        invalid_payloads = []

        missing_payload = dict(wire)
        missing_payload.pop("payload")
        invalid_payloads.append(missing_payload)

        extra_field = dict(wire)
        extra_field["extra"] = True
        invalid_payloads.append(extra_field)

        wrong_sequence_schema = dict(wire)
        wrong_sequence_schema["schema_version"] = True
        invalid_payloads.append(wrong_sequence_schema)

        wrong_timestamp = dict(wire)
        wrong_timestamp["received_at"] = 7
        invalid_payloads.append(wrong_timestamp)

        for invalid in invalid_payloads:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    Event.from_dict(invalid)

        self.assertEqual(Event.from_dict(wire).to_dict(), wire)

    def test_persistent_event_log_assigns_unique_sequences_across_processes(self):
        events = [make_event(f"event-{number}", number) for number in range(1, 5)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            wire_path = Path(directory) / "events.json"
            wire_path.write_text(json.dumps([event.to_dict() for event in events]), encoding="utf-8")
            script = (
                "import json, sys\n"
                "from pathlib import Path\n"
                "from XIO_LAYER.core.contracts import Event\n"
                "from XIO_LAYER.core.events import EventLog\n"
                "wire = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))\n"
                "record = EventLog(sys.argv[1]).append(Event.from_dict(wire[int(sys.argv[3])]))\n"
                "print(record.sequence)\n"
            )
            processes = [
                subprocess.Popen(
                    [sys.executable, "-c", script, str(path), str(wire_path), str(index)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for index in range(4)
            ]
            sequences = []
            for process in processes:
                stdout, stderr = process.communicate()
                self.assertEqual(process.returncode, 0, stderr)
                sequences.append(int(stdout.strip()))

            loaded = EventLog(path)
            loaded_records = loaded.records()
            loaded_length = len(loaded)

        self.assertEqual(sorted(sequences), [1, 2, 3, 4])
        self.assertEqual([record.sequence for record in loaded_records], [1, 2, 3, 4])
        self.assertEqual(loaded_length, 4)

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
    def test_checkpoint_restore_requires_exact_typed_and_hashed_contract(self):
        checkpoint = Checkpoint(
            stream_id="demo",
            sequence=2,
            state={"total": 3},
            captured_at=T0,
            source_event_id="event-2",
            checkpoint_id="checkpoint-2",
        )
        wire = checkpoint.to_dict()
        invalid_payloads = []

        missing_hash = dict(wire)
        missing_hash.pop("state_hash")
        invalid_payloads.append(missing_hash)

        extra_field = dict(wire)
        extra_field["extra"] = True
        invalid_payloads.append(extra_field)

        wrong_sequence_type = dict(wire)
        wrong_sequence_type["sequence"] = True
        invalid_payloads.append(wrong_sequence_type)

        wrong_hash = dict(wire)
        wrong_hash["state_hash"] = "not-the-state-hash"
        invalid_payloads.append(wrong_hash)

        for invalid in invalid_payloads:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    Checkpoint.from_dict(invalid)

        self.assertEqual(Checkpoint.from_dict(wire).to_dict(), wire)

    def test_semantically_inconsistent_checkpoint_falls_back_to_full_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            event_path = Path(directory) / "events.jsonl"
            checkpoint_path = Path(directory) / "checkpoints"
            log = EventLog(event_path)
            for number in range(1, 4):
                log.append(make_event(f"event-{number}", number))
            projector = SnapshotProjector(add_reducer)
            checkpoints = CheckpointStore(checkpoint_path)
            checkpoints.save(
                Snapshot(
                    stream_id="demo",
                    version=2,
                    state={"total": 999},
                    captured_at=T0,
                    source_event_id="event-2",
                    snapshot_id="inconsistent-checkpoint",
                )
            )

            recovered = RecoveryManager(checkpoints).recover("demo", EventLog(event_path), projector)

        self.assertFalse(recovered.used_checkpoint)
        self.assertEqual(recovered.replayed_events, 3)
        self.assertEqual(recovered.snapshot.state, {"total": 6})
        self.assertIn("checkpoint state does not match event replay", recovered.issues)

    def test_checkpoint_version_is_idempotent_but_conflicts_are_rejected(self):
        first = Snapshot(
            stream_id="demo",
            version=2,
            state={"total": 3},
            captured_at=T0,
            source_event_id="event-2",
            snapshot_id="snapshot-2",
        )
        conflict = Snapshot(
            stream_id="demo",
            version=2,
            state={"total": 99},
            captured_at=T0,
            source_event_id="event-2",
            snapshot_id="snapshot-2-conflict",
        )
        with tempfile.TemporaryDirectory() as directory:
            store = CheckpointStore(Path(directory) / "checkpoints")
            saved = store.save(first)
            repeated = store.save(first)
            with self.assertRaises(CheckpointConflictError):
                store.save(conflict)
            loaded = store.load_latest("demo")

        self.assertEqual(saved.to_dict(), repeated.to_dict())
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.to_dict(), saved.to_dict())

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
