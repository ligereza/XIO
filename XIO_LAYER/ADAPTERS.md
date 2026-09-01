# Source adapter registry

`SourceAdapterRegistry` is the portable boundary for future Adobe, Resolume
and other application adapters. It has no host SDK imports, socket code or
peer discovery.

Each adapter declares:

```text
source_app
supported_event_types
capabilities
convert(record, event_type) -> ApplicationEvent
```

`source_app`, event types and capabilities are stable ASCII identifiers. The
registry snapshots those declarations at registration time, rejects duplicate
or invalid source ids, and routes only declared event types. An unknown source
or undeclared type fails before the adapter is called and does not mutate the
registry or source record.

Adapters receive a source record that was validated by the host boundary. They
must return the existing `ApplicationEvent` contract and preserve event id,
sequence, timestamps, raw hash and provenance. The registry verifies that the
returned event matches the routed source and event type.

`ProtocolEventAdapter` now declares OSC and Art-Net event types and can be
routed through the same registry. Its existing direct `from_osc` and
`from_artnet` methods remain available. No registry route creates an action;
events remain observations for replay, reducers or analysis.
