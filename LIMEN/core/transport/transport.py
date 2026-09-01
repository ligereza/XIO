"""Minimal transport boundary with explicit peer and scheme policy.

The core does not open sockets or start a network listener. A host can attach a
local queue, Unix socket or network sender through this boundary. This keeps
transport separate from decisions and from device-specific execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from threading import RLock
from typing import Any, Callable, Mapping
from uuid import uuid4

from ..contracts import require_utc, utc_now


@dataclass(frozen=True, slots=True)
class Endpoint:
    scheme: str
    address: str

    @property
    def is_network(self) -> bool:
        return self.scheme in {"tcp", "udp", "http", "https"}


@dataclass(frozen=True, slots=True)
class TransportMessage:
    source: str
    destination: Endpoint
    channel: str
    payload: Mapping[str, Any]
    sent_at: datetime = field(default_factory=utc_now)
    message_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        object.__setattr__(self, "sent_at", require_utc(self.sent_at, "sent_at"))
        object.__setattr__(self, "payload", dict(self.payload))
        if not self.source.strip() or not self.channel.strip():
            raise ValueError("source and channel cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "source": self.source,
            "destination": {
                "scheme": self.destination.scheme,
                "address": self.destination.address,
            },
            "channel": self.channel,
            "payload": dict(self.payload),
            "sent_at": self.sent_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    message_id: str
    accepted: bool
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class TransportPolicy:
    """Allowlist for a transport host, evaluated before delivery."""

    allowed_schemes: frozenset[str] = frozenset({"memory", "unix", "tcp", "https"})
    allowed_peers: frozenset[str] = frozenset()
    allow_network: bool = True

    def validate(self, endpoint: Endpoint) -> None:
        if endpoint.scheme not in self.allowed_schemes:
            raise PermissionError(f"transport scheme not allowed: {endpoint.scheme}")
        if endpoint.is_network and not self.allow_network:
            raise PermissionError("network transport disabled by policy")
        if self.allowed_peers and endpoint.address not in self.allowed_peers:
            raise PermissionError(f"transport peer not allowed: {endpoint.address}")


class InMemoryTransport:
    """Deterministic local transport useful for tests and local orchestration."""

    def __init__(self, policy: TransportPolicy | None = None):
        self.policy = policy or TransportPolicy(allow_network=False)
        self._messages: list[TransportMessage] = []
        self._seen: set[str] = set()
        self._lock = RLock()

    def send(self, message: TransportMessage) -> DeliveryReceipt:
        self.policy.validate(message.destination)
        with self._lock:
            if message.message_id in self._seen:
                return DeliveryReceipt(message.message_id, accepted=True, duplicate=True)
            self._seen.add(message.message_id)
            self._messages.append(message)
            return DeliveryReceipt(message.message_id, accepted=True)

    def messages(self) -> tuple[TransportMessage, ...]:
        with self._lock:
            return tuple(self._messages)


class JsonLineTransport:
    """Adapt the contract to a caller-owned local or network writer.

    The writer is injected by the host, so LIMEN never decides which sockets,
    credentials or interfaces are used.
    """

    def __init__(self, writer: Callable[[bytes], None], policy: TransportPolicy | None = None):
        self.writer = writer
        self.policy = policy or TransportPolicy()

    def send(self, message: TransportMessage) -> DeliveryReceipt:
        self.policy.validate(message.destination)
        encoded = (json.dumps(message.to_dict(), ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        self.writer(encoded)
        return DeliveryReceipt(message.message_id, accepted=True)
