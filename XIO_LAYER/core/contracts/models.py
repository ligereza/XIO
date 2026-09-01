"""Stable data contracts for observation, proposal and explicit execution.

The core deliberately keeps events and proposals separate from actions. An
event can be replayed and a proposal can be displayed, but neither one can
execute anything by itself.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping
from uuid import uuid4


class TimestampError(ValueError):
    """Raised when a contract receives a naive or invalid timestamp."""


def utc_now() -> datetime:
    """Return an aware UTC timestamp suitable for a contract."""

    return datetime.now(timezone.utc)


def require_utc(value: datetime, field_name: str) -> datetime:
    """Normalize an aware datetime to UTC; reject ambiguous local time."""

    if not isinstance(value, datetime):
        raise TimestampError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise TimestampError(f"{field_name} must include a timezone")
    return value.astimezone(timezone.utc)


def _json_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a JSON-like mapping so callers cannot mutate a contract in place."""

    return deepcopy(dict(value))


def canonical_json(value: Any) -> str:
    """Serialize contract data deterministically for hashes and idempotency."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Event:
    """An observation entering XIO Layer.

    ``occurred_at`` is the source/device time and ``received_at`` is the XIO Layer
    ingestion time. Source clocks may be wrong or out of order; ingestion
    sequence, assigned by :class:`EventLog`, is the replay order.
    """

    stream_id: str
    kind: str
    source: str
    occurred_at: datetime
    received_at: datetime
    payload: Mapping[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.stream_id.strip():
            raise ValueError("stream_id cannot be empty")
        if not self.kind.strip():
            raise ValueError("kind cannot be empty")
        if not self.source.strip():
            raise ValueError("source cannot be empty")
        if not self.event_id.strip():
            raise ValueError("event_id cannot be empty")
        if self.schema_version < 1:
            raise ValueError("schema_version must be positive")
        object.__setattr__(self, "occurred_at", require_utc(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "received_at", require_utc(self.received_at, "received_at"))
        object.__setattr__(self, "payload", _json_copy(self.payload))

    @property
    def source_clock_is_ahead(self) -> bool:
        """Whether source time is later than ingestion time.

        This is recorded as an observation, not rejected. Device clocks and
        network delay make this a normal condition for an adapter.
        """

        return self.occurred_at > self.received_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "stream_id": self.stream_id,
            "kind": self.kind,
            "source": self.source,
            "occurred_at": self.occurred_at.isoformat(),
            "received_at": self.received_at.isoformat(),
            "payload": deepcopy(dict(self.payload)),
            "event_id": self.event_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Event":
        return cls(
            stream_id=str(data["stream_id"]),
            kind=str(data["kind"]),
            source=str(data["source"]),
            occurred_at=datetime.fromisoformat(str(data["occurred_at"])),
            received_at=datetime.fromisoformat(str(data["received_at"])),
            payload=data.get("payload", {}),
            event_id=str(data["event_id"]),
            schema_version=int(data.get("schema_version", 1)),
        )

    @property
    def fingerprint(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True, slots=True)
class EventRecord:
    """An event with a monotonic ingestion sequence for deterministic replay."""

    sequence: int
    event: Event

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("sequence must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {"sequence": self.sequence, "event": self.event.to_dict()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EventRecord":
        return cls(sequence=int(data["sequence"]), event=Event.from_dict(data["event"]))


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Deterministic state materialized from events."""

    stream_id: str
    version: int
    state: Mapping[str, Any]
    captured_at: datetime
    source_event_id: str | None = None
    snapshot_id: str = field(default_factory=lambda: str(uuid4()))
    schema_version: int = 1
    state_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.stream_id.strip():
            raise ValueError("stream_id cannot be empty")
        if self.version < 0:
            raise ValueError("version cannot be negative")
        object.__setattr__(self, "captured_at", require_utc(self.captured_at, "captured_at"))
        state = _json_copy(self.state)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "state_hash", content_hash(state))

    def to_dict(self) -> dict[str, Any]:
        return {
            "stream_id": self.stream_id,
            "version": self.version,
            "state": deepcopy(dict(self.state)),
            "captured_at": self.captured_at.isoformat(),
            "source_event_id": self.source_event_id,
            "snapshot_id": self.snapshot_id,
            "schema_version": self.schema_version,
            "state_hash": self.state_hash,
        }


