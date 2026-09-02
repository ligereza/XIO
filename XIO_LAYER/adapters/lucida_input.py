"""Small, redacted input contract for a future LUCIDA reducer."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from ..core.contracts import require_utc
from ..core.events import (
    ApplicationEvent,
    ApplicationEventLog,
    DuplicateApplicationEventError,
)
from .handoff import PrivacyPolicy


LUCIDA_INPUT_SCHEMA_VERSION = 1
LUCIDA_INPUT_CHANNEL = "lucida.input"
LUCIDA_INPUT_CONTRACT = "lucida-input-v1"
MAX_DATA_SUMMARY_FIELDS = 16
_SUMMARY_KINDS = frozenset(
    {"mapping", "null", "boolean", "integer", "number", "string", "bytes", "datetime", "sequence"}
)
_PRIVACY_STATUSES = frozenset({"redacted", "summary_only"})


class LucidaInputContractError(ValueError):
    """Raised when a LUCIDA input cannot be represented safely."""


class DuplicateLucidaInputError(LucidaInputContractError):
    """Raised when one input id is reused with different content."""


@dataclass(frozen=True, slots=True)
class LucidaInputRecord:
    """Bounded metadata exposed to a future LUCIDA reducer."""

    event_id: str
    source: str
    source_version: str
    event_type: str
    event_time: datetime
    sequence: int
    capability: str
    privacy_status: str
    data_summary: Mapping[str, Any]

    def __post_init__(self) -> None:
        for field_name in ("event_id", "source", "event_type", "capability"):
            _validate_identifier(getattr(self, field_name), field_name)
        _validate_ascii_text(self.source_version, "source_version")
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or self.sequence < 1:
            raise LucidaInputContractError("sequence must be a positive integer")
        object.__setattr__(self, "event_time", require_utc(self.event_time, "event_time"))
        if not isinstance(self.privacy_status, str) or self.privacy_status not in _PRIVACY_STATUSES:
            raise LucidaInputContractError("privacy_status is unsupported")
        summary = _validate_data_summary(self.data_summary)
        object.__setattr__(self, "data_summary", summary)

    @classmethod
    def from_application_event(
        cls,
        event: ApplicationEvent,
        *,
        source_version: str,
        capability: str,
        privacy_policy: PrivacyPolicy | None = None,
    ) -> "LucidaInputRecord":
        """Project one canonical event into bounded reducer metadata."""

        if not isinstance(event, ApplicationEvent):
            raise LucidaInputContractError("event must be an ApplicationEvent")
        policy = privacy_policy if privacy_policy is not None else PrivacyPolicy()
        if not isinstance(policy, PrivacyPolicy):
            raise LucidaInputContractError("privacy_policy must be a PrivacyPolicy")
        summary, privacy_status = _summarize_payload(event.payload, policy)
        return cls(
            event_id=event.event_id,
            source=event.source_app,
            source_version=source_version,
            event_type=event.event_type,
            event_time=event.source_timestamp,
            sequence=event.sequence,
            capability=capability,
            privacy_status=privacy_status,
            data_summary=summary,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "source": self.source,
            "source_version": self.source_version,
            "event_type": self.event_type,
            "event_time": self.event_time.isoformat(),
            "sequence": self.sequence,
            "capability": self.capability,
            "privacy_status": self.privacy_status,
            "data_summary": deepcopy(dict(self.data_summary)),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LucidaInputRecord":
        required = {
            "event_id",
            "source",
            "source_version",
            "event_type",
            "event_time",
            "sequence",
            "capability",
            "privacy_status",
            "data_summary",
        }
        if not isinstance(value, Mapping) or set(value) != required:
            raise LucidaInputContractError("lucida input fields do not match the contract")
        if not isinstance(value["event_time"], str):
            raise LucidaInputContractError("event_time must be an ISO datetime")
        try:
            event_time = datetime.fromisoformat(value["event_time"])
        except ValueError as exc:
            raise LucidaInputContractError("event_time must be an ISO datetime") from exc
        return cls(
            event_id=value["event_id"],
            source=value["source"],
            source_version=value["source_version"],
            event_type=value["event_type"],
            event_time=event_time,
            sequence=value["sequence"],
            capability=value["capability"],
            privacy_status=value["privacy_status"],
            data_summary=value["data_summary"],
        )


class LucidaInputLog:
    """Persistent input view backed by the existing ApplicationEventLog."""

    def __init__(self, path: str | Path):
        self._events = ApplicationEventLog(path)

    def append(self, record: LucidaInputRecord) -> bool:
        if not isinstance(record, LucidaInputRecord):
            raise TypeError("append accepts LucidaInputRecord only")
        try:
            return self._events.append(_to_storage_event(record))
        except DuplicateApplicationEventError as exc:
            raise DuplicateLucidaInputError(record.event_id) from exc

    def replace(self, previous_event_id: str, replacement: LucidaInputRecord) -> bool:
        """Append an explicit replacement with a new id; never mutate history."""

        _validate_identifier(previous_event_id, "previous_event_id")
        if not isinstance(replacement, LucidaInputRecord):
            raise TypeError("replacement must be a LucidaInputRecord")
        if replacement.event_id == previous_event_id:
            raise LucidaInputContractError("replacement must use a new event_id")
        previous = {record.event_id: record for record in self.replay()}.get(previous_event_id)
        if previous is None:
            raise LucidaInputContractError("previous_event_id is not present")
        if replacement.sequence <= previous.sequence:
            raise LucidaInputContractError("replacement sequence must follow the replaced input")
        try:
            return self._events.append(_to_storage_event(replacement, replaces=previous_event_id))
        except DuplicateApplicationEventError as exc:
            raise DuplicateLucidaInputError(replacement.event_id) from exc

    def replay(self) -> tuple[LucidaInputRecord, ...]:
        """Replay in sequence order, applying only explicit replacements."""

        def reducer(state: Mapping[str, Any], event: ApplicationEvent) -> Mapping[str, Any]:
            records = list(state.get("records", []))
            replacement_for = event.provenance.get("replaces")
            record = _from_storage_event(event)
            if replacement_for is not None:
                previous = next(
                    (item for item in records if item["event_id"] == replacement_for),
                    None,
                )
                if previous is None:
                    raise LucidaInputContractError("replacement target is not present")
                if record.sequence <= previous["sequence"]:
                    raise LucidaInputContractError("replacement sequence must follow the replaced input")
                records = [item for item in records if item["event_id"] != replacement_for]
            records.append(record.to_dict())
            return {"records": records}

        result = self._events.replay(reducer, {"records": []})
        return tuple(LucidaInputRecord.from_dict(item) for item in result.state["records"])


def _to_storage_event(record: LucidaInputRecord, *, replaces: str | None = None) -> ApplicationEvent:
    provenance = {
        "capability": record.capability,
        "contract": LUCIDA_INPUT_CONTRACT,
        "privacy_status": record.privacy_status,
        "source_version": record.source_version,
    }
    if replaces is not None:
        provenance["replaces"] = replaces
    return ApplicationEvent(
        event_id=record.event_id,
        schema_version=LUCIDA_INPUT_SCHEMA_VERSION,
        source_app=record.source,
        event_type=record.event_type,
        channel=LUCIDA_INPUT_CHANNEL,
        payload={"data_summary": deepcopy(dict(record.data_summary))},
        source_timestamp=record.event_time,
        received_timestamp=record.event_time,
        session_id="lucida-input",
        peer_id="xio-layer",
        sequence=record.sequence,
        provenance=provenance,
    )


def _from_storage_event(event: ApplicationEvent) -> LucidaInputRecord:
    if event.schema_version != LUCIDA_INPUT_SCHEMA_VERSION:
        raise LucidaInputContractError("storage event schema_version is unsupported")
    if event.channel != LUCIDA_INPUT_CHANNEL:
        raise LucidaInputContractError("storage event channel is not lucida.input")
    if not isinstance(event.payload, Mapping) or set(event.payload) != {"data_summary"}:
        raise LucidaInputContractError("storage event payload does not match the contract")
    required = {"capability", "contract", "privacy_status", "source_version"}
    if not isinstance(event.provenance, Mapping) or not required.issubset(event.provenance):
        raise LucidaInputContractError("storage event provenance is incomplete")
    allowed = required | {"replaces"}
    if set(event.provenance) - allowed or event.provenance["contract"] != LUCIDA_INPUT_CONTRACT:
        raise LucidaInputContractError("storage event provenance does not match the contract")
    replacement_for = event.provenance.get("replaces")
    if "replaces" in event.provenance and replacement_for is None:
        raise LucidaInputContractError("replaces must be an explicit identifier")
    if replacement_for is not None:
        _validate_identifier(replacement_for, "replaces")
    return LucidaInputRecord(
        event_id=event.event_id,
        source=event.source_app,
        source_version=event.provenance["source_version"],
        event_type=event.event_type,
        event_time=event.source_timestamp,
        sequence=event.sequence,
        capability=event.provenance["capability"],
        privacy_status=event.provenance["privacy_status"],
        data_summary=event.payload["data_summary"],
    )


def _summarize_payload(payload: Any, policy: PrivacyPolicy) -> tuple[dict[str, Any], str]:
    if not isinstance(payload, Mapping):
        kind = _value_kind(payload)
        status = "summary_only" if payload is None else "redacted"
        return {"kind": kind, "item_count": 0, "fields": [], "truncated": False}, status

    visible_keys = sorted(key for key in payload if key in policy.allowed_payload_keys)
    fields = [
        {"name": key, "type": _value_kind(payload[key])}
        for key in visible_keys[:MAX_DATA_SUMMARY_FIELDS]
    ]
    omitted = len(visible_keys) > MAX_DATA_SUMMARY_FIELDS or len(visible_keys) != len(payload)
    status = "redacted" if omitted else "summary_only"
    return {
        "kind": "mapping",
        "item_count": len(fields),
        "fields": fields,
        "truncated": omitted,
    }, status


def _validate_data_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise LucidaInputContractError("data_summary must be a mapping")
    required = {"kind", "item_count", "fields", "truncated"}
    if set(value) != required:
        raise LucidaInputContractError("data_summary fields do not match the contract")
    if not isinstance(value["kind"], str) or value["kind"] not in _SUMMARY_KINDS:
        raise LucidaInputContractError("data_summary kind is unsupported")
    if (
        isinstance(value["item_count"], bool)
        or not isinstance(value["item_count"], int)
        or not 0 <= value["item_count"] <= MAX_DATA_SUMMARY_FIELDS
    ):
        raise LucidaInputContractError("data_summary item_count is invalid")
    if not isinstance(value["fields"], list) or len(value["fields"]) > MAX_DATA_SUMMARY_FIELDS:
        raise LucidaInputContractError("data_summary fields must be a bounded list")
    names = []
    normalized_fields = []
    for field in value["fields"]:
        if not isinstance(field, Mapping) or set(field) != {"name", "type"}:
            raise LucidaInputContractError("data_summary field is invalid")
        if not isinstance(field["name"], str) or not field["name"].strip():
            raise LucidaInputContractError("data_summary field name is invalid")
        if not isinstance(field["type"], str) or field["type"] not in _SUMMARY_KINDS:
            raise LucidaInputContractError("data_summary field type is unsupported")
        names.append(field["name"])
        normalized_fields.append({"name": field["name"], "type": field["type"]})
    if names != sorted(names) or len(names) != len(set(names)):
        raise LucidaInputContractError("data_summary fields must be sorted and unique")
    if value["item_count"] != len(normalized_fields):
        raise LucidaInputContractError("data_summary item_count does not match fields")
    if not isinstance(value["truncated"], bool):
        raise LucidaInputContractError("data_summary truncated must be boolean")
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise LucidaInputContractError("data_summary must be JSON-safe") from exc
    return {
        "kind": value["kind"],
        "item_count": value["item_count"],
        "fields": normalized_fields,
        "truncated": value["truncated"],
    }


def _value_kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, bytes):
        return "bytes"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, Mapping):
        return "mapping"
    if isinstance(value, (list, tuple)):
        return "sequence"
    raise LucidaInputContractError(f"unsupported payload value: {type(value).__name__}")


def _validate_ascii_text(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip() or not value.isascii():
        raise LucidaInputContractError(f"{field_name} must be non-empty ASCII text")


def _validate_identifier(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value or not value.isascii():
        raise LucidaInputContractError(f"{field_name} must be a non-empty ASCII identifier")
    if not value[0].isalnum() or any(not (char.isalnum() or char in "._-") for char in value):
        raise LucidaInputContractError(f"{field_name} contains unsupported characters")


__all__ = [
    "DuplicateLucidaInputError",
    "LUCIDA_INPUT_CHANNEL",
    "LUCIDA_INPUT_CONTRACT",
    "LUCIDA_INPUT_SCHEMA_VERSION",
    "LucidaInputContractError",
    "LucidaInputLog",
    "LucidaInputRecord",
    "MAX_DATA_SUMMARY_FIELDS",
]
