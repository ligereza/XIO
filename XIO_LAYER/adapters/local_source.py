"""Replayable local JSONL source for caller-selected adapter handoffs."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping

from ..core.audit import AuditLedger
from ..core.contracts import content_hash, require_utc
from ..core.transport import Endpoint
from .handoff import AdapterHandoff, PrivacyPolicy, prepare_adapter_handoff
from .source_registry import AdapterSelection, SourceAdapterRegistry


class LocalEventSourceError(ValueError):
    """Raised when a local source record is invalid or cannot be replayed."""


class DuplicateLocalEventError(LocalEventSourceError):
    """Raised when one event id has conflicting local source records."""


@dataclass(frozen=True, slots=True)
class LocalEventRecord:
    """Validated local record consumed by exactly one selected adapter route."""

    event_id: str
    source_app: str
    event_type: str
    sequence: int
    source_timestamp: datetime
    received_timestamp: datetime
    payload: Any
    provenance: Mapping[str, Any]
    record_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_identifier(self.event_id, "event_id")
        _validate_identifier(self.source_app, "source_app")
        _validate_identifier(self.event_type, "event_type")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise LocalEventSourceError("sequence must be a positive integer")
        source_timestamp = require_utc(self.source_timestamp, "source_timestamp")
        received_timestamp = require_utc(self.received_timestamp, "received_timestamp")
        if not isinstance(self.provenance, Mapping):
            raise LocalEventSourceError("provenance must be a mapping")
        payload = deepcopy(self.payload)
        provenance = deepcopy(dict(self.provenance))
        _ensure_json_safe(payload, "payload")
        _ensure_json_safe(provenance, "provenance")
        object.__setattr__(self, "source_timestamp", source_timestamp)
        object.__setattr__(self, "received_timestamp", received_timestamp)
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "provenance", provenance)
        object.__setattr__(self, "record_fingerprint", content_hash(self._normalized_dict()))

    def _normalized_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "source_app": self.source_app,
            "event_type": self.event_type,
            "sequence": self.sequence,
            "source_timestamp": self.source_timestamp.isoformat(),
            "received_timestamp": self.received_timestamp.isoformat(),
            "payload": self.payload,
            "provenance": dict(self.provenance),
        }

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self._normalized_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LocalEventRecord":
        if not isinstance(value, Mapping):
            raise LocalEventSourceError("local event record must be a mapping")
        required = {
            "event_id",
            "source_app",
            "event_type",
            "sequence",
            "source_timestamp",
            "received_timestamp",
            "payload",
            "provenance",
        }
        if set(value) != required:
            missing = sorted(required - set(value))
            extra = sorted(set(value) - required)
            raise LocalEventSourceError(f"local record fields invalid; missing={missing}, extra={extra}")
        try:
            source_timestamp = datetime.fromisoformat(str(value["source_timestamp"]))
            received_timestamp = datetime.fromisoformat(str(value["received_timestamp"]))
        except (TypeError, ValueError) as exc:
            raise LocalEventSourceError("local record timestamps must be ISO datetimes") from exc
        return cls(
            event_id=str(value["event_id"]),
            source_app=str(value["source_app"]),
            event_type=str(value["event_type"]),
            sequence=value["sequence"],
            source_timestamp=source_timestamp,
            received_timestamp=received_timestamp,
            payload=value["payload"],
            provenance=value["provenance"],
        )


class LocalAdapterEventSource:
    """Read-only JSONL source with deterministic, idempotent replay."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def replay(self) -> tuple[LocalEventRecord, ...]:
        """Read unique records and order them by ingestion sequence."""

        if not self.path.exists():
            return ()
        unique: dict[str, LocalEventRecord] = {}
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = LocalEventRecord.from_dict(json.loads(line))
            except (json.JSONDecodeError, LocalEventSourceError) as exc:
                raise LocalEventSourceError(f"invalid local JSONL line {line_number}: {exc}") from exc
            existing = unique.get(record.event_id)
            if existing is not None:
                if existing.record_fingerprint != record.record_fingerprint:
                    raise DuplicateLocalEventError(record.event_id)
                continue
            unique[record.event_id] = record
        return tuple(
            sorted(
                unique.values(),
                key=lambda item: (item.sequence, item.received_timestamp, item.event_id),
            )
        )

    def prepare_handoffs(
        self,
        registry: SourceAdapterRegistry,
        selection: AdapterSelection,
        *,
        source: str,
        destination: Endpoint,
        audit: AuditLedger,
        privacy_policy: PrivacyPolicy | None = None,
    ) -> tuple[AdapterHandoff, ...]:
        """Prepare one handoff per replayed record; never deliver or execute."""

        privacy = privacy_policy or PrivacyPolicy()
        prepared = []
        for local_record in self.replay():
            if (
                local_record.source_app != selection.source_app
                or local_record.event_type != selection.event_type
            ):
                raise LocalEventSourceError(
                    "local record does not match the caller-selected adapter route"
                )
            prepared.append(
                prepare_adapter_handoff(
                    registry,
                    selection,
                    local_record.to_dict(),
                    source=source,
                    destination=destination,
                    audit=audit,
                    privacy_policy=privacy,
                    handoff_id=_replay_handoff_id(selection, local_record.event_id),
                )
            )
        return tuple(prepared)


def _ensure_json_safe(value: Any, field_name: str) -> None:
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise LocalEventSourceError(f"{field_name} must be JSON-safe") from exc


def _validate_identifier(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value or not value.isascii():
        raise LocalEventSourceError(f"{field_name} must be a non-empty ASCII identifier")
    if not value[0].isalnum() or any(not (char.isalnum() or char in "._-") for char in value):
        raise LocalEventSourceError(f"{field_name} contains unsupported characters")


def _replay_handoff_id(selection: AdapterSelection, event_id: str) -> str:
    return f"handoff-{content_hash({'selection_id': selection.selection_id, 'event_id': event_id})[:24]}"


__all__ = [
    "DuplicateLocalEventError",
    "LocalAdapterEventSource",
    "LocalEventRecord",
    "LocalEventSourceError",
]
