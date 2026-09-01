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
from .handoff import (
    AdapterHandoff,
    AdapterHandoffError,
    PrivacyPolicy,
    PrivacyPolicyError,
    prepare_adapter_handoff,
)
from .local_source import (
    DuplicateLocalEventError,
    LocalAdapterEventSource,
    LocalEventRecord,
    LocalEventSourceError,
)
from .protocol_events import ProtocolEventAdapter
from .source_registry import (
    AdapterSelection,
    CandidateNotAvailableError,
    DuplicateSourceAdapterError,
    InvalidSourceAdapterError,
    NoRouteMatchError,
    SourceAdapter,
    SourceAdapterDeclaration,
    SourceAdapterRegistry,
    SourceAdapterRegistryError,
    StaleRoutePlanError,
    UndeclaredEventTypeError,
    UnknownSourceAdapterError,
)

__all__ = [
    "CONNECTIVITY_EVENT_CHANNEL",
    "CONNECTIVITY_EVENT_TYPE",
    "APPLICATION_EVENT_CHANNEL",
    "APPLICATION_EVENT_ENVELOPE_TYPE",
    "APPLICATION_EVENT_SCHEMA_VERSION",
    "AdapterHandoff",
    "AdapterHandoffError",
    "AdapterSelection",
    "CandidateNotAvailableError",
    "DuplicateLocalEventError",
    "LucidaApplicationEnvelope",
    "LucidaBridgeError",
    "LocalAdapterEventSource",
    "LocalEventRecord",
    "LocalEventSourceError",
    "NoRouteMatchError",
    "PrivacyPolicy",
    "PrivacyPolicyError",
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
    "StaleRoutePlanError",
    "transport_to_application_event",
    "UndeclaredEventTypeError",
    "UnknownSourceAdapterError",
    "prepare_adapter_handoff",
]
