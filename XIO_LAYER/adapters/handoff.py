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

from ..core.audit import AuditLedger, PermissionRegistry
from ..core.contracts import content_hash, require_utc, utc_now
from ..core.events import ApplicationEvent
from ..core.transport import DeliveryReceipt, DeliveryStatus, Endpoint, Transport, TransportMessage
from .lucida_bridge import application_event_to_transport, transport_to_application_event
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
        payload_keys = _read_policy_keys(self.allowed_payload_keys, "allowed_payload_keys")
        provenance_keys = _read_policy_keys(self.allowed_provenance_keys, "allowed_provenance_keys")
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
        if not isinstance(self.selection, AdapterSelection):
            raise TypeError("selection must be an AdapterSelection")
        if not isinstance(self.event, ApplicationEvent):
            raise TypeError("event must be an ApplicationEvent")
        if not isinstance(self.message, TransportMessage):
            raise TypeError("message must be a TransportMessage")
        if not isinstance(self.privacy_policy, PrivacyPolicy):
            raise TypeError("privacy_policy must be a PrivacyPolicy")
        if not handoff_id_is_valid(self.handoff_id):
            raise AdapterHandoffError("handoff_id must be a non-empty ASCII identifier")
        if self.event.source_app != self.selection.source_app or self.event.event_type != self.selection.event_type:
            raise AdapterHandoffError("event does not match selected route")
        try:
            bridged_event = transport_to_application_event(self.message)
        except Exception as exc:
            raise AdapterHandoffError("message failed bridge validation") from exc
        if bridged_event.to_dict() != self.event.to_dict():
            raise AdapterHandoffError("event and transport message do not match")
        object.__setattr__(self, "prepared_at", require_utc(self.prepared_at, "prepared_at"))

    def to_dict(self, *, include_caller: bool = False) -> dict[str, Any]:
        """Serialize only the projected event and public selection metadata."""

        selection = self.selection.to_dict()
        if not include_caller:
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

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, caller_id: str | None = None) -> "AdapterHandoff":
        if not isinstance(data, Mapping):
            raise AdapterHandoffError("adapter handoff must be a mapping")
        required = {
            "handoff_id",
            "selection",
            "event",
            "message",
            "prepared_at",
            "privacy_policy",
            "status",
        }
        if set(data) != required or data["status"] != "prepared":
            raise AdapterHandoffError("adapter handoff fields do not match the contract")
        selection_data = data["selection"]
        if not isinstance(selection_data, Mapping):
            raise AdapterHandoffError("handoff selection must be a mapping")
        selection_data = dict(selection_data)
        stored_caller = selection_data.get("caller_id")
        if stored_caller is None:
            if caller_id is None:
                raise AdapterHandoffError("caller_id is required to restore a public handoff")
            selection_data["caller_id"] = caller_id
        elif caller_id is not None and stored_caller != caller_id:
            raise AdapterHandoffError("caller_id does not match the stored selection")
        try:
            selection = AdapterSelection.from_dict(selection_data)
            event = ApplicationEvent.from_dict(data["event"])
            message = _transport_from_dict(data["message"])
            prepared_at = datetime.fromisoformat(str(data["prepared_at"]))
            privacy = _privacy_from_dict(data["privacy_policy"])
        except (TypeError, ValueError, KeyError) as exc:
            raise AdapterHandoffError("adapter handoff could not be restored") from exc
        try:
            bridged_event = transport_to_application_event(message)
        except Exception as exc:
            raise AdapterHandoffError("restored handoff message failed bridge validation") from exc
        if bridged_event.to_dict() != event.to_dict():
            raise AdapterHandoffError("restored event and transport message do not match")
        if event.source_app != selection.source_app or event.event_type != selection.event_type:
            raise AdapterHandoffError("restored event does not match selected route")
        return cls(
            handoff_id=data["handoff_id"],
            selection=selection,
            event=event,
            message=message,
            prepared_at=prepared_at,
            privacy_policy=privacy,
        )