@dataclass(frozen=True, slots=True)
class Proposal:
    """A human- or policy-readable suggestion with no execution authority."""

    stream_id: str
    action_type: str
    parameters: Mapping[str, Any]
    created_at: datetime
    reason: str
    source_event_ids: tuple[str, ...] = ()
    proposal_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", require_utc(self.created_at, "created_at"))
        object.__setattr__(self, "parameters", _json_copy(self.parameters))
        object.__setattr__(self, "source_event_ids", tuple(self.source_event_ids))
        if not self.action_type.strip():
            raise ValueError("action_type cannot be empty")
        if not self.reason.strip():
            raise ValueError("reason cannot be empty")


@dataclass(frozen=True, slots=True)
class ExplicitAction:
    """An action explicitly confirmed by an actor.

    This contract cannot be created implicitly by replay. ``explicitly_confirmed``
    must be true and the current permission registry is checked at execution.
    """

    proposal_id: str
    action_type: str
    parameters: Mapping[str, Any]
    actor_id: str
    requested_at: datetime
    explicitly_confirmed: bool
    action_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        object.__setattr__(self, "requested_at", require_utc(self.requested_at, "requested_at"))
        object.__setattr__(self, "parameters", _json_copy(self.parameters))
        if not self.proposal_id.strip():
            raise ValueError("proposal_id cannot be empty")
        if not self.actor_id.strip():
            raise ValueError("actor_id cannot be empty")
        if not self.action_type.strip():
            raise ValueError("action_type cannot be empty")


@dataclass(frozen=True, slots=True)
class ActionResult:
    """Outcome of an explicit action, including denied actions."""

    action_id: str
    status: str
    started_at: datetime
    finished_at: datetime
    output: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "started_at", require_utc(self.started_at, "started_at"))
        object.__setattr__(self, "finished_at", require_utc(self.finished_at, "finished_at"))
        object.__setattr__(self, "output", _json_copy(self.output))
        if self.status not in {"succeeded", "failed", "denied"}:
            raise ValueError("status must be succeeded, failed or denied")
        if self.finished_at < self.started_at:
            raise TimestampError("finished_at cannot precede started_at")


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """Append-only, hash-chained record of an important decision or result."""

    audit_id: str
    recorded_at: datetime
    event_type: str
    subject_id: str
    actor_id: str | None
    outcome: str
    details: Mapping[str, Any]
    previous_hash: str
    entry_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "recorded_at", require_utc(self.recorded_at, "recorded_at"))
        object.__setattr__(self, "details", _json_copy(self.details))

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "recorded_at": self.recorded_at.isoformat(),
            "event_type": self.event_type,
            "subject_id": self.subject_id,
            "actor_id": self.actor_id,
            "outcome": self.outcome,
            "details": deepcopy(dict(self.details)),
            "previous_hash": self.previous_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        data = self.unsigned_dict()
        data["entry_hash"] = self.entry_hash
        return data


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """Persisted snapshot marker used to resume replay after interruption."""

    stream_id: str
    sequence: int
    state: Mapping[str, Any]
    source_event_id: str | None
    captured_at: datetime
    checkpoint_id: str = field(default_factory=lambda: str(uuid4()))
    state_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("sequence cannot be negative")
        object.__setattr__(self, "captured_at", require_utc(self.captured_at, "captured_at"))
        state = _json_copy(self.state)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "state_hash", content_hash(state))

    @classmethod
    def from_snapshot(cls, snapshot: Snapshot) -> "Checkpoint":
        return cls(
            stream_id=snapshot.stream_id,
            sequence=snapshot.version,
            state=snapshot.state,
            source_event_id=snapshot.source_event_id,
            captured_at=snapshot.captured_at,
            checkpoint_id=snapshot.snapshot_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "stream_id": self.stream_id,
            "sequence": self.sequence,
            "state": deepcopy(dict(self.state)),
            "source_event_id": self.source_event_id,
            "captured_at": self.captured_at.isoformat(),
            "checkpoint_id": self.checkpoint_id,
            "state_hash": self.state_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Checkpoint":
        checkpoint = cls(
            stream_id=str(data["stream_id"]),
            sequence=int(data["sequence"]),
            state=data["state"],
            source_event_id=data.get("source_event_id"),
            captured_at=datetime.fromisoformat(str(data["captured_at"])),
            checkpoint_id=str(data["checkpoint_id"]),
        )
        expected = str(data.get("state_hash", ""))
        if expected and expected != checkpoint.state_hash:
            raise ValueError("checkpoint state hash mismatch")
        return checkpoint
