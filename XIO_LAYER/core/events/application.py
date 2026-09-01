"""Canonical application event contract with reversible JSON encoding."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import base64
from typing import Any, Mapping
from uuid import uuid4

from ..contracts import content_hash, require_utc, utc_now


class ApplicationEventContractError(ValueError):
    """Raised when an application event cannot be represented safely."""


def encode_value(value: Any) -> Any:
    """Encode JSON values and bytes without changing their information."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return {
            "__xio_type__": "bytes",
            "base64": base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, datetime):
        return {"__xio_type__": "datetime", "value": require_utc(value, "payload datetime").isoformat()}
    if isinstance(value, Mapping):
        encoded = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ApplicationEventContractError("payload mapping keys must be strings")
            encoded[key] = encode_value(item)
        return encoded
    if isinstance(value, (list, tuple)):
        return [encode_value(item) for item in value]
    raise ApplicationEventContractError(f"unsupported payload value: {type(value).__name__}")


def decode_value(value: Any) -> Any:
    if isinstance(value, list):
        return [decode_value(item) for item in value]
    if isinstance(value, dict):
        marker = value.get("__xio_type__")
        if marker == "bytes":
            return base64.b64decode(value["base64"], validate=True)
        if marker == "datetime":
            return datetime.fromisoformat(value["value"])
        return {key: decode_value(item) for key, item in value.items()}
    return value


class ApplicationEvent:
    """App-independent event envelope for signals from any protocol."""

    def __init__(
        self,
        *,
        source_app: str,
        event_type: str,
        channel: str,
        payload: Any,
        source_timestamp: datetime,
        received_timestamp: datetime,
        session_id: str,
        peer_id: str,
        sequence: int,
        provenance: Mapping[str, Any],
        raw_hash: str | None = None,
        event_id: str | None = None,
        schema_version: int = 1,
    ) -> None:
        self.source_app = self._required(source_app, "source_app")
        self.event_type = self._required(event_type, "event_type")
        self.channel = self._required(channel, "channel")
        self.session_id = self._required(session_id, "session_id")
        self.peer_id = self._required(peer_id, "peer_id")
        if sequence < 1:
            raise ApplicationEventContractError("sequence must be positive")
        if schema_version < 1:
            raise ApplicationEventContractError("schema_version must be positive")
        self.sequence = sequence
        self.schema_version = schema_version
        self.source_timestamp = require_utc(source_timestamp, "source_timestamp")
        self.received_timestamp = require_utc(received_timestamp, "received_timestamp")
        self.payload = deepcopy(payload)
        self.provenance = deepcopy(dict(provenance))
        encoded_payload = encode_value(self.payload)
        computed_hash = content_hash(encoded_payload)
        if raw_hash is not None and raw_hash != computed_hash:
            raise ApplicationEventContractError("raw_hash does not match payload")
        self.raw_hash = computed_hash
        self.event_id = self._required(event_id or str(uuid4()), "event_id")

    @staticmethod
    def _required(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ApplicationEventContractError(f"{field_name} cannot be empty")
        return value

    @property
    def source_clock_is_ahead(self) -> bool:
        return self.source_timestamp > self.received_timestamp

    @property
    def fingerprint(self) -> str:
        return content_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "schema_version": self.schema_version,
            "source_app": self.source_app,
            "event_type": self.event_type,
            "channel": self.channel,
            "payload": encode_value(self.payload),
            "source_timestamp": self.source_timestamp.isoformat(),
            "received_timestamp": self.received_timestamp.isoformat(),
            "session_id": self.session_id,
            "peer_id": self.peer_id,
            "sequence": self.sequence,
            "raw_hash": self.raw_hash,
            "provenance": encode_value(self.provenance),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ApplicationEvent":
        return cls(
            event_id=str(data["event_id"]),
            schema_version=int(data.get("schema_version", 1)),
            source_app=str(data["source_app"]),
            event_type=str(data["event_type"]),
            channel=str(data["channel"]),
            payload=decode_value(data["payload"]),
            source_timestamp=datetime.fromisoformat(str(data["source_timestamp"])),
            received_timestamp=datetime.fromisoformat(str(data["received_timestamp"])),
            session_id=str(data["session_id"]),
            peer_id=str(data["peer_id"]),
            sequence=int(data["sequence"]),
            raw_hash=str(data["raw_hash"]),
            provenance=decode_value(data.get("provenance", {})),
        )
