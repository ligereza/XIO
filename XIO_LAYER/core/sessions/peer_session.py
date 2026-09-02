"""Explicit peer sessions and directed fan-out over the Transport port.

This module has no discovery, socket, device, credential or action logic. A
caller supplies every peer and endpoint, and a caller decides what to do with
an observed signal after it has been delivered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from functools import wraps
from threading import RLock
from typing import Any, Iterable, Mapping
from uuid import uuid4

from ..contracts import content_hash, require_utc, utc_now
from ..transport import (
    ConnectionState,
    DeliveryReceipt,
    DeliveryStatus,
    Endpoint,
    Transport,
    TransportMessage,
    TransportPolicy,
)


HANDSHAKE_CHANNEL = "xio.handshake"
HANDSHAKE_ACK_CHANNEL = "xio.handshake.ack"


class UnknownPeerError(KeyError):
    """The caller referenced a peer that was not authorized."""


class VersionMismatchError(ValueError):
    """The peer protocol major versions are incompatible."""


class PeerSessionState(str, Enum):
    DISCONNECTED = ConnectionState.DISCONNECTED.value
    CONNECTED = ConnectionState.CONNECTED.value
    BLOCKED = ConnectionState.BLOCKED.value
    ERROR = ConnectionState.ERROR.value


class AckStatus(str, Enum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    OUT_OF_SEQUENCE = "out_of_sequence"
    SEQUENCE_GAP = "sequence_gap"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    UNKNOWN_PEER = "unknown_peer"
    VERSION_INCOMPATIBLE = "version_incompatible"
    DISCONNECTED = "disconnected"
    BLOCKED = "blocked"
    CAPABILITY_MISSING = "capability_missing"
    ERROR = "error"


def _synchronized(method):
    """Serialize one manager operation without changing its public contract."""

    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return guarded


def _endpoint_from_dict(data: Mapping[str, Any]) -> Endpoint:
    if not isinstance(data, Mapping) or set(data) != {"scheme", "address", "medium", "scope", "port"}:
        raise ValueError("endpoint fields do not match the contract")
    for field_name in ("scheme", "address", "medium", "scope"):
        _require_text(data[field_name], f"endpoint.{field_name}")
    port = data["port"]
    if port is not None and (
        isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535
    ):
        raise ValueError("endpoint.port must be between 1 and 65535")
    return Endpoint(
        scheme=data["scheme"],
        address=data["address"],
        medium=data["medium"],
        scope=data["scope"],
        port=port,
    )


def _require_text(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _capabilities(value: Any, field_name: str) -> frozenset[str]:
    if isinstance(value, (str, bytes, Mapping)):
        raise ValueError(f"{field_name} must be a collection of strings")
    try:
        values = tuple(value)
    except TypeError as exc:
        raise ValueError(f"{field_name} must be a collection of strings") from exc
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ValueError(f"{field_name} must contain non-empty strings")
    return frozenset(values)


@dataclass(frozen=True, slots=True)
class PeerDescriptor:
    peer_id: str
    protocol_version: str
    endpoint: Endpoint
    capabilities: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        _require_text(self.peer_id, "peer_id")
        _require_text(self.protocol_version, "protocol_version")
        if not isinstance(self.endpoint, Endpoint):
            raise ValueError("endpoint must be an Endpoint")
        object.__setattr__(self, "capabilities", _capabilities(self.capabilities, "capabilities"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "peer_id": self.peer_id,
            "protocol_version": self.protocol_version,
            "capabilities": sorted(self.capabilities),
            "endpoint": self.endpoint.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PeerDescriptor":
        required = {"peer_id", "protocol_version", "capabilities", "endpoint"}
        if not isinstance(data, Mapping) or set(data) != required:
            raise ValueError("peer descriptor fields do not match the contract")
        _require_text(data["peer_id"], "peer_id")
        _require_text(data["protocol_version"], "protocol_version")
        if not isinstance(data["capabilities"], list):
            raise ValueError("capabilities must be a list")
        return cls(
            peer_id=data["peer_id"],
            protocol_version=data["protocol_version"],
            capabilities=_capabilities(data["capabilities"], "capabilities"),
            endpoint=_endpoint_from_dict(data["endpoint"]),
        )


@dataclass(frozen=True, slots=True)
class HandshakeRequest:
    peer: PeerDescriptor
    session_id: str = field(default_factory=lambda: str(uuid4()))
    request_id: str = field(default_factory=lambda: str(uuid4()))
    requested_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not isinstance(self.peer, PeerDescriptor):
            raise ValueError("peer must be a PeerDescriptor")
        _require_text(self.session_id, "session_id")
        _require_text(self.request_id, "request_id")
        object.__setattr__(self, "requested_at", require_utc(self.requested_at, "requested_at"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "session_id": self.session_id,
            "requested_at": self.requested_at.isoformat(),
            "peer": self.peer.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HandshakeRequest":
        required = {"request_id", "session_id", "requested_at", "peer"}
        if not isinstance(data, Mapping) or set(data) != required:
            raise ValueError("handshake request fields do not match the contract")
        _require_text(data["request_id"], "request_id")
        _require_text(data["session_id"], "session_id")
        if not isinstance(data["requested_at"], str):
            raise ValueError("requested_at must be an ISO datetime")
        if not isinstance(data["peer"], Mapping):
            raise ValueError("peer must be a mapping")
        return cls(
            request_id=data["request_id"],
            session_id=data["session_id"],
            requested_at=datetime.fromisoformat(data["requested_at"]),
            peer=PeerDescriptor.from_dict(data["peer"]),
        )


@dataclass(frozen=True, slots=True)
class HandshakeAck:
    request_id: str
    session_id: str
    responder_peer_id: str
    protocol_version: str
    accepted: bool
    capabilities: frozenset[str] = frozenset()
    status: str = "accepted"
    reason: str | None = None
    responded_at: datetime = field(default_factory=utc_now)
    ack_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        for field_name in (
            "request_id",
            "session_id",
            "responder_peer_id",
            "protocol_version",
            "status",
            "ack_id",
        ):
            _require_text(getattr(self, field_name), field_name)
        if not isinstance(self.accepted, bool):
            raise ValueError("accepted must be a boolean")
        if self.reason is not None and not isinstance(self.reason, str):
            raise ValueError("reason must be a string or null")
        object.__setattr__(self, "responded_at", require_utc(self.responded_at, "responded_at"))
        object.__setattr__(self, "capabilities", _capabilities(self.capabilities, "capabilities"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ack_id": self.ack_id,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "responder_peer_id": self.responder_peer_id,
            "protocol_version": self.protocol_version,
            "accepted": self.accepted,
            "capabilities": sorted(self.capabilities),
            "status": self.status,
            "reason": self.reason,
            "responded_at": self.responded_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HandshakeAck":
        required = {
            "ack_id",
            "request_id",
            "session_id",
            "responder_peer_id",
            "protocol_version",
            "accepted",
            "capabilities",
            "status",
            "reason",
            "responded_at",
        }
        if not isinstance(data, Mapping) or set(data) != required:
            raise ValueError("handshake ack fields do not match the contract")
        for field_name in (
            "ack_id",
            "request_id",
            "session_id",
            "responder_peer_id",
            "protocol_version",
            "status",
        ):
            _require_text(data[field_name], field_name)
        if not isinstance(data["accepted"], bool):
            raise ValueError("accepted must be a boolean")
        if not isinstance(data["capabilities"], list):
            raise ValueError("capabilities must be a list")
        if data["reason"] is not None and not isinstance(data["reason"], str):
            raise ValueError("reason must be a string or null")
        if not isinstance(data["responded_at"], str):
            raise ValueError("responded_at must be an ISO datetime")
        return cls(
            ack_id=data["ack_id"],
            request_id=data["request_id"],
            session_id=data["session_id"],
            responder_peer_id=data["responder_peer_id"],
            protocol_version=data["protocol_version"],
            accepted=data["accepted"],
            capabilities=_capabilities(data["capabilities"], "capabilities"),
            status=data["status"],
            reason=data["reason"],
            responded_at=datetime.fromisoformat(data["responded_at"]),
        )


@dataclass(frozen=True, slots=True)
class SignalEnvelope:
    """A signal with peer/session metadata, never an action request."""

    source_peer_id: str
    session_id: str
    channel: str
    sequence: int
    payload: Mapping[str, Any]
    created_at: datetime = field(default_factory=utc_now)
    message_id: str = field(default_factory=lambda: str(uuid4()))
    idempotency_key: str | None = None
    protocol_envelope: Any | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("source_peer_id", "session_id", "channel", "message_id"):
            _require_text(getattr(self, field_name), field_name)
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or self.sequence < 1:
            raise ValueError("sequence must be a positive integer")
        if not isinstance(self.payload, Mapping):
            raise ValueError("payload must be a mapping")
        if self.idempotency_key is not None and not isinstance(self.idempotency_key, str):
            raise ValueError("idempotency_key must be a string or null")
        if (
            self.protocol_envelope is not None
            and not isinstance(self.protocol_envelope, Mapping)
            and not hasattr(self.protocol_envelope, "to_dict")
        ):
            raise ValueError("protocol_envelope must be a mapping, serializable envelope or null")
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be a mapping")
        object.__setattr__(self, "created_at", require_utc(self.created_at, "created_at"))
        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def fingerprint(self) -> str:
        return content_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        envelope = self.protocol_envelope.to_dict() if hasattr(self.protocol_envelope, "to_dict") else self.protocol_envelope
        return {
            "message_id": self.message_id,
            "source_peer_id": self.source_peer_id,
            "session_id": self.session_id,
            "channel": self.channel,
            "sequence": self.sequence,
            "payload": dict(self.payload),
            "created_at": self.created_at.isoformat(),
            "idempotency_key": self.idempotency_key,
            "protocol_envelope": envelope,
            "metadata": dict(self.metadata),
        }

    def to_transport_message(self, endpoint: Endpoint) -> TransportMessage:
        return TransportMessage(
            source=self.source_peer_id,
            destination=endpoint,
            channel=self.channel,
            payload=dict(self.payload),
            sent_at=self.created_at,
            message_id=self.message_id,
            sequence=self.sequence,
            idempotency_key=self.idempotency_key,
            envelope=self.protocol_envelope,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SignalEnvelope":
        required = {
            "message_id",
            "source_peer_id",
            "session_id",
            "channel",
            "sequence",
            "payload",
            "created_at",
            "idempotency_key",
            "protocol_envelope",
            "metadata",
        }
        if not isinstance(data, Mapping) or set(data) != required:
            raise ValueError("signal envelope fields do not match the contract")
        for field_name in ("message_id", "source_peer_id", "session_id", "channel"):
            _require_text(data[field_name], field_name)
        if (
            not isinstance(data["sequence"], int)
            or isinstance(data["sequence"], bool)
            or data["sequence"] < 1
        ):
            raise ValueError("sequence must be a positive integer")
        if not isinstance(data["payload"], Mapping):
            raise ValueError("payload must be a mapping")
        if not isinstance(data["created_at"], str):
            raise ValueError("created_at must be an ISO datetime")
        if data["idempotency_key"] is not None and not isinstance(data["idempotency_key"], str):
            raise ValueError("idempotency_key must be a string or null")
        if (
            data["protocol_envelope"] is not None
            and not isinstance(data["protocol_envelope"], Mapping)
        ):
            raise ValueError("protocol_envelope must be a mapping or null")
        if not isinstance(data["metadata"], Mapping):
            raise ValueError("metadata must be a mapping")
        return cls(
            message_id=data["message_id"],
            source_peer_id=data["source_peer_id"],
            session_id=data["session_id"],
            channel=data["channel"],
            sequence=data["sequence"],
            payload=data["payload"],
            created_at=datetime.fromisoformat(data["created_at"]),
            idempotency_key=data["idempotency_key"],
            protocol_envelope=data["protocol_envelope"],
            metadata=data["metadata"],
        )


@dataclass(frozen=True, slots=True)
class DeliveryAck:
    peer_id: str
    message_id: str
    accepted: bool
    status: str
    sequence: int | None = None
    fingerprint: str | None = None
    error: str | None = None
    received_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _require_text(self.peer_id, "peer_id")
        _require_text(self.message_id, "message_id")
        _require_text(self.status, "status")
        if not isinstance(self.accepted, bool):
            raise ValueError("accepted must be a boolean")
        if self.sequence is not None and (
            isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1
        ):
            raise ValueError("sequence must be a positive integer or null")
        for field_name in ("fingerprint", "error"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{field_name} must be a string or null")
        object.__setattr__(self, "received_at", require_utc(self.received_at, "received_at"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "peer_id": self.peer_id,
            "message_id": self.message_id,
            "accepted": self.accepted,
            "status": self.status,
            "sequence": self.sequence,
            "fingerprint": self.fingerprint,
            "error": self.error,
            "received_at": self.received_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DeliveryAck":
        required = {
            "peer_id",
            "message_id",
            "accepted",
            "status",
            "sequence",
            "fingerprint",
            "error",
            "received_at",
        }
        if not isinstance(data, Mapping) or set(data) != required:
            raise ValueError("delivery ack fields do not match the contract")
        _require_text(data["peer_id"], "peer_id")
        _require_text(data["message_id"], "message_id")
        _require_text(data["status"], "status")
        if not isinstance(data["accepted"], bool):
            raise ValueError("accepted must be a boolean")
        sequence = data["sequence"]
        if sequence is not None and (
            isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1
        ):
            raise ValueError("sequence must be a positive integer or null")
        for field_name in ("fingerprint", "error"):
            if data[field_name] is not None and not isinstance(data[field_name], str):
                raise ValueError(f"{field_name} must be a string or null")
        if not isinstance(data["received_at"], str):
            raise ValueError("received_at must be an ISO datetime")
        return cls(
            peer_id=data["peer_id"],
            message_id=data["message_id"],
            accepted=data["accepted"],
            status=data["status"],
            sequence=sequence,
            fingerprint=data["fingerprint"],
            error=data["error"],
            received_at=datetime.fromisoformat(data["received_at"]),
        )


@dataclass(frozen=True, slots=True)
class HandshakeAttempt:
    request: HandshakeRequest
    receipt: DeliveryReceipt


@dataclass(slots=True)
class _PeerSession:
    peer: PeerDescriptor
    session_id: str
    state: PeerSessionState = PeerSessionState.DISCONNECTED
    negotiated_capabilities: frozenset[str] = frozenset()
    last_sent_sequence: int = 0
    last_received_sequence: int = 0


def _major_version(version: str) -> int:
    try:
        return int(version.split(".", 1)[0])
    except (TypeError, ValueError):
        return -1


def versions_compatible(left: str, right: str) -> bool:
    """Allow minor revisions but reject malformed or different major versions."""

    left_major = _major_version(left)
    right_major = _major_version(right)
    return left_major >= 0 and left_major == right_major


class PeerSessionManager:
    """Manage caller-authorized peers and explicit sessions."""

    def __init__(
        self,
        local_peer: PeerDescriptor,
        transport: Transport,
        policy: TransportPolicy | None = None,
        authorized_peers: Iterable[PeerDescriptor] = (),
    ) -> None:
        self._lock = RLock()
        self.local_peer = local_peer
        self.transport = transport
        self.policy = policy or TransportPolicy()
        self._peers: dict[str, PeerDescriptor] = {}
        self._sessions: dict[str, _PeerSession] = {}
        self._revoked: set[str] = set()
        self._pending: dict[str, str] = {}
        self._received: dict[tuple[str, str], str] = {}
        self._sent: dict[tuple[str, str], str] = {}
        for peer in authorized_peers:
            self.authorize_peer(peer)

    @_synchronized
    def authorize_peer(self, peer: PeerDescriptor) -> None:
        if peer.peer_id == self.local_peer.peer_id:
            raise ValueError("local peer cannot authorize itself")
        self.policy.validate(peer.endpoint)
        self._peers[peer.peer_id] = peer
        self._revoked.discard(peer.peer_id)
        self._sessions.setdefault(peer.peer_id, _PeerSession(peer=peer, session_id=""))

    @_synchronized
    def revoke_peer(self, peer_id: str) -> None:
        if peer_id not in self._peers:
            raise UnknownPeerError(peer_id)
        self._revoked.add(peer_id)
        session = self._sessions[peer_id]
        session.state = PeerSessionState.BLOCKED
        session.negotiated_capabilities = frozenset()

    @_synchronized
    def disconnect(self, peer_id: str) -> None:
        session = self._require_peer(peer_id)
        session.state = PeerSessionState.DISCONNECTED
        session.negotiated_capabilities = frozenset()

    def _require_peer(self, peer_id: str) -> _PeerSession:
        if peer_id not in self._peers:
            raise UnknownPeerError(peer_id)
        return self._sessions[peer_id]

    def _blocked_or_unknown_ack(self, peer_id: str, message_id: str, sequence: int | None = None) -> DeliveryAck:
        status = AckStatus.BLOCKED if peer_id in self._revoked else AckStatus.UNKNOWN_PEER
        return DeliveryAck(peer_id, message_id, False, status.value, sequence=sequence, error=status.value)

    @_synchronized
    def initiate_handshake(self, peer_id: str) -> HandshakeAttempt:
        session = self._require_peer(peer_id)
        if peer_id in self._revoked:
            raise PermissionError(f"peer is revoked: {peer_id}")
        session.negotiated_capabilities = frozenset()
        self.policy.validate(session.peer.endpoint)
        request = HandshakeRequest(peer=self.local_peer)
        self._pending[request.request_id] = peer_id
        receipt = self.transport.send(
            TransportMessage(
                source=self.local_peer.peer_id,
                destination=session.peer.endpoint,
                channel=HANDSHAKE_CHANNEL,
                payload=request.to_dict(),
                message_id=request.request_id,
                idempotency_key=request.request_id,
            )
        )
        return HandshakeAttempt(request=request, receipt=receipt)

    @_synchronized
    def accept_handshake(self, request: HandshakeRequest) -> HandshakeAck:
        peer_id = request.peer.peer_id
        accepted = True
        status = AckStatus.ACCEPTED
        reason = None
        peer = self._peers.get(peer_id)
        if peer_id in self._revoked:
            accepted = False
            status = AckStatus.BLOCKED
            reason = "peer_revoked"
        elif peer is None:
            accepted = False
            status = AckStatus.UNKNOWN_PEER
            reason = "peer_not_authorized"
        else:
            try:
                self.policy.validate(request.peer.endpoint)
            except PermissionError as exc:
                accepted = False
                status = AckStatus.BLOCKED
                reason = str(exc)
            if accepted and not versions_compatible(self.local_peer.protocol_version, request.peer.protocol_version):
                accepted = False
                status = AckStatus.VERSION_INCOMPATIBLE
                reason = "protocol_major_version_mismatch"

        if accepted:
            session = self._sessions[peer_id]
            session.session_id = request.session_id
            session.state = PeerSessionState.CONNECTED
            session.negotiated_capabilities = frozenset(request.peer.capabilities)
        elif peer is not None:
            session = self._sessions[peer_id]
            session.negotiated_capabilities = frozenset()
            session.state = (
                PeerSessionState.BLOCKED
                if status is AckStatus.BLOCKED
                else PeerSessionState.ERROR
            )
        ack = HandshakeAck(
            request_id=request.request_id,
            session_id=request.session_id,
            responder_peer_id=self.local_peer.peer_id,
            protocol_version=self.local_peer.protocol_version,
            accepted=accepted,
            capabilities=self.local_peer.capabilities,
            status=status.value,
            reason=reason,
        )
        if peer is not None:
            try:
                self.transport.send(
                    TransportMessage(
                        source=self.local_peer.peer_id,
                        destination=request.peer.endpoint,
                        channel=HANDSHAKE_ACK_CHANNEL,
                        payload=ack.to_dict(),
                        message_id=ack.ack_id,
                        idempotency_key=ack.ack_id,
                    )
                )
            except PermissionError:
                pass
        return ack

    @_synchronized
    def complete_handshake(self, ack: HandshakeAck) -> bool:
        peer_id = self._pending.pop(ack.request_id, None)
        if peer_id is None:
            raise ValueError("handshake ack is not pending")
        session = self._require_peer(peer_id)
        session.negotiated_capabilities = frozenset()
        if ack.responder_peer_id != peer_id:
            session.state = PeerSessionState.ERROR
            raise ValueError("handshake responder does not match requested peer")
        if not ack.accepted:
            session.state = (
                PeerSessionState.BLOCKED
                if ack.status in {AckStatus.BLOCKED.value, AckStatus.UNKNOWN_PEER.value}
                else PeerSessionState.ERROR
            )
            return False
        if not versions_compatible(self.local_peer.protocol_version, ack.protocol_version):
            session.negotiated_capabilities = frozenset()
            session.state = PeerSessionState.ERROR
            raise VersionMismatchError(ack.protocol_version)
        session.session_id = ack.session_id
        session.state = PeerSessionState.CONNECTED
        session.negotiated_capabilities = frozenset(ack.capabilities)
        return True

    @_synchronized
    def state(self, peer_id: str) -> PeerSessionState:
        return self._require_peer(peer_id).state

    @_synchronized
    def fan_out(
        self,
        signal: SignalEnvelope,
        peer_ids: Iterable[str] | None = None,
        *,
        required_capability: str | None = None,
    ) -> dict[str, DeliveryAck]:
        if signal.source_peer_id != self.local_peer.peer_id:
            raise ValueError("signal source_peer_id must match local peer")
        if required_capability is not None and not required_capability.strip():
            raise ValueError("required_capability cannot be empty")
        targets = list(peer_ids) if peer_ids is not None else [
            peer_id for peer_id, session in self._sessions.items()
            if session.state is PeerSessionState.CONNECTED and peer_id not in self._revoked
        ]
        acks: dict[str, DeliveryAck] = {}
        for peer_id in targets:
            session = self._sessions.get(peer_id)
            if session is None:
                acks[peer_id] = self._blocked_or_unknown_ack(peer_id, signal.message_id, signal.sequence)
                continue
            if peer_id in self._revoked:
                acks[peer_id] = self._blocked_or_unknown_ack(peer_id, signal.message_id, signal.sequence)
                continue
            if session.state is not PeerSessionState.CONNECTED:
                acks[peer_id] = DeliveryAck(
                    peer_id, signal.message_id, False, AckStatus.DISCONNECTED.value,
                    sequence=signal.sequence, error=AckStatus.DISCONNECTED.value,
                )
                continue
            if required_capability is not None and required_capability not in session.negotiated_capabilities:
                acks[peer_id] = DeliveryAck(
                    peer_id, signal.message_id, False, AckStatus.CAPABILITY_MISSING.value,
                    sequence=signal.sequence, fingerprint=signal.fingerprint,
                    error=AckStatus.CAPABILITY_MISSING.value,
                )
                continue

            key = (peer_id, signal.message_id)
            previous = self._sent.get(key)
            if previous is not None:
                if previous != signal.fingerprint:
                    acks[peer_id] = DeliveryAck(
                        peer_id, signal.message_id, False, AckStatus.IDEMPOTENCY_CONFLICT.value,
                        sequence=signal.sequence, fingerprint=signal.fingerprint,
                        error=AckStatus.IDEMPOTENCY_CONFLICT.value,
                    )
                else:
                    acks[peer_id] = DeliveryAck(
                        peer_id, signal.message_id, True, AckStatus.DUPLICATE.value,
                        sequence=signal.sequence, fingerprint=signal.fingerprint,
                    )
                continue

            try:
                receipt = self.transport.send(signal.to_transport_message(session.peer.endpoint))
            except PermissionError as exc:
                acks[peer_id] = DeliveryAck(
                    peer_id, signal.message_id, False, AckStatus.BLOCKED.value,
                    sequence=signal.sequence, fingerprint=signal.fingerprint, error=str(exc),
                )
                continue
            ack = self._ack_from_receipt(peer_id, signal, receipt)
            acks[peer_id] = ack
            if ack.accepted:
                self._sent[key] = signal.fingerprint
                if signal.sequence > session.last_sent_sequence:
                    session.last_sent_sequence = signal.sequence
        return acks

    @staticmethod
    def _ack_from_receipt(peer_id: str, signal: SignalEnvelope, receipt: DeliveryReceipt) -> DeliveryAck:
        if receipt.duplicate:
            status = AckStatus.DUPLICATE.value
        elif receipt.accepted:
            status = AckStatus.ACCEPTED.value
        elif receipt.status is DeliveryStatus.OUT_OF_SEQUENCE:
            status = AckStatus.OUT_OF_SEQUENCE.value
        elif receipt.status is DeliveryStatus.SEQUENCE_GAP:
            status = AckStatus.SEQUENCE_GAP.value
        elif receipt.status is DeliveryStatus.IDEMPOTENCY_CONFLICT:
            status = AckStatus.IDEMPOTENCY_CONFLICT.value
        else:
            status = AckStatus.ERROR.value
        return DeliveryAck(
            peer_id,
            signal.message_id,
            receipt.accepted,
            status,
            sequence=signal.sequence,
            fingerprint=signal.fingerprint,
            error=receipt.error,
            received_at=receipt.delivered_at or utc_now(),
        )

    @_synchronized
    def receive_signal(self, signal: SignalEnvelope, from_peer_id: str) -> DeliveryAck:
        session = self._sessions.get(from_peer_id)
        if session is None:
            return self._blocked_or_unknown_ack(from_peer_id, signal.message_id, signal.sequence)
        if from_peer_id in self._revoked:
            return self._blocked_or_unknown_ack(from_peer_id, signal.message_id, signal.sequence)
        if signal.source_peer_id != from_peer_id:
            return DeliveryAck(
                from_peer_id, signal.message_id, False, AckStatus.ERROR.value,
                sequence=signal.sequence, error="source_peer_mismatch",
            )
        if session.state is not PeerSessionState.CONNECTED:
            return DeliveryAck(
                from_peer_id, signal.message_id, False, AckStatus.DISCONNECTED.value,
                sequence=signal.sequence, error=AckStatus.DISCONNECTED.value,
            )

        key = (from_peer_id, signal.message_id)
        previous = self._received.get(key)
        if previous is not None:
            status = AckStatus.DUPLICATE.value if previous == signal.fingerprint else AckStatus.IDEMPOTENCY_CONFLICT.value
            return DeliveryAck(
                from_peer_id, signal.message_id, status == AckStatus.DUPLICATE.value, status,
                sequence=signal.sequence, fingerprint=signal.fingerprint,
                error=None if status == AckStatus.DUPLICATE.value else status,
            )

        expected = session.last_received_sequence + 1
        if signal.sequence < expected:
            return DeliveryAck(
                from_peer_id, signal.message_id, False, AckStatus.OUT_OF_SEQUENCE.value,
                sequence=signal.sequence, fingerprint=signal.fingerprint,
                error=AckStatus.OUT_OF_SEQUENCE.value,
            )
        if signal.sequence > expected:
            return DeliveryAck(
                from_peer_id, signal.message_id, False, AckStatus.SEQUENCE_GAP.value,
                sequence=signal.sequence, fingerprint=signal.fingerprint,
                error=AckStatus.SEQUENCE_GAP.value,
            )

        self._received[key] = signal.fingerprint
        session.last_received_sequence = signal.sequence
        return DeliveryAck(
            from_peer_id, signal.message_id, True, AckStatus.ACCEPTED.value,
            sequence=signal.sequence, fingerprint=signal.fingerprint,
        )
