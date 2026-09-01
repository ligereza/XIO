"""Host/device adapter boundaries."""

from .connectivity_events import (
    CONNECTIVITY_EVENT_CHANNEL,
    CONNECTIVITY_EVENT_TYPE,
    ConnectivityEventError,
    connectivity_status_to_event,
)
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
from .source_registry import (
    DuplicateSourceAdapterError,
    InvalidSourceAdapterError,
    SourceAdapter,
    SourceAdapterDeclaration,
    SourceAdapterRegistry,
    SourceAdapterRegistryError,
    UndeclaredEventTypeError,
    UnknownSourceAdapterError,
)

__all__ = [
    "CONNECTIVITY_EVENT_CHANNEL",
    "CONNECTIVITY_EVENT_TYPE",
    "APPLICATION_EVENT_CHANNEL",
    "APPLICATION_EVENT_ENVELOPE_TYPE",
    "APPLICATION_EVENT_SCHEMA_VERSION",
    "LucidaApplicationEnvelope",
    "LucidaBridgeError",
    "ProtocolEventAdapter",
    "application_event_to_transport",
    "ConnectivityEventError",
    "connectivity_status_to_event",
    "DuplicateSourceAdapterError",
    "InvalidSourceAdapterError",
    "SourceAdapter",
    "SourceAdapterDeclaration",
    "SourceAdapterRegistry",
    "SourceAdapterRegistryError",
    "transport_to_application_event",
    "UndeclaredEventTypeError",
    "UnknownSourceAdapterError",
]
