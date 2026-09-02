from __future__ import annotations

from datetime import datetime, timezone
import threading
import unittest

from XIO_LAYER.core.sessions import (
    AckStatus,
    DeliveryAck,
    HandshakeAck,
    HandshakeRequest,
    PeerDescriptor,
    PeerSessionManager,
    PeerSessionState,
    SignalEnvelope,
)
from XIO_LAYER.core.transport import (
    ArtNetEnvelope,
    DeliveryReceipt,
    DeliveryStatus,
    Endpoint,
    InMemoryTransport,
    NetworkScope,
    OscEnvelope,
    TransportPolicy,
)


T0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def peer(peer_id: str, version: str = "1.0", port: int | None = None) -> PeerDescriptor:
    return PeerDescriptor(
        peer_id=peer_id,
        protocol_version=version,
        capabilities=frozenset({"signal.observe", "signal.send"}),
        endpoint=Endpoint("memory", peer_id, scope=NetworkScope.LOCAL, port=port),
    )


def connected_pair(alice: PeerDescriptor | None = None, bob: PeerDescriptor | None = None):
    alice = alice or peer("alice")
    bob = bob or peer("bob")
    transport = InMemoryTransport()
    alice_session = PeerSessionManager(alice, transport, authorized_peers=[bob])
    bob_session = PeerSessionManager(bob, transport, authorized_peers=[alice])
    attempt = alice_session.initiate_handshake("bob")
    ack = bob_session.accept_handshake(attempt.request)
    return alice_session, bob_session, transport, ack, attempt


