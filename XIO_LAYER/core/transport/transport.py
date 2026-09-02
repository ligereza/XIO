"""Offline-first transport contracts and in-memory delivery.

TRANSPORT moves envelopes. It does not collect signals, analyse them, or decide
actions. Network writers are injected by a host; this package never opens a
socket or discovers peers on its own.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
import math
from threading import RLock
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

from ..contracts import content_hash, ensure_json_safe, require_utc, utc_now


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
        if not isinstance(self.scheme, str) or not isinstance(self.address, str):
            raise ValueError("endpoint scheme and address must be strings")
        scheme = self.scheme.strip().lower()
        if not scheme or not self.address.strip():
            raise ValueError("endpoint scheme and address cannot be empty")
        object.__setattr__(self, "scheme", scheme)
        if self.medium is not None and not isinstance(self.medium, (NetworkMedium, str)):
            raise ValueError("endpoint medium must be a string")
        if self.scope is not None and not isinstance(self.scope, (NetworkScope, str)):
            raise ValueError("endpoint scope must be a string")
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
        if self.port is not None and (
            isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535
        ):
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
        if not isinstance(self.destination, Endpoint):
            raise ValueError("destination must be an Endpoint")
        if not isinstance(self.source, str) or not isinstance(self.channel, str):
            raise ValueError("source and channel must be strings")
        if not isinstance(self.payload, Mapping):
            raise ValueError("payload must be a mapping")
        if not isinstance(self.message_id, str):
            raise ValueError("message_id must be a string")
        if self.idempotency_key is not None and not isinstance(self.idempotency_key, str):
            raise ValueError("idempotency_key must be a string or null")
        object.__setattr__(self, "sent_at", require_utc(self.sent_at, "sent_at"))
        payload = deepcopy(dict(self.payload))
        _ensure_json_safe(payload, "payload")
        if self.envelope is not None:
            envelope = self.envelope.to_dict() if hasattr(self.envelope, "to_dict") else self.envelope
            _ensure_json_safe(envelope, "envelope")
        object.__setattr__(self, "payload", payload)
        if not self.source.strip() or not self.channel.strip():
            raise ValueError("source and channel cannot be empty")
        if not self.message_id.strip():
            raise ValueError("message_id cannot be empty")
        if self.sequence is not None and (
            isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1
        ):
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

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TransportMessage":
        """Restore a strict transport wire record without sending it."""

        if not isinstance(value, Mapping):
            raise ValueError("transport message must be a mapping")
        required = {
            "message_id",
            "source",
            "destination",
            "channel",
            "payload",
            "sent_at",
            "sequence",
            "idempotency_key",
            "envelope",
        }
        if set(value) != required or not isinstance(value["destination"], Mapping):
            raise ValueError("transport message fields do not match the contract")
        for field_name in ("message_id", "source", "channel"):
            _require_transport_text(value[field_name], field_name)
        if value["sequence"] is not None and (
            isinstance(value["sequence"], bool)
            or not isinstance(value["sequence"], int)
            or value["sequence"] < 1
        ):
            raise ValueError("transport message sequence is invalid")
        if value["idempotency_key"] is not None:
            _require_transport_text(value["idempotency_key"], "idempotency_key")
        if not isinstance(value["payload"], Mapping):
            raise ValueError("transport message payload must be a mapping")
        destination = value["destination"]
        destination_required = {"scheme", "address", "medium", "scope", "port"}
        if set(destination) != destination_required:
            raise ValueError("transport destination fields do not match the contract")
        for field_name in ("scheme", "address", "medium", "scope"):
            _require_transport_text(destination[field_name], f"destination.{field_name}")
        if destination["port"] is not None and (
            isinstance(destination["port"], bool)
            or not isinstance(destination["port"], int)
            or not 1 <= destination["port"] <= 65535
        ):
            raise ValueError("transport destination port is invalid")
        try:
            sent_at = datetime.fromisoformat(str(value["sent_at"]))
        except (TypeError, ValueError) as exc:
            raise ValueError("transport sent_at must be an ISO datetime") from exc
        return cls(
            message_id=value["message_id"],
            source=value["source"],
            destination=Endpoint(
                scheme=destination["scheme"],
                address=destination["address"],
                medium=destination["medium"],
                scope=destination["scope"],
                port=destination["port"],
            ),
            channel=value["channel"],
            payload=value["payload"],
            sent_at=sent_at,
            sequence=value["sequence"],
            idempotency_key=value["idempotency_key"],
            envelope=value["envelope"],
        )


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
        _require_transport_text(self.message_id, "message_id")
        if not isinstance(self.accepted, bool):
            raise ValueError("accepted must be a boolean")
        if not isinstance(self.duplicate, bool):
            raise ValueError("duplicate must be a boolean")
        if self.sequence is not None and (
            isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1
        ):
            raise ValueError("sequence must be a positive integer or null")
        if self.latency_ms is not None and (
            isinstance(self.latency_ms, bool)
            or not isinstance(self.latency_ms, (int, float))
            or not math.isfinite(self.latency_ms)
            or self.latency_ms < 0
        ):
            raise ValueError("latency_ms must be a finite non-negative number or null")
        if self.error is not None and not isinstance(self.error, str):
            raise ValueError("error must be a string or null")
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


def _require_transport_text(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_string_collection(value: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, Mapping)):
        raise ValueError(f"{field_name} must be a collection of strings")
    try:
        values = tuple(value)
    except TypeError as exc:
        raise ValueError(f"{field_name} must be a collection of strings") from exc
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ValueError(f"{field_name} must contain non-empty strings")
    return values


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
        if not isinstance(self.endpoint, Endpoint):
            raise ValueError("endpoint must be an Endpoint")
        if not isinstance(self.state, ConnectionState):
            raise ValueError("state must be a ConnectionState")
        object.__setattr__(self, "checked_at", require_utc(self.checked_at, "checked_at"))
        if self.latency_ms is not None and (
            isinstance(self.latency_ms, bool)
            or not isinstance(self.latency_ms, (int, float))
            or not math.isfinite(self.latency_ms)
            or self.latency_ms < 0
        ):
            raise ValueError("latency_ms cannot be negative")
        for field_name in ("packets_sent", "packets_received", "packets_lost"):
            counter = getattr(self, field_name)
            if isinstance(counter, bool) or not isinstance(counter, int) or counter < 0:
                raise ValueError("packet counters must be non-negative integers")
        if self.last_sequence is not None and (
            isinstance(self.last_sequence, bool)
            or not isinstance(self.last_sequence, int)
            or self.last_sequence < 1
        ):
            raise ValueError("last_sequence must be a positive integer or null")
        if self.last_error is not None and not isinstance(self.last_error, str):
            raise ValueError("last_error must be a string or null")
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
        required = {
            "endpoint",
            "state",
            "checked_at",
            "latency_ms",
            "packets_sent",
            "packets_received",
            "packets_lost",
            "last_sequence",
            "last_error",
            "reason",
        }
        if set(data) != required:
            raise ValueError("connection status fields do not match the contract")
        endpoint_data = data["endpoint"]
        if not isinstance(endpoint_data, Mapping):
            raise ValueError("connection status endpoint must be a mapping")
        if set(endpoint_data) != {"scheme", "address", "medium", "scope", "port"}:
            raise ValueError("connection status endpoint fields do not match the contract")
        for field_name in ("scheme", "address", "medium", "scope"):
            if not isinstance(endpoint_data[field_name], str) or not endpoint_data[field_name].strip():
                raise ValueError(f"connection status endpoint {field_name} must be a non-empty string")
        port = endpoint_data["port"]
        if port is not None and (isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535):
            raise ValueError("connection status endpoint port is invalid")
        if not isinstance(data["state"], str):
            raise ValueError("connection status state must be a string")
        if not isinstance(data["checked_at"], str):
            raise ValueError("connection status checked_at must be an ISO datetime")
        latency_ms = data["latency_ms"]
        if latency_ms is not None and (
            isinstance(latency_ms, bool)
            or not isinstance(latency_ms, (int, float))
            or not math.isfinite(latency_ms)
            or latency_ms < 0
        ):
            raise ValueError("connection status latency_ms is invalid")
        for field_name in ("packets_sent", "packets_received", "packets_lost"):
            counter = data[field_name]
            if isinstance(counter, bool) or not isinstance(counter, int) or counter < 0:
                raise ValueError(f"connection status {field_name} is invalid")
        last_sequence = data["last_sequence"]
        if last_sequence is not None and (
            isinstance(last_sequence, bool) or not isinstance(last_sequence, int) or last_sequence < 1
        ):
            raise ValueError("connection status last_sequence is invalid")
        for field_name in ("last_error", "reason"):
            if data[field_name] is not None and not isinstance(data[field_name], str):
                raise ValueError(f"connection status {field_name} must be a string or null")
        return cls(
            endpoint=Endpoint(
                scheme=endpoint_data["scheme"],
                address=endpoint_data["address"],
                medium=endpoint_data["medium"],
                scope=endpoint_data["scope"],
                port=port,
            ),
            state=ConnectionState(data["state"]),
            checked_at=datetime.fromisoformat(data["checked_at"]),
            latency_ms=latency_ms,
            packets_sent=data["packets_sent"],
            packets_received=data["packets_received"],
            packets_lost=data["packets_lost"],
            last_sequence=last_sequence,
            last_error=data["last_error"],
            reason=data["reason"],
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
        if not isinstance(self.allow_network, bool):
            raise ValueError("allow_network must be a boolean")
        schemes = _require_string_collection(self.allowed_schemes, "allowed_schemes")
        peers = _require_string_collection(self.allowed_peers, "allowed_peers")
        media = _require_string_collection(self.allowed_media, "allowed_media")
        scopes = _require_string_collection(self.allowed_scopes, "allowed_scopes")
        object.__setattr__(self, "allowed_schemes", frozenset(s.lower() for s in schemes))
        object.__setattr__(self, "allowed_peers", frozenset(peers))
        object.__setattr__(self, "allowed_media", frozenset(NetworkMedium(m) for m in media))
        object.__setattr__(self, "allowed_scopes", frozenset(NetworkScope(s) for s in scopes))

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
        encoded = (
            json.dumps(message.to_dict(), ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
        ).encode("utf-8")
        self.writer(encoded)
        return DeliveryReceipt(message.message_id, accepted=True, sequence=message.sequence, delivered_at=utc_now())


def _ensure_json_safe(value: Any, field_name: str) -> None:
    try:
        ensure_json_safe(value, field_name)
    except ValueError as exc:
        raise ValueError(f"transport {field_name} must be JSON-safe") from exc
