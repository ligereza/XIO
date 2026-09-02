from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from XIO_LAYER.adapters import ProtocolEventAdapter
from XIO_LAYER.core.contracts import TimestampError
from XIO_LAYER.core.events import (
    ApplicationEvent,
    ApplicationEventContractError,
    ApplicationEventLog,
    DuplicateApplicationEventError,
    replay_jsonl,
)
from XIO_LAYER.core.transport import ArtNetEnvelope, OscEnvelope


T0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def make_event(event_id: str, sequence: int, value: int, received_offset: int = 0):
    return ApplicationEvent(
        event_id=event_id,
        source_app="test-app",
        event_type="test.value",
        channel="signals",
        payload={"value": value},
        source_timestamp=T0 + timedelta(seconds=sequence),
        received_timestamp=T0 + timedelta(seconds=received_offset),
        session_id="session-1",
        peer_id="peer-1",
        sequence=sequence,
        provenance={"source": "fixture"},
    )


def reducer(state, event):
    next_state = dict(state)
    next_state.setdefault("values", []).append(event.payload["value"])
    return next_state


class ApplicationEventContractTests(unittest.TestCase):
    def test_explicit_falsy_event_id_is_rejected_instead_of_replaced(self):
        arguments = {
            "source_app": "test-app",
            "event_type": "test.value",
            "channel": "signals",
            "payload": {"value": 1},
            "source_timestamp": T0,
            "received_timestamp": T0,
            "session_id": "session-1",
            "peer_id": "peer-1",
            "sequence": 1,
            "provenance": {},
        }

        with self.assertRaises(ApplicationEventContractError):
            ApplicationEvent(**arguments, event_id="")
        with self.assertRaises(ApplicationEventContractError):
            ApplicationEvent(**arguments, event_id=0)

    def test_event_log_append_rejects_wrong_type_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            log = ApplicationEventLog(path)

            with self.assertRaisesRegex(TypeError, "ApplicationEvent"):
                log.append(object())

            self.assertFalse(path.exists())

    def test_direct_constructor_rejects_boolean_sequence_and_non_mapping_provenance(self):
        arguments = {
            "source_app": "test-app",
            "event_type": "test.value",
            "channel": "signals",
            "payload": {"value": 1},
            "source_timestamp": T0,
            "received_timestamp": T0,
            "session_id": "session-1",
            "peer_id": "peer-1",
            "provenance": {},
        }
        with self.assertRaises(ApplicationEventContractError):
            ApplicationEvent(**arguments, sequence=True)
        with self.assertRaises(ApplicationEventContractError):
            ApplicationEvent(**{**arguments, "sequence": 1, "provenance": []})

    def test_direct_constructor_rejects_non_json_payload_and_provenance(self):
        arguments = {
            "source_app": "test-app",
            "event_type": "test.value",
            "channel": "signals",
            "source_timestamp": T0,
            "received_timestamp": T0,
            "session_id": "session-1",
            "peer_id": "peer-1",
            "sequence": 1,
            "provenance": {},
        }
        with self.assertRaises(ApplicationEventContractError):
            ApplicationEvent(**arguments, payload={"value": float("nan")})
        with self.assertRaises(ApplicationEventContractError):
            ApplicationEvent(**{**arguments, "payload": {}, "provenance": {"unsafe": object()}})

    def test_restore_rejects_malformed_reversible_values_with_contract_error(self):
        event = make_event("event-malformed-values", 1, 10)
        invalid_bytes = event.to_dict()
        invalid_bytes["payload"] = {"blob": {"__xio_type__": "bytes", "base64": "%%%"}}
        invalid_datetime = event.to_dict()
        invalid_datetime["payload"] = {"when": {"__xio_type__": "datetime", "value": "not-a-date"}}

        for invalid in (invalid_bytes, invalid_datetime):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ApplicationEventContractError):
                    ApplicationEvent.from_dict(invalid)

    def test_restore_requires_exact_typed_application_event_contract(self):
        event = make_event("event-restore", 1, 10)
        wire = event.to_dict()
        invalid_payloads = []

        missing_provenance = dict(wire)
        missing_provenance.pop("provenance")
        invalid_payloads.append(missing_provenance)

        extra_field = dict(wire)
        extra_field["extra"] = True
        invalid_payloads.append(extra_field)

        wrong_sequence = dict(wire)
        wrong_sequence["sequence"] = True
        invalid_payloads.append(wrong_sequence)

        wrong_hash = dict(wire)
        wrong_hash["raw_hash"] = 7
        invalid_payloads.append(wrong_hash)

        for invalid in invalid_payloads:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ApplicationEventContractError):
                    ApplicationEvent.from_dict(invalid)

        self.assertEqual(ApplicationEvent.from_dict(wire).to_dict(), wire)

    def test_osc_payload_provenance_and_hash_round_trip(self):
        envelope = OscEnvelope("/xio/test", (1, "cue", b"\x00\xff"), timetag=T0)
        adapter = ProtocolEventAdapter("source-app", "session-1", "peer-1")

        event = adapter.from_osc(
            envelope,
            channel="signals",
            sequence=1,
            received_timestamp=T0 + timedelta(seconds=1),
        )
        round_trip = ApplicationEvent.from_dict(json.loads(json.dumps(event.to_dict())))

        self.assertEqual(event.source_app, "source-app")
        self.assertEqual(event.event_type, "osc.message")
        self.assertEqual(event.payload, envelope.to_dict())
        self.assertEqual(event.provenance["protocol"], "osc")
        self.assertEqual(event.provenance["envelope"], envelope.to_dict())
        self.assertEqual(round_trip.payload, event.payload)
        self.assertEqual(round_trip.raw_hash, event.raw_hash)

    def test_artnet_payload_keeps_binary_data_and_metadata(self):
        envelope = ArtNetEnvelope(universe=4, data=b"\x01\x02\xff", sequence=7, physical=2)
        adapter = ProtocolEventAdapter("source-app", "session-1", "peer-1")

        event = adapter.from_artnet(
            envelope,
            channel="dmx",
            sequence=1,
            source_timestamp=T0,
            received_timestamp=T0 + timedelta(milliseconds=5),
        )

        self.assertEqual(event.event_type, "artnet.frame")
        self.assertEqual(event.payload, envelope.to_dict())
        self.assertEqual(event.payload["data_base64"], "AQL/")
        self.assertEqual(event.payload["universe"], 4)
        self.assertEqual(event.provenance["protocol"], "artnet")

    def test_invalid_contract_is_rejected(self):
        with self.assertRaises(TimestampError):
            ApplicationEvent(
                event_id="invalid-time",
                source_app="test-app",
                event_type="test.value",
                channel="signals",
                payload={"value": 1},
                source_timestamp=datetime(2026, 9, 1, 12, 0),
                received_timestamp=T0,
                session_id="session-1",
                peer_id="peer-1",
                sequence=1,
                provenance={},
            )

        with self.assertRaises(ApplicationEventContractError):
            ApplicationEvent(
                event_id="bad-hash",
                source_app="test-app",
                event_type="test.value",
                channel="signals",
                payload={"value": 1},
                source_timestamp=T0,
                received_timestamp=T0,
                session_id="session-1",
                peer_id="peer-1",
                sequence=1,
                raw_hash="not-the-payload-hash",
                provenance={},
            )

        with self.assertRaises(ApplicationEventContractError):
            make_event("bad-sequence", 0, 1)


