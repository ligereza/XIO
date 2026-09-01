"""Explicit caller-selected adapter handoff to LUCIDA/MULTI.

This module prepares a transport message. It never sends the message, opens a
socket, discovers a peer, or invokes an XIO executor. Payload and provenance
data are projected through an explicit allowlist before crossing the bridge.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from uuid import uuid4

from ..core.audit import AuditLedger
from ..core.contracts import content_hash, require_utc, utc_now
from ..core.events import ApplicationEvent
from ..core.transport import Endpoint, TransportMessage
from .lucida_bridge import application_event_to_transport
from .source_registry import AdapterSelection, SourceAdapterRegistry


class AdapterHandoffError(ValueError):
    """Raised when a selected adapter cannot be handed off safely."""


class PrivacyPolicyError(AdapterHandoffError):
    """Raised when an allowlisted projection cannot be created."""


@dataclass(frozen=True, slots=True)
class PrivacyPolicy:
    """Top-level allowlist for data crossing the adapter handoff boundary."""

    allowed_payload_keys: frozenset[str] = frozenset()
    allowed_provenance_keys: frozenset[str] = frozenset()
    expose_session_id: bool = False
    expose_peer_id: bool = False

    def __post_init__(self) -> None:
        payload_keys = frozenset(self.allowed_payload_keys)
        provenance_keys = frozenset(self.allowed_provenance_keys)
        for key in payload_keys:
            _validate_key(key, "allowed_payload_key")
        for key in provenance_keys:
            _validate_key(key, "allowed_provenance_key")
        object.__setattr__(self, "allowed_payload_keys", payload_keys)
        object.__setattr__(self, "allowed_provenance_keys", provenance_keys)
        if not isinstance(self.expose_session_id, bool) or not isinstance(self.expose_peer_id, bool):
            raise PrivacyPolicyError("identifier exposure flags must be boolean")

    def project(
        self,
        event: ApplicationEvent,
        *,
        selection: AdapterSelection,
        handoff_id: str,
    ) -> ApplicationEvent:
        """Return a redacted event with safe handoff provenance."""

        if not isinstance(event, ApplicationEvent):
            raise PrivacyPolicyError("privacy projection accepts ApplicationEvent only")
        if self.allowed_payload_keys and not isinstance(event.payload, Mapping):
            raise PrivacyPolicyError("allowlisted payload keys require a mapping payload")
        if not isinstance(event.provenance, Mapping):
            raise PrivacyPolicyError("event provenance must be a mapping")

        payload = {
            key: deepcopy(event.payload[key])
            for key in sorted(self.allowed_payload_keys)
            if key in event.payload
        }
        provenance = {
            key: deepcopy(event.provenance[key])
            for key in sorted(self.allowed_provenance_keys)
            if key in event.provenance
        }
        provenance.update(
            {
                "xio_handoff_id": handoff_id,
                "xio_original_event_fingerprint": event.fingerprint,
                "xio_privacy_policy": "allowlist-v1",
                "xio_selection_id": selection.selection_id,
            }
        )
        return ApplicationEvent(
            event_id=event.event_id,
            schema_version=event.schema_version,
            source_app=event.source_app,
            event_type=event.event_type,
            channel=event.channel,
            payload=payload,
            source_timestamp=event.source_timestamp,
            received_timestamp=event.received_timestamp,
            session_id=_opaque_id("session", event.session_id)
            if not self.expose_session_id
            else event.session_id,
            peer_id=_opaque_id("peer", event.peer_id) if not self.expose_peer_id else event.peer_id,
            sequence=event.sequence,
            provenance=provenance,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_payload_keys": sorted(self.allowed_payload_keys),
            "allowed_provenance_keys": sorted(self.allowed_provenance_keys),
            "expose_session_id": self.expose_session_id,
            "expose_peer_id": self.expose_peer_id,
            "version": "allowlist-v1",
        }


@dataclass(frozen=True, slots=True)
class AdapterHandoff:
    """Prepared, auditable handoff; ``message`` still requires an explicit send."""

    handoff_id: str
    selection: AdapterSelection
    event: ApplicationEvent
    message: TransportMessage
    prepared_at: datetime
    privacy_policy: PrivacyPolicy

    def __post_init__(self) -> None:
        if not handoff_id_is_valid(self.handoff_id):
            raise AdapterHandoffError("handoff_id must be a non-empty ASCII identifier")
        object.__setattr__(self, "prepared_at", require_utc(self.prepared_at, "prepared_at"))

    def to_dict(self) -> dict[str, Any]:
        """Serialize only the projected event and public selection metadata."""

        selection = self.selection.to_dict()
        selection.pop("caller_id", None)
        return {
            "handoff_id": self.handoff_id,
            "selection": selection,
            "event": self.event.to_dict(),
            "message": self.message.to_dict(),
            "prepared_at": self.prepared_at.isoformat(),
            "privacy_policy": self.privacy_policy.to_dict(),
            "status": "prepared",
        }


def prepare_adapter_handoff(
    registry: SourceAdapterRegistry,
    selection: AdapterSelection,
    record: Mapping[str, Any],
    *,
    source: str,
    destination: Endpoint,
    audit: AuditLedger,
    privacy_policy: PrivacyPolicy | None = None,
    sent_at: datetime | None = None,
    message_id: str | None = None,
    handoff_id: str | None = None,
) -> AdapterHandoff:
    """Convert the caller's selected adapter record into a prepared LUCIDA message.

    The registry is revalidated immediately before conversion. The supplied
    record is passed only to the selected adapter; it is never copied into the
    audit ledger or the handoff metadata. ``audit`` is required so successful
    and rejected handoffs are inspectable.
    """

    if not isinstance(registry, SourceAdapterRegistry):
        raise TypeError("registry must be a SourceAdapterRegistry")
    if not isinstance(selection, AdapterSelection):
        raise TypeError("selection must be an AdapterSelection")
    if not isinstance(record, Mapping):
        raise AdapterHandoffError("record must be a mapping")
    if not isinstance(destination, Endpoint):
        raise TypeError("destination must be an Endpoint")
    if not callable(getattr(audit, "append", None)):
        raise TypeError("audit must provide append")
    if not isinstance(source, str) or not source.strip():
        raise AdapterHandoffError("source cannot be empty")

    resolved_handoff_id = handoff_id or str(uuid4())
    if not handoff_id_is_valid(resolved_handoff_id):
        raise AdapterHandoffError("handoff_id must be a non-empty ASCII identifier")
    privacy = privacy_policy or PrivacyPolicy()
    prepared_at = utc_now()

    try:
        registry.validate_selection(selection)
        event = registry.route(selection.source_app, selection.event_type, record)
        projected = privacy.project(event, selection=selection, handoff_id=resolved_handoff_id)
        message = application_event_to_transport(
            projected,
            source=source,
            destination=destination,
            sent_at=sent_at,
            message_id=message_id,
        )
    except Exception as exc:
        audit.append(
            "adapter.handoff.rejected",
            resolved_handoff_id,
            "rejected",
            _audit_metadata(selection, reason=type(exc).__name__),
            selection.caller_id,
        )
        raise

    audit.append(
        "adapter.handoff.prepared",
        resolved_handoff_id,
        "prepared",
        _audit_metadata(
            selection,
            event_id=projected.event_id,
            original_event_fingerprint=event.fingerprint,
            projected_event_fingerprint=projected.fingerprint,
            destination_scope=destination.scope.value,
            destination_scheme=destination.scheme,
            privacy_policy=privacy.to_dict(),
        ),
        selection.caller_id,
    )
    return AdapterHandoff(
        handoff_id=resolved_handoff_id,
        selection=selection,
        event=projected,
        message=message,
        prepared_at=prepared_at,
        privacy_policy=privacy,
    )


def _audit_metadata(selection: AdapterSelection, **extra: Any) -> dict[str, Any]:
    metadata = {
        "selection_id": selection.selection_id,
        "source_app": selection.source_app,
        "event_type": selection.event_type,
        "plan_fingerprint": selection.plan_fingerprint,
    }
    metadata.update(extra)
    return metadata


def _opaque_id(prefix: str, value: str) -> str:
    return f"{prefix}-{content_hash(value)[:16]}"


def _validate_key(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value or not value.isascii():
        raise PrivacyPolicyError(f"{field_name} must be a non-empty ASCII key")
    if not value[0].isalnum() or any(not (char.isalnum() or char in "._-") for char in value):
        raise PrivacyPolicyError(f"{field_name} contains unsupported characters")


def handoff_id_is_valid(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value.isascii()
        and value[0].isalnum()
        and all(char.isalnum() or char in "._-" for char in value)
    )


__all__ = [
    "AdapterHandoff",
    "AdapterHandoffError",
    "PrivacyPolicy",
    "PrivacyPolicyError",
    "handoff_id_is_valid",
    "prepare_adapter_handoff",
]
