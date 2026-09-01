"""Offline-first transport contracts and in-memory delivery.

TRANSPORT moves envelopes. It does not collect signals, analyse them, or decide
actions. Network writers are injected by a host; this package never opens a
socket or discovers peers on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
from threading import RLock
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

from ..contracts import content_hash, require_utc, utc_now


class NetworkMedium(str, Enum):
    ETHERNET = "ethernet"
    WIFI = "wifi"
    HOTSPOT = "hotspot"
    ROUTER = "router"
    UNKNOWN = "unknown"


class NetworkScope(str, Enum):
    """Reachability scope; WAN is not a synonym for a faster LAN."""

    LOCAL = "local"
    LAN = "lan"
    WAN = "wan"


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    ERROR = "error"
    UNKNOWN = "unknown"


class DeliveryStatus(str, Enum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    OUT_OF_SEQUENCE = "out_of_sequence"
    SEQUENCE_GAP = "sequence_gap"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    ERROR = "error"


class Transport(Protocol):
    def send(self, message: "TransportMessage") -> "DeliveryReceipt": ...


@dataclass(frozen=True, slots=True)
class Endpoint:
    """A destination plus its physical medium and reachability scope."""

    scheme: str
    address: str
    medium: NetworkMedium | str | None = None
    scope: NetworkScope | str | None = None
    port: int | None = None

    def __post_init__(self) -> None:
        scheme = self.scheme.strip().lower()
        if not scheme or not self.address.strip():
            raise ValueError("endpoint scheme and address cannot be empty")
        object.__setattr__(self, "scheme", scheme)
        medium = NetworkMedium.UNKNOWN if self.medium is None else NetworkMedium(self.medium)
        scope = (
            NetworkScope.LOCAL
            if self.scope is None and scheme in {"memory", "unix"}
            else NetworkScope.LAN
            if self.scope is None
            else NetworkScope(self.scope)
        )
        object.__setattr__(self, "medium", medium)
        object.__setattr__(self, "scope", scope)
        if self.port is not None and not 1 <= self.port <= 65535:
            raise ValueError("endpoint port must be between 1 and 65535")

    @property
    def is_network(self) -> bool:
        return self.scheme in {"tcp", "udp", "http", "https"}

    @property
    def is_lan(self) -> bool:
        return self.scope is NetworkScope.LAN

    @property
    def is_wan(self) -> bool:
        return self.scope is NetworkScope.WAN

    def key(self) -> str:
        return f"{self.scheme}|{self.address}|{self.port or ''}|{self.scope.value}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "scheme": self.scheme,
            "address": self.address,
            "medium": self.medium.value,
            "scope": self.scope.value,
            "port": self.port,
        }


@dataclass(frozen=True, slots=True)
class TransportMessage:
    """A protocol-neutral message carrying an optional protocol envelope."""

    source: str
    destination: Endpoint
    channel: str
    payload: Mapping[str, Any]
    sent_at: datetime = field(default_factory=utc_now)
    message_id: str = field(default_factory=lambda: str(uuid4()))
    sequence: int | None = None
    idempotency_key: str | None = None
    envelope: Any | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "sent_at", require_utc(self.sent_at, "sent_at"))
        object.__setattr__(self, "payload", dict(self.payload))
        if not self.source.strip() or not self.channel.strip():
            raise ValueError("source and channel cannot be empty")
        if not self.message_id.strip():
            raise ValueError("message_id cannot be empty")
        if self.sequence is not None and self.sequence < 1:
            raise ValueError("sequence must be positive")

    @property
    def dedupe_key(self) -> str:
        return self.idempotency_key or self.message_id

    @property
    def fingerprint(self) -> str:
        return content_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        envelope = self.envelope.to_dict() if hasattr(self.envelope, "to_dict") else self.envelope
        return {
            "message_id": self.message_id,
            "source": self.source,
            "destination": {
                "scheme": self.destination.scheme,
                "address": self.destination.address,
                "medium": self.destination.medium.value,
                "scope": self.destination.scope.value,
                "port": self.destination.port,
            },
            "channel": self.channel,
            "payload": dict(self.payload),
            "sent_at": self.sent_at.isoformat(),
            "sequence": self.sequence,
            "idempotency_key": self.idempotency_key,
            "envelope": envelope,
        }


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    message_id: str
    accepted: bool
    duplicate: bool = False
    sequence: int | None = None
    latency_ms: float | None = None
    error: str | None = None
    delivered_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.delivered_at is not None:
            object.__setattr__(self, "delivered_at", require_utc(self.delivered_at, "delivered_at"))

    @property
    def status(self) -> DeliveryStatus:
        if self.duplicate:
            return DeliveryStatus.DUPLICATE
        if self.accepted:
            return DeliveryStatus.ACCEPTED
        if self.error == DeliveryStatus.OUT_OF_SEQUENCE.value:
            return DeliveryStatus.OUT_OF_SEQUENCE
        if self.error == DeliveryStatus.SEQUENCE_GAP.value:
            return DeliveryStatus.SEQUENCE_GAP
        if self.error == DeliveryStatus.IDEMPOTENCY_CONFLICT.value:
            return DeliveryStatus.IDEMPOTENCY_CONFLICT
        return DeliveryStatus.ERROR


@dataclass(frozen=True, slots=True)
class ConnectionStatus:
    endpoint: Endpoint
    state: ConnectionState
    checked_at: datetime
    latency_ms: float | None = None
    packets_sent: int = 0
    packets_received: int = 0
    packets_lost: int = 0
    last_sequence: int | None = None
    last_error: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, ConnectionState):
            raise ValueError("state must be a ConnectionState")
        object.__setattr__(self, "checked_at", require_utc(self.checked_at, "checked_at"))
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("latency_ms cannot be negative")
        if min(self.packets_sent, self.packets_received, self.packets_lost) < 0:
            raise ValueError("packet counters cannot be negative")
        if self.reason is not None and (not isinstance(self.reason, str) or not self.reason.strip()):
            raise ValueError("reason must be a non-empty string when provided")

    def to_dict(self) -> dict[str, Any]:
        return {
            "endpoint": self.endpoint.to_dict(),
            "state": self.state.value,
            "checked_at": self.checked_at.isoformat(),
            "latency_ms": self.latency_ms,
            "packets_sent": self.packets_sent,
            "packets_received": self.packets_received,
            "packets_lost": self.packets_lost,
            "last_sequence": self.last_sequence,
            "last_error": self.last_error,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ConnectionStatus":
        if not isinstance(data, Mapping):
            raise ValueError("connection status must be a mapping")
        endpoint_data = data.get("endpoint")
        if not isinstance(endpoint_data, Mapping):
            raise ValueError("connection status endpoint must be a mapping")
        return cls(
            endpoint=Endpoint(
                scheme=str(endpoint_data["scheme"]),
                address=str(endpoint_data["address"]),
                medium=str(endpoint_data["medium"]),
                scope=str(endpoint_data["scope"]),
                port=endpoint_data.get("port"),
            ),
            state=ConnectionState(str(data["state"])),
            checked_at=datetime.fromisoformat(str(data["checked_at"])),
            latency_ms=data.get("latency_ms"),
            packets_sent=int(data.get("packets_sent", 0)),
            packets_received=int(data.get("packets_received", 0)),
            packets_lost=int(data.get("packets_lost", 0)),
            last_sequence=data.get("last_sequence"),
            last_error=data.get("last_error"),
            reason=data.get("reason"),
        )

    @property
    def loss_ratio(self) -> float:
        total = self.packets_received + self.packets_lost
        return self.packets_lost / total if total else 0.0


@dataclass(frozen=True, slots=True)
class TransportPolicy:
    """Allowlist for schemes, peers, physical media and LAN/WAN scope."""

    allowed_schemes: frozenset[str] = frozenset({"memory", "unix", "tcp", "udp", "https"})
    allowed_peers: frozenset[str] = frozenset()
    allowed_media: frozenset[NetworkMedium] = frozenset({
        NetworkMedium.ETHERNET,
        NetworkMedium.WIFI,
        NetworkMedium.HOTSPOT,
        NetworkMedium.ROUTER,
        NetworkMedium.UNKNOWN,
    })
    allowed_scopes: frozenset[NetworkScope] = frozenset({NetworkScope.LOCAL, NetworkScope.LAN})
    allow_network: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_schemes", frozenset(s.lower() for s in self.allowed_schemes))
        object.__setattr__(self, "allowed_media", frozenset(NetworkMedium(m) for m in self.allowed_media))
        object.__setattr__(self, "allowed_scopes", frozenset(NetworkScope(s) for s in self.allowed_scopes))

    def validate(self, endpoint: Endpoint) -> None:
        if endpoint.scheme not in self.allowed_schemes:
            raise PermissionError(f"transport scheme not allowed: {endpoint.scheme}")
        if endpoint.is_network and not self.allow_network:
            raise PermissionError("network transport disabled by policy")
        if endpoint.medium not in self.allowed_media:
            raise PermissionError(f"network medium not allowed: {endpoint.medium.value}")
        if endpoint.scope not in self.allowed_scopes:
            raise PermissionError(f"network scope not allowed: {endpoint.scope.value}")
        if self.allowed_peers and endpoint.address not in self.allowed_peers:
            raise PermissionError(f"transport peer not allowed: {endpoint.address}")


class InMemoryTransport:
    """Deterministic local transport; no socket, DNS or peer discovery."""

    def __init__(
        self,
        policy: TransportPolicy | None = None,
        clock: Callable[[], datetime] = utc_now,
        enforce_sequence: bool = True,
    ):
        self.policy = policy or TransportPolicy(allow_network=False)
        self.clock = clock
        self.enforce_sequence = enforce_sequence
        self._messages: list[TransportMessage] = []
        self._seen: dict[tuple[str, str], str] = {}
        self._accepted_sequences: dict[tuple[str, str], int] = {}
        self._statuses: dict[str, ConnectionStatus] = {}
        self._lock = RLock()

    def _set_status(
        self,
        endpoint: Endpoint,
        state: ConnectionState,
        *,
        latency_ms: float | None = None,
        sent: int = 0,
        received: int = 0,
        lost: int = 0,
        sequence: int | None = None,
        error: str | None = None,
    ) -> ConnectionStatus:
        previous = self._statuses.get(endpoint.key())
        status = ConnectionStatus(
            endpoint=endpoint,
            state=state,
            checked_at=self.clock(),
            latency_ms=latency_ms if latency_ms is not None else (previous.latency_ms if previous else None),
            packets_sent=(previous.packets_sent if previous else 0) + sent,
            packets_received=(previous.packets_received if previous else 0) + received,
            packets_lost=(previous.packets_lost if previous else 0) + lost,
            last_sequence=sequence if sequence is not None else (previous.last_sequence if previous else None),
            last_error=error,
        )
        self._statuses[endpoint.key()] = status
        return status

    def send(self, message: TransportMessage) -> DeliveryReceipt:
        try:
            self.policy.validate(message.destination)
        except PermissionError as exc:
            with self._lock:
                self._set_status(message.destination, ConnectionState.BLOCKED, error=str(exc))
            raise

        with self._lock:
            fingerprint = message.fingerprint
            endpoint_key = message.destination.key()
            duplicate_keys = [
                (endpoint_key, key)
                for key in (message.message_id, message.dedupe_key)
                if (endpoint_key, key) in self._seen
            ]
            if duplicate_keys:
                if any(self._seen[key] != fingerprint for key in duplicate_keys):
                    self._set_status(message.destination, ConnectionState.ERROR, error=DeliveryStatus.IDEMPOTENCY_CONFLICT.value)
                    return DeliveryReceipt(
                        message.message_id,
                        accepted=False,
                        sequence=message.sequence,
                        error=DeliveryStatus.IDEMPOTENCY_CONFLICT.value,
                        delivered_at=self.clock(),
                    )
                return DeliveryReceipt(
                    message.message_id,
                    accepted=True,
                    duplicate=True,
                    sequence=message.sequence,
                    delivered_at=self.clock(),
                )

            sequence_key = (message.destination.key(), message.channel)
            last_sequence = self._accepted_sequences.get(sequence_key, 0)
            if self.enforce_sequence and message.sequence is not None:
                expected = last_sequence + 1
                if message.sequence < expected:
                    self._set_status(message.destination, ConnectionState.DEGRADED, error=DeliveryStatus.OUT_OF_SEQUENCE.value)
                    return DeliveryReceipt(
                        message.message_id,
                        accepted=False,
                        sequence=message.sequence,
                        error=DeliveryStatus.OUT_OF_SEQUENCE.value,
                        delivered_at=self.clock(),
                    )
                if message.sequence > expected:
                    self._set_status(message.destination, ConnectionState.DEGRADED, error=DeliveryStatus.SEQUENCE_GAP.value)
                    return DeliveryReceipt(
                        message.message_id,
                        accepted=False,
                        sequence=message.sequence,
                        error=DeliveryStatus.SEQUENCE_GAP.value,
                        delivered_at=self.clock(),
                    )

            delivered_at = self.clock()
            latency_ms = max(0.0, (delivered_at - message.sent_at).total_seconds() * 1000)
            self._seen[(endpoint_key, message.message_id)] = fingerprint
            self._seen[(endpoint_key, message.dedupe_key)] = fingerprint
            self._messages.append(message)
            if message.sequence is not None:
                self._accepted_sequences[sequence_key] = message.sequence
            self._set_status(
                message.destination,
                ConnectionState.CONNECTED,
                latency_ms=latency_ms,
                sent=1,
                received=1,
                sequence=message.sequence,
            )
            return DeliveryReceipt(
                message.message_id,
                accepted=True,
                sequence=message.sequence,
                latency_ms=latency_ms,
                delivered_at=delivered_at,
            )

    def mark_lost(self, endpoint: Endpoint, error: str = "delivery_lost") -> ConnectionStatus:
        with self._lock:
            return self._set_status(endpoint, ConnectionState.DEGRADED, lost=1, error=error)

    def messages(self) -> tuple[TransportMessage, ...]:
        with self._lock:
            return tuple(self._messages)

    def status(self, endpoint: Endpoint) -> ConnectionStatus:
        with self._lock:
            return self._statuses.get(endpoint.key()) or ConnectionStatus(
                endpoint=endpoint,
                state=ConnectionState.DISCONNECTED,
                checked_at=self.clock(),
            )


class JsonLineTransport:
    """Serialize one message to a caller-owned TCP/UDP/local writer.

    This is a framing adapter, not a socket implementation. The host supplies
    the writer after applying its own interface, TLS and firewall decisions.
    """

    def __init__(self, writer: Callable[[bytes], None], policy: TransportPolicy | None = None):
        self.writer = writer
        self.policy = policy or TransportPolicy()

    def send(self, message: TransportMessage) -> DeliveryReceipt:
        self.policy.validate(message.destination)
        encoded = (json.dumps(message.to_dict(), ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        self.writer(encoded)
        return DeliveryReceipt(message.message_id, accepted=True, sequence=message.sequence, delivered_at=utc_now())
