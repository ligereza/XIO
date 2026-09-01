from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from XIO_LAYER.adapters import (
    APPLICATION_EVENT_CHANNEL,
    LucidaBridgeError,
    application_event_to_transport,
    transport_to_application_event,
)
from XIO_LAYER.core.transport import (
    DeliveryStatus,
    Endpoint,
    InMemoryTransport,
    TransportMessage,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "lucida_application_events.jsonl"
DESTINATION = Endpoint("memory", "lucida-queue")


def fixture_messages() -> tuple[TransportMessage, ...]:
    messages = []
    for line in FIXTURE_PATH.read_text(encoding="utf-8").splitlines():
        wire = json.loads(line)
        destination = Endpoint(**wire["destination"])
        messages.append(
            TransportMessage(
                source=wire["source"],
                destination=destination,
                channel=wire["channel"],
                payload=wire["payload"],
                sent_at=datetime.fromisoformat(wire["sent_at"]),
                message_id=wire["message_id"],
                sequence=wire["sequence"],
                idempotency_key=wire["idempotency_key"],
                envelope=wire["envelope"],
            )
        )
    return tuple(messages)


class LucidaBridgeTests(unittest.TestCase):
    def test_fixture_round_trip_preserves_event_fields_and_bytes(self):
        original_message = fixture_messages()[0]
        event = transport_to_application_event(original_message)
        rebuilt_message = application_event_to_transport(
            event,
            source=original_message.source,
            destination=original_message.destination,
            sent_at=original_message.sent_at,
            message_id=original_message.message_id,
        )
        round_trip = transport_to_application_event(rebuilt_message)

        self.assertEqual(round_trip.to_dict(), event.to_dict())
        self.assertEqual(event.event_id, "fixture-event-2")
        self.assertEqual(event.session_id, "fixture-session")
        self.assertEqual(event.peer_id, "fixture-peer")
        self.assertEqual(event.sequence, 2)
        self.assertEqual(event.payload["blob"], b"\x00\xff\x10")
        self.assertEqual(event.payload["label"], "fixture")
        self.assertEqual(event.raw_hash, original_message.payload["raw_hash"])
        self.assertEqual(rebuilt_message.channel, APPLICATION_EVENT_CHANNEL)

    def test_fixture_dedupe_and_sequence_are_enforced_offline(self):
        messages = fixture_messages()
        transport = InMemoryTransport()

        gap = transport.send(messages[0])
        first = transport.send(messages[1])
        duplicate = transport.send(messages[2])
        second = transport.send(messages[0])

        self.assertEqual(gap.status, DeliveryStatus.SEQUENCE_GAP)
        self.assertEqual(first.status, DeliveryStatus.ACCEPTED)
        self.assertEqual(duplicate.status, DeliveryStatus.DUPLICATE)
        self.assertEqual(second.status, DeliveryStatus.ACCEPTED)
        self.assertEqual([message.sequence for message in transport.messages()], [1, 2])

    def test_wrong_channel_is_rejected(self):
        message = fixture_messages()[0]
        with self.assertRaises(LucidaBridgeError):
            transport_to_application_event(replace(message, channel="signals"))

    def test_non_application_envelope_is_rejected(self):
        message = fixture_messages()[0]
        with self.assertRaises(LucidaBridgeError):
            transport_to_application_event(
                replace(message, envelope={"type": "osc", "schema_version": 1})
            )

    def test_invalid_payload_and_sequence_are_rejected(self):
        message = fixture_messages()[0]
        invalid_payload = dict(message.payload)
        invalid_payload.pop("raw_hash")
        with self.assertRaises(LucidaBridgeError):
            transport_to_application_event(replace(message, payload=invalid_payload))
        with self.assertRaises(LucidaBridgeError):
            transport_to_application_event(replace(message, sequence=9))

    def test_bridge_rejects_non_application_event_input(self):
        with self.assertRaises(LucidaBridgeError):
            application_event_to_transport(
                object(),
                source="lucida",
                destination=DESTINATION,
                sent_at=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
