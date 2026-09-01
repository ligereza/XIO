"""Pure conversion from host connectivity status to ApplicationEvent."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from ..core.contracts import content_hash
from ..core.events import ApplicationEvent
from ..core.transport import ConnectionStatus


CONNECTIVITY_EVENT_TYPE = "connectivity.status"
CONNECTIVITY_EVENT_CHANNEL = "transport"


class ConnectivityEventError(ValueError):
    """Raised when a connectivity status cannot become a canonical event."""


def connectivity_status_to_event(
    status: ConnectionStatus,
    *,
    source_app: str,
    session_id: str,
    peer_id: str,
    sequence: int,
    received_timestamp: datetime,
    provenance: Mapping[str, Any] | None = None,
) -> ApplicationEvent:
    """Convert one host-owned status without measuring or filling missing data."""

    if not isinstance(status, ConnectionStatus):
        raise ConnectivityEventError("adapter accepts ConnectionStatus only")

    status_payload = status.to_dict()
    status_payload["loss_ratio"] = status.loss_ratio
    stable_identity = {
        "source_app": source_app,
        "session_id": session_id,
        "peer_id": peer_id,
        "event_type": CONNECTIVITY_EVENT_TYPE,
        "channel": CONNECTIVITY_EVENT_CHANNEL,
        "status": status_payload,
    }
    event_id = "connectivity-" + content_hash(stable_identity)
    event_provenance = {
        "adapter": "connectivity_status",
        "origin": "host_probe",
        "status_contract": "ConnectionStatus",
        "status_hash": content_hash(status_payload),
        **dict(provenance or {}),
    }
    return ApplicationEvent(
        event_id=event_id,
        source_app=source_app,
        event_type=CONNECTIVITY_EVENT_TYPE,
        channel=CONNECTIVITY_EVENT_CHANNEL,
        payload=status_payload,
        source_timestamp=status.checked_at,
        received_timestamp=received_timestamp,
        session_id=session_id,
        peer_id=peer_id,
        sequence=sequence,
        provenance=event_provenance,
    )


__all__ = [
    "CONNECTIVITY_EVENT_CHANNEL",
    "CONNECTIVITY_EVENT_TYPE",
    "ConnectivityEventError",
    "connectivity_status_to_event",
]
