from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from XIO_LAYER.adapters import (
    DuplicateLucidaInputError,
    LucidaInputContractError,
    LucidaInputLog,
    LucidaInputRecord,
    PrivacyPolicy,
)
from XIO_LAYER.core.events import ApplicationEvent


T0 = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "lucida_input_events.jsonl"


def make_record(event_id: str, sequence: int) -> LucidaInputRecord:
    return LucidaInputRecord(
        event_id=event_id,
        source="fixture-source",
        source_version="fixture-1",
        event_type="fixture.value",
        event_time=T0,
        sequence=sequence,
        capability="observe.value",
        privacy_status="summary_only",
        data_summary={
            "kind": "mapping",
            "item_count": 1,
            "fields": [{"name": "value", "type": "integer"}],
            "truncated": False,
        },
    )


class LucidaInputRecordTests(unittest.TestCase):
    def test_application_event_projection_is_bounded_and_redacted(self):
        event = ApplicationEvent(
            event_id="event-redacted",
            source_app="fixture-source",
            event_type="fixture.value",
            channel="signals",
            payload={"safe": 7, "secret": b"private-bytes"},
            source_timestamp=T0,
            received_timestamp=T0,
            session_id="session-1",
            peer_id="peer-1",
            sequence=1,
            provenance={"origin": "synthetic"},
        )

        record = LucidaInputRecord.from_application_event(
            event,
            source_version="fixture-1",
            capability="observe.value",
            privacy_policy=PrivacyPolicy(allowed_payload_keys=frozenset({"safe"})),
        )

        self.assertEqual(record.privacy_status, "redacted")
        self.assertEqual(record.data_summary["fields"], [{"name": "safe", "type": "integer"}])
        encoded = json.dumps(record.to_dict(), sort_keys=True)
        self.assertNotIn("secret", encoded)
        self.assertNotIn("private-bytes", encoded)

    def test_invalid_inputs_are_rejected_without_coercion(self):
        record = make_record("input-invalid", 1)
        with self.assertRaises(TypeError):
            LucidaInputLog("unused.jsonl").append(object())
        with self.assertRaises(LucidaInputContractError):
            LucidaInputRecord.from_application_event(
                object(), source_version="fixture-1", capability="observe.value"
            )
        with self.assertRaises(LucidaInputContractError):
            LucidaInputRecord.from_dict({**record.to_dict(), "sequence": True})
        with self.assertRaises(LucidaInputContractError):
            LucidaInputRecord.from_dict({key: value for key, value in record.to_dict().items() if key != "capability"})
        invalid_summary = dict(record.to_dict())
        invalid_summary["data_summary"] = {
            "kind": "mapping",
            "item_count": 1,
            "fields": [{"name": "value", "type": "integer"}],
            "truncated": "false",
        }
        with self.assertRaises(LucidaInputContractError):
            LucidaInputRecord.from_dict(invalid_summary)


class LucidaInputLogTests(unittest.TestCase):
    def test_fixture_replays_in_sequence_and_deduplicates_delivery(self):
        log = LucidaInputLog(FIXTURE_PATH)
        records = log.replay()

        self.assertEqual([record.event_id for record in records], ["fixture-input-1", "fixture-input-2"])
        self.assertEqual([record.sequence for record in records], [1, 2])
        self.assertEqual(
            set(records[0].to_dict()),
            {
                "event_id",
                "source",
                "source_version",
                "event_type",
                "event_time",
                "sequence",
                "capability",
                "privacy_status",
                "data_summary",
            },
        )
        self.assertFalse(log.append(records[0]))
        with self.assertRaises(DuplicateLucidaInputError):
            log.append(replace(records[0], sequence=3))

    def test_explicit_replacement_replays_without_mutating_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lucida-input.jsonl"
            log = LucidaInputLog(path)
            original = make_record("input-original", 1)
            replacement = make_record("input-replacement", 2)

            self.assertTrue(log.append(original))
            self.assertTrue(log.replace(original.event_id, replacement))
            self.assertEqual([item.event_id for item in log.replay()], [replacement.event_id])
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 2)

            with self.assertRaises(LucidaInputContractError):
                log.replace(original.event_id, replacement)

    def test_replacement_requires_new_id_and_existing_input(self):
        with tempfile.TemporaryDirectory() as directory:
            log = LucidaInputLog(Path(directory) / "lucida-input.jsonl")
            record = make_record("input-1", 1)
            with self.assertRaises(LucidaInputContractError):
                log.replace("missing-input", record)
            log.append(record)
            with self.assertRaises(LucidaInputContractError):
                log.replace(record.event_id, record)


if __name__ == "__main__":
    unittest.main()