class SessionContractTests(unittest.TestCase):
    def test_session_records_round_trip_with_exact_wire_shape(self):
        descriptor = peer("alice")
        request = HandshakeRequest(
            peer=descriptor,
            session_id="session-1",
            request_id="request-1",
            requested_at=T0,
        )
        ack = HandshakeAck(
            request_id=request.request_id,
            session_id=request.session_id,
            responder_peer_id="bob",
            protocol_version="1.0",
            accepted=True,
            capabilities=frozenset({"signal.observe"}),
            responded_at=T0,
            ack_id="ack-1",
        )
        signal = SignalEnvelope(
            source_peer_id="alice",
            session_id=request.session_id,
            channel="signals",
            sequence=1,
            payload={"value": 7},
            created_at=T0,
            message_id="signal-1",
            idempotency_key="signal-key-1",
            protocol_envelope={"protocol": "custom", "value": 1},
            metadata={"source": "fixture"},
        )
        delivery_ack = DeliveryAck(
            peer_id="bob",
            message_id=signal.message_id,
            accepted=True,
            status=AckStatus.ACCEPTED.value,
            sequence=signal.sequence,
            fingerprint=signal.fingerprint,
            received_at=T0,
        )

        self.assertEqual(PeerDescriptor.from_dict(descriptor.to_dict()).to_dict(), descriptor.to_dict())
        self.assertEqual(HandshakeRequest.from_dict(request.to_dict()).to_dict(), request.to_dict())
        self.assertEqual(HandshakeAck.from_dict(ack.to_dict()).to_dict(), ack.to_dict())
        self.assertEqual(SignalEnvelope.from_dict(signal.to_dict()).to_dict(), signal.to_dict())
        self.assertEqual(DeliveryAck.from_dict(delivery_ack.to_dict()).to_dict(), delivery_ack.to_dict())

    def test_session_restore_rejects_missing_extra_and_coercible_values(self):
        descriptor = peer("alice")
        request = HandshakeRequest(peer=descriptor, session_id="session-1", request_id="request-1", requested_at=T0)
        ack = HandshakeAck(
            request_id="request-1",
            session_id="session-1",
            responder_peer_id="bob",
            protocol_version="1.0",
            accepted=True,
            capabilities=frozenset({"signal.observe"}),
            responded_at=T0,
            ack_id="ack-1",
        )
        signal = SignalEnvelope(
            source_peer_id="alice",
            session_id="session-1",
            channel="signals",
            sequence=1,
            payload={"value": 7},
            created_at=T0,
            message_id="signal-1",
        )
        delivery_ack = DeliveryAck(
            peer_id="bob",
            message_id="signal-1",
            accepted=True,
            status=AckStatus.ACCEPTED.value,
            sequence=1,
            received_at=T0,
        )

        cases = [
            (PeerDescriptor.from_dict, {**descriptor.to_dict(), "peer_id": 7}),
            (PeerDescriptor.from_dict, {key: value for key, value in descriptor.to_dict().items() if key != "endpoint"}),
            (HandshakeRequest.from_dict, {**request.to_dict(), "request_id": 7}),
            (HandshakeRequest.from_dict, {**request.to_dict(), "extra": True}),
            (HandshakeAck.from_dict, {**ack.to_dict(), "accepted": 1}),
            (HandshakeAck.from_dict, {**ack.to_dict(), "capabilities": "signal.observe"}),
            (SignalEnvelope.from_dict, {**signal.to_dict(), "sequence": True}),
            (SignalEnvelope.from_dict, {**signal.to_dict(), "payload": []}),
            (SignalEnvelope.from_dict, {**signal.to_dict(), "protocol_envelope": []}),
            (DeliveryAck.from_dict, {**delivery_ack.to_dict(), "accepted": "true"}),
            (DeliveryAck.from_dict, {**delivery_ack.to_dict(), "received_at": 7}),
        ]
        for parser, invalid in cases:
            with self.subTest(parser=parser.__qualname__, invalid=invalid):
                with self.assertRaises(ValueError):
                    parser(invalid)

    def test_direct_session_constructors_reject_coercible_types(self):
        descriptor = peer("alice")
        with self.assertRaises(ValueError):
            PeerDescriptor(peer_id=7, protocol_version="1.0", endpoint=descriptor.endpoint)
        with self.assertRaises(ValueError):
            HandshakeAck(
                request_id="request-1",
                session_id="session-1",
                responder_peer_id="bob",
                protocol_version="1.0",
                accepted=1,
            )
        with self.assertRaises(ValueError):
            SignalEnvelope(
                source_peer_id="alice",
                session_id="session-1",
                channel="signals",
                sequence=True,
                payload={},
            )
        with self.assertRaises(ValueError):
            DeliveryAck(
                peer_id="bob",
                message_id="signal-1",
                accepted=True,
                status=AckStatus.ACCEPTED.value,
                sequence=False,
            )


class HandshakeTests(unittest.TestCase):
    def test_explicit_handshake_connects_two_authorized_peers(self):
        alice_session, bob_session, transport, ack, attempt = connected_pair()

        self.assertTrue(ack.accepted)
        self.assertTrue(alice_session.complete_handshake(ack))
        self.assertEqual(alice_session.state("bob"), PeerSessionState.CONNECTED)
        self.assertEqual(bob_session.state("alice"), PeerSessionState.CONNECTED)
        channels = [item.channel for item in transport.messages()]
        self.assertIn("xio.handshake", channels)
        self.assertIn("xio.handshake.ack", channels)
        self.assertEqual(attempt.request.peer.peer_id, "alice")

    def test_unknown_peer_is_rejected_by_receiver(self):
        alice = peer("alice")
        bob = peer("bob")
        rogue = peer("rogue")
        transport = InMemoryTransport()
        bob_session = PeerSessionManager(bob, transport, authorized_peers=[alice])
        ack = bob_session.accept_handshake(HandshakeRequest(peer=rogue))

        self.assertFalse(ack.accepted)
        self.assertEqual(ack.status, AckStatus.UNKNOWN_PEER.value)

    def test_incompatible_protocol_version_is_rejected(self):
        alice = peer("alice", version="1.0")
        bob = peer("bob", version="2.0")
        alice_session, bob_session, _, ack, _ = connected_pair(alice, bob)

        self.assertFalse(ack.accepted)
        self.assertEqual(ack.status, AckStatus.VERSION_INCOMPATIBLE.value)
        self.assertFalse(alice_session.complete_handshake(ack))
        self.assertEqual(alice_session.state("bob"), PeerSessionState.ERROR)
        self.assertEqual(bob_session.state("alice"), PeerSessionState.ERROR)