class ApplicationEventReplayTests(unittest.TestCase):
    def test_concurrent_processes_keep_identical_event_id_idempotent(self):
        event = make_event("event-1", 1, 10)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            wire_path = Path(directory) / "event.json"
            wire_path.write_text(json.dumps(event.to_dict()), encoding="utf-8")
            script = (
                "import json, sys\n"
                "from pathlib import Path\n"
                "from XIO_LAYER.core.events import ApplicationEvent, ApplicationEventLog\n"
                "wire = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))\n"
                "print(ApplicationEventLog(sys.argv[1]).append(ApplicationEvent.from_dict(wire)))\n"
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

            loaded = ApplicationEventLog(path)
            loaded_events = loaded.events()

        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 3)
        self.assertEqual([item.to_dict() for item in loaded_events], [event.to_dict()])

    def test_jsonl_replay_is_deterministic_by_sequence_and_skips_duplicate(self):
        first = make_event("event-1", 1, 10, received_offset=2)
        second = make_event("event-2", 2, 20, received_offset=1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text(
                "\n".join(
                    json.dumps(item, sort_keys=True)
                    for item in (second.to_dict(), first.to_dict(), first.to_dict())
                )
                + "\n",
                encoding="utf-8",
            )

            result = replay_jsonl(path, reducer)

        self.assertEqual(result.state, {"values": [10, 20]})
        self.assertEqual(result.applied_events, 2)
        self.assertEqual(result.duplicate_events, 1)
        self.assertEqual(result.source_clock_ahead_events, 1)

    def test_append_is_idempotent_and_conflicting_duplicate_is_rejected(self):
        event = make_event("event-1", 1, 10)
        conflict = make_event("event-1", 1, 99)
        with tempfile.TemporaryDirectory() as directory:
            log = ApplicationEventLog(Path(directory) / "events.jsonl")

            self.assertTrue(log.append(event))
            self.assertFalse(log.append(event))
            with self.assertRaises(DuplicateApplicationEventError):
                log.append(conflict)
            self.assertEqual(len(log.events()), 1)


if __name__ == "__main__":
    unittest.main()
