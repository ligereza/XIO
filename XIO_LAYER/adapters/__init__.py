"""Host/device adapter boundaries."""

from .lucida_bridge import (
    APPLICATION_EVENT_CHANNEL,
    APPLICATION_EVENT_ENVELOPE_TYPE,
    APPLICATION_EVENT_SCHEMA_VERSION,
    LucidaApplicationEnvelope,
    LucidaBridgeError,
    application_event_to_transport,
    transport_to_application_event,
)
from .protocol_events import ProtocolEventAdapter

__all__ = [
    "APPLICATION_EVENT_CHANNEL",
    "APPLICATION_EVENT_ENVELOPE_TYPE",
    "APPLICATION_EVENT_SCHEMA_VERSION",
    "LucidaApplicationEnvelope",
    "LucidaBridgeError",
    "ProtocolEventAdapter",
    "application_event_to_transport",
    "transport_to_application_event",
]
