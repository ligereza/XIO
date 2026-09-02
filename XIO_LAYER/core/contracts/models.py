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

    copied = deepcopy(dict(value))
    try:
        json.dumps(copied, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("mapping must be JSON-safe") from exc
    return copied


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
        for field_name in ("stream_id", "kind", "source", "event_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if not isinstance(self.schema_version, int) or isinstance(self.schema_version, bool) or self.schema_version < 1:
            raise ValueError("schema_version must be positive")
        if not isinstance(self.payload, Mapping):
            raise ValueError("payload must be a mapping")
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
        required = {
            "stream_id",
            "kind",
            "source",
            "occurred_at",
            "received_at",
            "payload",
            "event_id",
            "schema_version",
        }
        if not isinstance(data, Mapping) or set(data) != required:
            raise ValueError("event fields do not match the contract")
        for field_name in ("stream_id", "kind", "source", "event_id"):
            if not isinstance(data[field_name], str):
                raise ValueError(f"event {field_name} must be a string")
        for field_name in ("occurred_at", "received_at"):
            if not isinstance(data[field_name], str):
                raise ValueError(f"event {field_name} must be an ISO datetime")
        if not isinstance(data["schema_version"], int) or isinstance(data["schema_version"], bool):
            raise ValueError("event schema_version must be an integer")
        if not isinstance(data["payload"], Mapping):
            raise ValueError("event payload must be a mapping")
        return cls(
            stream_id=data["stream_id"],
            kind=data["kind"],
            source=data["source"],
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            received_at=datetime.fromisoformat(data["received_at"]),
            payload=data["payload"],
            event_id=data["event_id"],
            schema_version=data["schema_version"],
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
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or self.sequence < 1:
            raise ValueError("sequence must be positive")
        if not isinstance(self.event, Event):
            raise ValueError("event must be an Event")

    def to_dict(self) -> dict[str, Any]:
        return {"sequence": self.sequence, "event": self.event.to_dict()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EventRecord":
        if not isinstance(data, Mapping) or set(data) != {"sequence", "event"}:
            raise ValueError("event record fields do not match the contract")
        if not isinstance(data["sequence"], int) or isinstance(data["sequence"], bool):
            raise ValueError("event record sequence must be an integer")
        if not isinstance(data["event"], Mapping):
            raise ValueError("event record event must be a mapping")
        return cls(sequence=data["sequence"], event=Event.from_dict(data["event"]))


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
        if not isinstance(self.stream_id, str) or not self.stream_id.strip():
            raise ValueError("stream_id must be a non-empty string")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 0:
            raise ValueError("version cannot be negative")
        if not isinstance(self.state, Mapping):
            raise ValueError("state must be a mapping")
        if self.source_event_id is not None and not isinstance(self.source_event_id, str):
            raise ValueError("source_event_id must be a string or null")
        if not isinstance(self.snapshot_id, str) or not self.snapshot_id.strip():
            raise ValueError("snapshot_id must be a non-empty string")
        if not isinstance(self.schema_version, int) or isinstance(self.schema_version, bool) or self.schema_version < 1:
            raise ValueError("schema_version must be positive")
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
        for field_name in ("stream_id", "action_type", "reason", "proposal_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if not isinstance(self.parameters, Mapping):
            raise ValueError("parameters must be a mapping")
        object.__setattr__(self, "created_at", require_utc(self.created_at, "created_at"))
        object.__setattr__(self, "parameters", _json_copy(self.parameters))
        if isinstance(self.source_event_ids, (str, bytes, Mapping)):
            raise ValueError("source_event_ids must be a collection of strings")
        try:
            source_event_ids = tuple(self.source_event_ids)
        except TypeError as exc:
            raise ValueError("source_event_ids must be a collection of strings") from exc
        if any(not isinstance(event_id, str) or not event_id.strip() for event_id in source_event_ids):
            raise ValueError("source_event_ids must contain non-empty strings")
        object.__setattr__(self, "source_event_ids", source_event_ids)


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
        for field_name in ("proposal_id", "action_type", "actor_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if not isinstance(self.parameters, Mapping):
            raise ValueError("parameters must be a mapping")
        object.__setattr__(self, "requested_at", require_utc(self.requested_at, "requested_at"))
        object.__setattr__(self, "parameters", _json_copy(self.parameters))
        if not isinstance(self.explicitly_confirmed, bool):
            raise ValueError("explicitly_confirmed must be a boolean")


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
        if not isinstance(self.action_id, str) or not self.action_id.strip():
            raise ValueError("action_id must be a non-empty string")
        if not isinstance(self.status, str) or self.status not in {"succeeded", "failed", "denied"}:
            raise ValueError("status must be succeeded, failed or denied")
        if not isinstance(self.output, Mapping):
            raise ValueError("output must be a mapping")
        if self.error is not None and not isinstance(self.error, str):
            raise ValueError("error must be a string or null")
        object.__setattr__(self, "started_at", require_utc(self.started_at, "started_at"))
        object.__setattr__(self, "finished_at", require_utc(self.finished_at, "finished_at"))
        object.__setattr__(self, "output", _json_copy(self.output))
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
        for field_name in (
            "audit_id",
            "event_type",
            "subject_id",
            "outcome",
            "previous_hash",
            "entry_hash",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if self.actor_id is not None and not isinstance(self.actor_id, str):
            raise ValueError("actor_id must be a string or null")
        object.__setattr__(self, "recorded_at", require_utc(self.recorded_at, "recorded_at"))
        object.__setattr__(self, "details", _json_copy(self.details))
        if self.entry_hash != content_hash(self.unsigned_dict()):
            raise ValueError("entry_hash does not match audit entry")

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

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AuditEntry":
        if not isinstance(data, Mapping):
            raise ValueError("audit entry must be a mapping")
        required = {
            "audit_id",
            "recorded_at",
            "event_type",
            "subject_id",
            "actor_id",
            "outcome",
            "details",
            "previous_hash",
            "entry_hash",
        }
        if set(data) != required:
            raise ValueError("audit entry fields do not match the contract")
        for field_name in ("audit_id", "recorded_at", "event_type", "subject_id", "outcome", "previous_hash", "entry_hash"):
            if not isinstance(data[field_name], str) or not data[field_name].strip():
                raise ValueError(f"audit entry {field_name} must be a non-empty string")
        if data["actor_id"] is not None and not isinstance(data["actor_id"], str):
            raise ValueError("audit entry actor_id must be a string or null")
        details = data["details"]
        if not isinstance(details, Mapping):
            raise ValueError("audit entry details must be a mapping")
        return cls(
            audit_id=data["audit_id"],
            recorded_at=datetime.fromisoformat(data["recorded_at"]),
            event_type=data["event_type"],
            subject_id=data["subject_id"],
            actor_id=data["actor_id"],
            outcome=data["outcome"],
            details=details,
            previous_hash=data["previous_hash"],
            entry_hash=data["entry_hash"],
        )


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
        if not isinstance(self.stream_id, str) or not self.stream_id.strip():
            raise ValueError("stream_id must be a non-empty string")
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or self.sequence < 0:
            raise ValueError("sequence cannot be negative")
        if not isinstance(self.state, Mapping):
            raise ValueError("state must be a mapping")
        if self.source_event_id is not None and not isinstance(self.source_event_id, str):
            raise ValueError("source_event_id must be a string or null")
        if not isinstance(self.checkpoint_id, str) or not self.checkpoint_id.strip():
            raise ValueError("checkpoint_id must be a non-empty string")
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
        required = {
            "stream_id",
            "sequence",
            "state",
            "source_event_id",
            "captured_at",
            "checkpoint_id",
            "state_hash",
        }
        if not isinstance(data, Mapping) or set(data) != required:
            raise ValueError("checkpoint fields do not match the contract")
        if not isinstance(data["stream_id"], str):
            raise ValueError("checkpoint stream_id must be a string")
        if not isinstance(data["sequence"], int) or isinstance(data["sequence"], bool):
            raise ValueError("checkpoint sequence must be an integer")
        if not isinstance(data["state"], Mapping):
            raise ValueError("checkpoint state must be a mapping")
        if data["source_event_id"] is not None and not isinstance(data["source_event_id"], str):
            raise ValueError("checkpoint source_event_id must be a string or null")
        if not isinstance(data["captured_at"], str):
            raise ValueError("checkpoint captured_at must be a string")
        if not isinstance(data["checkpoint_id"], str):
            raise ValueError("checkpoint checkpoint_id must be a string")
        if not isinstance(data["state_hash"], str):
            raise ValueError("checkpoint state_hash must be a string")
        checkpoint = cls(
            stream_id=data["stream_id"],
            sequence=data["sequence"],
            state=data["state"],
            source_event_id=data.get("source_event_id"),
            captured_at=datetime.fromisoformat(data["captured_at"]),
            checkpoint_id=data["checkpoint_id"],
        )
        if data["state_hash"] != checkpoint.state_hash:
            raise ValueError("checkpoint state hash mismatch")
        return checkpoint
