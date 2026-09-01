"""Bidirectional LUCIDA/MULTI bridge for canonical application events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from typing import Any, Mapping

from ..core.events import ApplicationEvent
from ..core.transport import Endpoint, TransportMessage


APPLICATION_EVENT_CHANNEL = "application-event"
APPLICATION_EVENT_ENVELOPE_TYPE = "xio.application-event"
APPLICATION_EVENT_SCHEMA_VERSION = 1

_APPLICATION_EVENT_FIELDS = frozenset(
    {
        "event_id",
        "schema_version",
        "source_app",
        "event_type",
        "channel",
        "payload",
        "source_timestamp",
        "received_timestamp",
        "session_id",
        "peer_id",
        "sequence",
        "raw_hash",
        "provenance",
    }
)
_ENVELOPE_FIELDS = frozenset({"type", "schema_version"})


class LucidaBridgeError(ValueError):
    """Raised when a LUCIDA/MULTI transport message violates the contract."""


@dataclass(frozen=True, slots=True)
class LucidaApplicationEnvelope:
    """Explicit wire envelope for the application-event channel."""

    schema_version: int = APPLICATION_EVENT_SCHEMA_VERSION
    envelope_type: str = field(init=False, default=APPLICATION_EVENT_ENVELOPE_TYPE)

    def __post_init__(self) -> None:
        if self.schema_version != APPLICATION_EVENT_SCHEMA_VERSION:
            raise LucidaBridgeError("unsupported application-event envelope schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.envelope_type,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_value(cls, value: Any) -> "LucidaApplicationEnvelope":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise LucidaBridgeError("transport envelope must be a mapping")
        if set(value) != _ENVELOPE_FIELDS:
            raise LucidaBridgeError("transport envelope fields do not match application-event schema")
        if value.get("type") != APPLICATION_EVENT_ENVELOPE_TYPE:
            raise LucidaBridgeError("transport envelope is not an application-event envelope")
        if value.get("schema_version") != APPLICATION_EVENT_SCHEMA_VERSION:
            raise LucidaBridgeError("unsupported application-event envelope schema")
        return cls(schema_version=APPLICATION_EVENT_SCHEMA_VERSION)


def application_event_to_transport(
    event: ApplicationEvent,
    *,
    source: str,
    destination: Endpoint,
    sent_at: datetime | None = None,
    message_id: str | None = None,
) -> TransportMessage:
    """Pack one application event into a protocol-neutral transport message."""

    if not isinstance(event, ApplicationEvent):
        raise LucidaBridgeError("bridge accepts ApplicationEvent only")
    return TransportMessage(
        source=source,
        destination=destination,
        channel=APPLICATION_EVENT_CHANNEL,
        payload=event.to_dict(),
        sent_at=sent_at or event.received_timestamp,
        message_id=message_id or event.event_id,
        sequence=event.sequence,
        idempotency_key=event.event_id,
        envelope=LucidaApplicationEnvelope(schema_version=event.schema_version),
    )


def transport_to_application_event(message: TransportMessage) -> ApplicationEvent:
    """Validate and unpack one application-event transport message."""

    if not isinstance(message, TransportMessage):
        raise LucidaBridgeError("bridge accepts TransportMessage only")
    if message.channel != APPLICATION_EVENT_CHANNEL:
        raise LucidaBridgeError("transport channel is not application-event")
    envelope = LucidaApplicationEnvelope.from_value(message.envelope)
    payload = _validate_event_payload(message.payload)
    try:
        event = ApplicationEvent.from_dict(payload)
    except Exception as exc:
        raise LucidaBridgeError(f"invalid application-event payload: {exc}") from exc
    if event.schema_version != envelope.schema_version:
        raise LucidaBridgeError("event and envelope schema versions do not match")
    if message.sequence != event.sequence:
        raise LucidaBridgeError("transport sequence does not match event sequence")
    if message.idempotency_key not in {None, event.event_id}:
        raise LucidaBridgeError("transport idempotency key does not match event id")
    return event


def _validate_event_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise LucidaBridgeError("application-event payload must be a mapping")
    fields = set(value)
    if fields != _APPLICATION_EVENT_FIELDS:
        missing = sorted(_APPLICATION_EVENT_FIELDS - fields)
        extra = sorted(fields - _APPLICATION_EVENT_FIELDS)
        raise LucidaBridgeError(f"application-event fields invalid; missing={missing}, extra={extra}")
    if not isinstance(value["event_id"], str) or not value["event_id"].strip():
        raise LucidaBridgeError("event_id must be a non-empty string")
    for field_name in ("source_app", "event_type", "channel", "session_id", "peer_id", "raw_hash"):
        field_value = value[field_name]
        if not isinstance(field_value, str) or not field_value.strip():
            raise LucidaBridgeError(f"{field_name} must be a non-empty string")
    if isinstance(value["schema_version"], bool) or not isinstance(value["schema_version"], int):
        raise LucidaBridgeError("schema_version must be an integer")
    if isinstance(value["sequence"], bool) or not isinstance(value["sequence"], int):
        raise LucidaBridgeError("sequence must be an integer")
    if not isinstance(value["provenance"], Mapping):
        raise LucidaBridgeError("provenance must be a mapping")
    try:
        json.dumps(dict(value), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise LucidaBridgeError(f"application-event payload is not JSON-safe: {exc}") from exc
    return dict(value)


__all__ = [
    "APPLICATION_EVENT_CHANNEL",
    "APPLICATION_EVENT_ENVELOPE_TYPE",
    "APPLICATION_EVENT_SCHEMA_VERSION",
    "LucidaApplicationEnvelope",
    "LucidaBridgeError",
    "application_event_to_transport",
    "transport_to_application_event",
]
