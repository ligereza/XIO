from __future__ import annotations

from datetime import datetime, timezone
import unittest

from XIO_LAYER.core.sessions import (
    AckStatus,
    HandshakeRequest,
    PeerDescriptor,
    PeerSessionManager,
    PeerSessionState,
    SignalEnvelope,
)
from XIO_LAYER.core.transport import (
    ArtNetEnvelope,
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