class FanOutTests(unittest.TestCase):
    def setUp(self):
        self.alice = peer("alice")
        self.bob = peer("bob")
        self.carol = peer("carol")
        self.transport = InMemoryTransport()
        self.sender = PeerSessionManager(
            self.alice,
            self.transport,
            authorized_peers=[self.bob, self.carol],
        )
        self.bob_receiver = PeerSessionManager(
            self.bob,
            self.transport,
            authorized_peers=[self.alice],
        )
        self.carol_receiver = PeerSessionManager(
            self.carol,
            self.transport,
            authorized_peers=[self.alice],
        )
        for peer_id, receiver in (("bob", self.bob_receiver), ("carol", self.carol_receiver)):
            attempt = self.sender.initiate_handshake(peer_id)
            ack = receiver.accept_handshake(attempt.request)
            self.assertTrue(ack.accepted)
            self.assertTrue(self.sender.complete_handshake(ack))

    def make_signal(self, sequence: int, message_id: str) -> SignalEnvelope:
        return SignalEnvelope(
            source_peer_id="alice",
            session_id="alice-session",
            channel="signals",
            sequence=sequence,
            payload={"value": sequence},
            created_at=T0,
            message_id=message_id,
        )

    def test_directed_fan_out_reaches_two_authorized_peers(self):
        signal = self.make_signal(1, "signal-1")
        acks = self.sender.fan_out(signal, ["bob", "carol"])

        self.assertEqual(acks["bob"].status, AckStatus.ACCEPTED.value)
        self.assertEqual(acks["carol"].status, AckStatus.ACCEPTED.value)
        self.assertTrue(self.bob_receiver.receive_signal(signal, "alice").accepted)
        self.assertTrue(self.carol_receiver.receive_signal(signal, "alice").accepted)

    def test_capability_gate_allows_a_connected_peer_with_capability(self):
        signal = self.make_signal(1, "signal-capability-allowed")
        acks = self.sender.fan_out(
            signal,
            ["bob"],
            required_capability="signal.send",
        )

        self.assertTrue(acks["bob"].accepted)
        self.assertEqual(acks["bob"].status, AckStatus.ACCEPTED.value)
        self.assertTrue(self.bob_receiver.receive_signal(signal, "alice").accepted)

    def test_capability_gate_denies_a_connected_peer_without_capability(self):
        signal = self.make_signal(1, "signal-capability-denied")
        message_count = len(self.transport.messages())
        ack = self.sender.fan_out(
            signal,
            ["bob"],
            required_capability="media.render",
        )["bob"]

        self.assertFalse(ack.accepted)
        self.assertEqual(ack.status, AckStatus.CAPABILITY_MISSING.value)
        self.assertEqual(ack.error, AckStatus.CAPABILITY_MISSING.value)
        self.assertEqual(ack.sequence, signal.sequence)
        self.assertEqual(ack.fingerprint, signal.fingerprint)
        self.assertEqual(len(self.transport.messages()), message_count)

    def test_capability_gate_uses_negotiated_capabilities_not_stale_descriptor(self):
        stale_bob = peer("bob")
        stale_bob = PeerDescriptor(
            peer_id=stale_bob.peer_id,
            protocol_version=stale_bob.protocol_version,
            endpoint=stale_bob.endpoint,
            capabilities=frozenset({"signal.observe", "signal.send", "media.render"}),
        )
        actual_bob = peer("bob")
        sender = PeerSessionManager(self.alice, self.transport, authorized_peers=[stale_bob])
        receiver = PeerSessionManager(actual_bob, self.transport, authorized_peers=[self.alice])
        attempt = sender.initiate_handshake("bob")
        ack = receiver.accept_handshake(attempt.request)
        self.assertTrue(sender.complete_handshake(ack))

        signal = self.make_signal(1, "signal-capability-stale-descriptor")
        message_count = len(self.transport.messages())
        result = sender.fan_out(signal, ["bob"], required_capability="media.render")["bob"]

        self.assertFalse(result.accepted)
        self.assertEqual(result.status, AckStatus.CAPABILITY_MISSING.value)
        self.assertEqual(len(self.transport.messages()), message_count)

    def test_reconnect_refreshes_negotiated_capabilities(self):
        bob_with_render = PeerDescriptor(
            peer_id="bob",
            protocol_version="1.0",
            endpoint=peer("bob").endpoint,
            capabilities=frozenset({"signal.observe", "signal.send", "media.render"}),
        )
        sender = PeerSessionManager(self.alice, self.transport, authorized_peers=[bob_with_render])
        first_receiver = PeerSessionManager(bob_with_render, self.transport, authorized_peers=[self.alice])
        first_attempt = sender.initiate_handshake("bob")
        first_ack = first_receiver.accept_handshake(first_attempt.request)
        self.assertTrue(sender.complete_handshake(first_ack))
        first_signal = self.make_signal(1, "signal-render-before-reconnect")
        self.assertTrue(
            sender.fan_out(first_signal, ["bob"], required_capability="media.render")["bob"].accepted
        )

        sender.disconnect("bob")
        bob_without_render = peer("bob")
        second_receiver = PeerSessionManager(bob_without_render, self.transport, authorized_peers=[self.alice])
        second_attempt = sender.initiate_handshake("bob")
        second_ack = second_receiver.accept_handshake(second_attempt.request)
        self.assertTrue(sender.complete_handshake(second_ack))
        second_signal = self.make_signal(2, "signal-render-after-reconnect")
        result = sender.fan_out(
            second_signal,
            ["bob"],
            required_capability="media.render",
        )["bob"]

        self.assertFalse(result.accepted)
        self.assertEqual(result.status, AckStatus.CAPABILITY_MISSING.value)
        self.assertEqual(result.error, AckStatus.CAPABILITY_MISSING.value)

    def test_fan_out_without_capability_requirement_keeps_existing_behavior(self):
        signal = self.make_signal(1, "signal-capability-optional")
        acks = self.sender.fan_out(signal, ["bob"])

        self.assertTrue(acks["bob"].accepted)
        self.assertEqual(acks["bob"].status, AckStatus.ACCEPTED.value)

    def test_unknown_peer_and_revoked_peer_are_blocked(self):
        signal = self.make_signal(1, "signal-blocked")
        unknown = self.sender.fan_out(signal, ["ghost"])
        self.assertEqual(unknown["ghost"].status, AckStatus.UNKNOWN_PEER.value)

        self.sender.revoke_peer("bob")
        blocked = self.sender.fan_out(signal, ["bob"])
        self.assertEqual(blocked["bob"].status, AckStatus.BLOCKED.value)
        self.assertEqual(self.sender.state("bob"), PeerSessionState.BLOCKED)

    def test_duplicate_fan_out_is_idempotent_per_peer(self):
        signal = self.make_signal(1, "signal-duplicate")
        first = self.sender.fan_out(signal, ["bob", "carol"])
        message_count = len(self.transport.messages())
        second = self.sender.fan_out(signal, ["bob", "carol"])

        self.assertTrue(first["bob"].accepted)
        self.assertEqual(second["bob"].status, AckStatus.DUPLICATE.value)
        self.assertEqual(second["carol"].status, AckStatus.DUPLICATE.value)
        self.assertEqual(len(self.transport.messages()), message_count)

    def test_concurrent_fan_out_serializes_idempotency_per_peer(self):
        class BlockingTransport:
            def __init__(self):
                self.messages_seen = []
                self.lock = threading.Lock()
                self.first_send_started = threading.Event()
                self.release_first_send = threading.Event()

            def send(self, message):
                with self.lock:
                    self.messages_seen.append(message)
                    send_number = len(self.messages_seen)
                    if send_number == 1:
                        self.first_send_started.set()
                if send_number == 1:
                    self.release_first_send.wait(1.0)
                return DeliveryReceipt(
                    message_id=message.message_id,
                    accepted=True,
                    sequence=message.sequence,
                    delivered_at=T0,
                )

        controlled = BlockingTransport()
        self.sender.transport = controlled
        signal = self.make_signal(1, "signal-concurrent")
        results = []
        first = threading.Thread(
            target=lambda: results.append(self.sender.fan_out(signal, ["bob"])["bob"])
        )
        second = threading.Thread(
            target=lambda: results.append(self.sender.fan_out(signal, ["bob"])["bob"])
        )
        first.start()
        self.assertTrue(controlled.first_send_started.wait(1.0))
        second.start()
        self.assertEqual(len(controlled.messages_seen), 1)
        controlled.release_first_send.set()
        first.join(1.0)
        second.join(1.0)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(len(controlled.messages_seen), 1)
        self.assertEqual(sorted(ack.status for ack in results), [
            AckStatus.ACCEPTED.value,
            AckStatus.DUPLICATE.value,
        ])

    def test_conflicting_fingerprint_with_same_message_id_is_rejected(self):
        first = self.make_signal(1, "signal-conflict")
        conflict = SignalEnvelope(
            source_peer_id="alice",
            session_id="alice-session",
            channel="signals",
            sequence=1,
            payload={"value": 999},
            created_at=T0,
            message_id="signal-conflict",
        )
        self.sender.fan_out(first, ["bob"])
        ack = self.sender.fan_out(conflict, ["bob"])["bob"]

        self.assertEqual(ack.status, AckStatus.IDEMPOTENCY_CONFLICT.value)
        self.assertFalse(ack.accepted)

    def test_out_of_sequence_signal_is_rejected_by_transport(self):
        first = self.make_signal(1, "signal-1")
        gap = self.make_signal(3, "signal-3")

        self.assertEqual(
            self.sender.fan_out(first, ["bob"])["bob"].status,
            AckStatus.ACCEPTED.value,
        )
        ack = self.sender.fan_out(gap, ["bob"])["bob"]
        self.assertEqual(ack.status, AckStatus.SEQUENCE_GAP.value)
        self.assertEqual(ack.error, DeliveryStatus.SEQUENCE_GAP.value)

    def test_signal_protocol_envelopes_keep_their_type_and_metadata(self):
        osc = self.make_signal(1, "signal-osc")
        osc = SignalEnvelope(
            source_peer_id=osc.source_peer_id,
            session_id=osc.session_id,
            channel=osc.channel,
            sequence=osc.sequence,
            payload=osc.payload,
            created_at=osc.created_at,
            message_id=osc.message_id,
            protocol_envelope=OscEnvelope("/xio/test", (1, "cue"), timetag=T0),
        )
        artnet = SignalEnvelope(
            source_peer_id="alice",
            session_id="alice-session",
            channel="signals",
            sequence=2,
            payload={},
            created_at=T0,
            message_id="signal-artnet",
            protocol_envelope=ArtNetEnvelope(universe=4, data=b"\x01\x02", sequence=2),
        )

        osc_message = osc.to_transport_message(self.bob.endpoint)
        artnet_message = artnet.to_transport_message(self.bob.endpoint)

        self.assertIsInstance(osc_message.envelope, OscEnvelope)
        self.assertIsInstance(artnet_message.envelope, ArtNetEnvelope)
        self.assertEqual(osc_message.envelope.to_dict()["address"], "/xio/test")
        self.assertEqual(artnet_message.envelope.to_dict()["universe"], 4)


if __name__ == "__main__":
    unittest.main()