@dataclass(frozen=True, slots=True)
class AdapterHandoffDelivery:
    """Receipt from one explicit delivery attempt for a prepared handoff."""

    handoff_id: str
    status: str
    receipt: DeliveryReceipt | None
    attempted_at: datetime
    error: str | None = None

    def __post_init__(self) -> None:
        if not handoff_id_is_valid(self.handoff_id):
            raise AdapterHandoffError("handoff_id must be a non-empty ASCII identifier")
        if not isinstance(self.status, str) or self.status not in {
            "accepted", "duplicate", "conflict", "rejected", "failed"
        }:
            raise AdapterHandoffError("delivery status is invalid")
        if self.receipt is not None and not isinstance(self.receipt, DeliveryReceipt):
            raise TypeError("receipt must be a DeliveryReceipt or None")
        if self.status in {"accepted", "duplicate", "conflict"} and self.receipt is None:
            raise AdapterHandoffError("successful delivery statuses require a receipt")
        if self.status == "duplicate" and not self.receipt.duplicate:
            raise AdapterHandoffError("duplicate status requires a duplicate receipt")
        if self.status == "accepted" and (not self.receipt.accepted or self.receipt.duplicate):
            raise AdapterHandoffError("accepted status requires a non-duplicate accepted receipt")
        if self.status == "conflict" and self.receipt.status is not DeliveryStatus.IDEMPOTENCY_CONFLICT:
            raise AdapterHandoffError("conflict status requires an idempotency-conflict receipt")
        if self.error is not None and not isinstance(self.error, str):
            raise TypeError("error must be a string or None")
        object.__setattr__(self, "attempted_at", require_utc(self.attempted_at, "attempted_at"))

    def to_dict(self) -> dict[str, Any]:
        receipt = None
        if self.receipt is not None:
            receipt = {
                "message_id": self.receipt.message_id,
                "accepted": self.receipt.accepted,
                "duplicate": self.receipt.duplicate,
                "sequence": self.receipt.sequence,
                "latency_ms": self.receipt.latency_ms,
                "error": self.receipt.error,
                "delivered_at": self.receipt.delivered_at.isoformat()
                if self.receipt.delivered_at is not None
                else None,
            }
        return {
            "handoff_id": self.handoff_id,
            "status": self.status,
            "receipt": receipt,
            "attempted_at": self.attempted_at.isoformat(),
            "error": self.error,
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


def deliver_adapter_handoff(
    handoff: AdapterHandoff,
    transport: Transport,
    audit: AuditLedger,
    *,
    permissions: PermissionRegistry,
    required_permission: str = "handoff.deliver",
) -> AdapterHandoffDelivery:
    """Deliver one prepared handoff after a current caller permission check."""

    if not isinstance(handoff, AdapterHandoff):
        raise TypeError("handoff must be an AdapterHandoff")
    if not callable(getattr(transport, "send", None)):
        raise TypeError("transport must provide send")
    if not callable(getattr(audit, "append", None)):
        raise TypeError("audit must provide append")
    if not isinstance(permissions, PermissionRegistry):
        raise TypeError("permissions must be a PermissionRegistry")
    if not isinstance(required_permission, str) or not required_permission.strip():
        raise ValueError("required_permission cannot be empty")

    attempted_at = utc_now()
    try:
        allowed, receipt = permissions.run_if_allowed(
            handoff.selection.caller_id,
            required_permission,
            lambda: transport.send(handoff.message),
        )
        if not allowed:
            audit.append(
                "adapter.handoff.delivery_rejected",
                handoff.handoff_id,
                "rejected",
                {
                    **_delivery_audit_metadata(handoff, error="permission_missing_or_revoked"),
                    "permission": required_permission,
                },
                handoff.selection.caller_id,
            )
            return AdapterHandoffDelivery(
                handoff_id=handoff.handoff_id,
                status="rejected",
                receipt=None,
                attempted_at=attempted_at,
                error="permission_missing_or_revoked",
            )
        if not isinstance(receipt, DeliveryReceipt):
            raise AdapterHandoffError("transport returned an invalid delivery receipt")
        status = (
            "duplicate"
            if receipt.duplicate
            else "accepted"
            if receipt.accepted
            else "conflict"
            if receipt.status is DeliveryStatus.IDEMPOTENCY_CONFLICT
            else "rejected"
        )
        event_type = {
            "accepted": "adapter.handoff.delivered",
            "duplicate": "adapter.handoff.delivered",
            "conflict": "adapter.handoff.delivery_conflict",
            "rejected": "adapter.handoff.delivery_rejected",
        }[status]
        audit.append(
            event_type,
            handoff.handoff_id,
            status,
            _delivery_audit_metadata(handoff, receipt=receipt),
            handoff.selection.caller_id,
        )
        return AdapterHandoffDelivery(
            handoff_id=handoff.handoff_id,
            status=status,
            receipt=receipt,
            attempted_at=attempted_at,
        )
    except PermissionError as exc:
        audit.append(
            "adapter.handoff.delivery_rejected",
            handoff.handoff_id,
            "rejected",
            _delivery_audit_metadata(handoff, error=type(exc).__name__),
            handoff.selection.caller_id,
        )
        return AdapterHandoffDelivery(
            handoff_id=handoff.handoff_id,
            status="rejected",
            receipt=None,
            attempted_at=attempted_at,
            error=type(exc).__name__,
        )
    except Exception as exc:
        audit.append(
            "adapter.handoff.delivery_failed",
            handoff.handoff_id,
            "failed",
            _delivery_audit_metadata(handoff, error=type(exc).__name__),
            handoff.selection.caller_id,
        )
        return AdapterHandoffDelivery(
            handoff_id=handoff.handoff_id,
            status="failed",
            receipt=None,
            attempted_at=attempted_at,
            error=type(exc).__name__,
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


def _delivery_audit_metadata(
    handoff: AdapterHandoff,
    *,
    receipt: DeliveryReceipt | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    metadata = {
        "selection_id": handoff.selection.selection_id,
        "source_app": handoff.selection.source_app,
        "event_type": handoff.selection.event_type,
        "message_id": handoff.message.message_id,
        "sequence": handoff.message.sequence,
    }
    if receipt is not None:
        metadata.update(
            {
                "delivery_status": receipt.status.value,
                "duplicate": receipt.duplicate,
                "latency_ms": receipt.latency_ms,
                "receipt_error": receipt.error,
            }
        )
    if error is not None:
        metadata["error_type"] = error
    return metadata


def _privacy_from_dict(value: Any) -> PrivacyPolicy:
    if not isinstance(value, Mapping):
        raise AdapterHandoffError("privacy policy must be a mapping")
    required = {
        "allowed_payload_keys",
        "allowed_provenance_keys",
        "expose_session_id",
        "expose_peer_id",
        "version",
    }
    if set(value) != required or value["version"] != "allowlist-v1":
        raise AdapterHandoffError("privacy policy fields do not match the contract")
    return PrivacyPolicy(
        allowed_payload_keys=frozenset(value["allowed_payload_keys"]),
        allowed_provenance_keys=frozenset(value["allowed_provenance_keys"]),
        expose_session_id=value["expose_session_id"],
        expose_peer_id=value["expose_peer_id"],
    )


def _transport_from_dict(value: Any) -> TransportMessage:
    try:
        return TransportMessage.from_dict(value)
    except Exception as exc:
        raise AdapterHandoffError("handoff message could not be restored") from exc


def _opaque_id(prefix: str, value: str) -> str:
    return f"{prefix}-{content_hash(value)[:16]}"


def _validate_key(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value or not value.isascii():
        raise PrivacyPolicyError(f"{field_name} must be a non-empty ASCII key")
    if not value[0].isalnum() or any(not (char.isalnum() or char in "._-") for char in value):
        raise PrivacyPolicyError(f"{field_name} contains unsupported characters")


def _read_policy_keys(value: Any, field_name: str) -> frozenset[str]:
    if isinstance(value, (str, bytes, Mapping)) or value is None:
        raise PrivacyPolicyError(f"{field_name} must be a collection of keys")
    try:
        values = frozenset(value)
    except TypeError as exc:
        raise PrivacyPolicyError(f"{field_name} must be a collection of keys") from exc
    if any(not isinstance(item, str) for item in values):
        raise PrivacyPolicyError(f"{field_name} must contain strings")
    return values


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
    "AdapterHandoffDelivery",
    "AdapterHandoffError",
    "PrivacyPolicy",
    "PrivacyPolicyError",
    "handoff_id_is_valid",
    "deliver_adapter_handoff",
    "prepare_adapter_handoff",
]
