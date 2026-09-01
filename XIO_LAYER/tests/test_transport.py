from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import unittest

from XIO_LAYER.core.transport import (
    ArtNetEnvelope,
    ConnectionState,
    DeliveryStatus,
    Endpoint,
    InMemoryTransport,
    JsonLineTransport,
    NetworkMedium,
    NetworkScope,
    OscEnvelope,
    TransportMessage,
    TransportPolicy,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def message(endpoint, *, sequence=None, envelope=None, message_id="message-1", idempotency_key=None, sent_at=T0):
    return TransportMessage(
        source="xio-layer-test",
        destination=endpoint,
        channel="control",
        payload={"kind": "test"},
        sent_at=sent_at,
        message_id=message_id,
        sequence=sequence,
        idempotency_key=idempotency_key,
        envelope=envelope,
    )


class TransportTests(unittest.TestCase):
    def test_order_and_timestamps_are_reported(self):
        endpoint = Endpoint(
            "tcp",
            "10.0.0.10",
            medium=NetworkMedium.ETHERNET,
            scope=NetworkScope.LAN,
            port=9000,
        )
        transport = InMemoryTransport(
            TransportPolicy(allowed_scopes=frozenset({NetworkScope.LAN})),
            clock=lambda: T0 + timedelta(milliseconds=25),
        )

        receipt = transport.send(message(endpoint, sequence=1))
        status = transport.status(endpoint)

        self.assertTrue(receipt.accepted)
        self.assertEqual(receipt.status, DeliveryStatus.ACCEPTED)
        self.assertEqual(receipt.sequence, 1)
        self.assertEqual(receipt.latency_ms, 25.0)
        self.assertEqual(status.state, ConnectionState.CONNECTED)
        self.assertEqual(status.last_sequence, 1)
        self.assertEqual(status.packets_sent, 1)
        self.assertEqual(status.packets_received, 1)

    def test_duplicate_is_idempotent_and_conflicting_key_is_an_error(self):
        endpoint = Endpoint("memory", "queue")
        transport = InMemoryTransport()
        original = message(endpoint, idempotency_key="idem-1")

        first = transport.send(original)
        duplicate = transport.send(original)
        conflict = transport.send(
            message(endpoint, idempotency_key="idem-1", message_id="message-2")
        )

        self.assertEqual(first.status, DeliveryStatus.ACCEPTED)
        self.assertEqual(duplicate.status, DeliveryStatus.DUPLICATE)
        self.assertEqual(conflict.status, DeliveryStatus.IDEMPOTENCY_CONFLICT)
        self.assertEqual(len(transport.messages()), 1)

    def test_messages_out_of_sequence_are_not_delivered(self):
        endpoint = Endpoint("memory", "queue")
        transport = InMemoryTransport()

        first = transport.send(message(endpoint, sequence=1, message_id="message-1"))
        gap = transport.send(message(endpoint, sequence=3, message_id="message-3"))
        second = transport.send(message(endpoint, sequence=2, message_id="message-2"))
        late = transport.send(message(endpoint, sequence=2, message_id="message-2b"))

        self.assertTrue(first.accepted)
        self.assertEqual(gap.status, DeliveryStatus.SEQUENCE_GAP)
        self.assertTrue(second.accepted)
        self.assertEqual(late.status, DeliveryStatus.OUT_OF_SEQUENCE)
        self.assertEqual([item.sequence for item in transport.messages()], [1, 2])

    def test_unauthorized_endpoint_is_blocked(self):
        allowed = Endpoint("tcp", "10.0.0.10", scope=NetworkScope.LAN, port=9000)
        denied = Endpoint("tcp", "10.0.0.11", scope=NetworkScope.LAN, port=9000)
        transport = InMemoryTransport(
            TransportPolicy(
                allowed_peers=frozenset({allowed.address}),
                allowed_scopes=frozenset({NetworkScope.LAN}),
            )
        )

        self.assertTrue(transport.send(message(allowed)).accepted)
        with self.assertRaises(PermissionError):
            transport.send(message(denied, message_id="denied"))
        self.assertEqual(transport.status(denied).state, ConnectionState.BLOCKED)

    def test_lan_and_wan_are_not_interchangeable(self):
        lan = Endpoint(
            "tcp", "192.168.1.20", medium=NetworkMedium.WIFI,
            scope=NetworkScope.LAN, port=9000,
        )
        wan = Endpoint(
            "tcp", "198.51.100.20", medium=NetworkMedium.ROUTER,
            scope=NetworkScope.WAN, port=9000,
        )
        policy = TransportPolicy(allowed_scopes=frozenset({NetworkScope.LAN}))
        transport = InMemoryTransport(policy)

        self.assertTrue(lan.is_lan)
        self.assertFalse(lan.is_wan)
        self.assertTrue(wan.is_wan)
        self.assertFalse(wan.is_lan)
        self.assertTrue(transport.send(message(lan)).accepted)
        with self.assertRaises(PermissionError):
            transport.send(message(wan, message_id="wan"))

    def test_osc_and_artnet_remain_distinct_envelopes(self):
        endpoint = Endpoint("udp", "127.0.0.1", scope=NetworkScope.LAN, port=9000)
        transport = InMemoryTransport(
            TransportPolicy(allowed_scopes=frozenset({NetworkScope.LAN}))
        )
        osc = OscEnvelope("/xio/test", (1, "cue"), timetag=T0)
        artnet = ArtNetEnvelope(universe=2, data=b"\x00\xff\x7f", sequence=4)

        osc_receipt = transport.send(message(endpoint, envelope=osc, message_id="osc"))
        artnet_receipt = transport.send(message(endpoint, envelope=artnet, message_id="artnet"))

        self.assertTrue(osc_receipt.accepted)
        self.assertTrue(artnet_receipt.accepted)
        self.assertEqual(osc.protocol, "osc")
        self.assertEqual(artnet.protocol, "artnet")
        self.assertEqual(osc.to_dict()["arguments"][1], "cue")
        self.assertEqual(artnet.to_dict()["data_base64"], "AP9/")
        self.assertIsInstance(transport.messages()[0].envelope, OscEnvelope)
        self.assertIsInstance(transport.messages()[1].envelope, ArtNetEnvelope)

    def test_latency_and_loss_state_are_explicit(self):
        endpoint = Endpoint("memory", "queue")
        transport = InMemoryTransport(clock=lambda: T0)
        transport.send(message(endpoint))

        degraded = transport.mark_lost(endpoint, "timeout")

        self.assertEqual(degraded.state, ConnectionState.DEGRADED)
        self.assertEqual(degraded.packets_lost, 1)
        self.assertEqual(degraded.loss_ratio, 0.5)
        self.assertEqual(degraded.last_error, "timeout")

    def test_jsonline_transport_uses_injected_writer_without_opening_socket(self):
        written = []
        endpoint = Endpoint("udp", "10.0.0.10", scope=NetworkScope.LAN, port=9000)
        transport = JsonLineTransport(
            written.append,
            TransportPolicy(allowed_scopes=frozenset({NetworkScope.LAN})),
        )

        with patch("socket.socket", side_effect=AssertionError("socket must not open")) as socket_factory:
            receipt = transport.send(message(endpoint, message_id="wire"))

        self.assertTrue(receipt.accepted)
        self.assertEqual(socket_factory.call_count, 0)
        self.assertEqual(len(written), 1)
        self.assertIn(b'"scheme": "udp"', written[0])


if __name__ == "__main__":
    unittest.main()
