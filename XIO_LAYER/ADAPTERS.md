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

## LUCIDA/MULTI registry consumer contract

`SourceAdapterRegistry.snapshot()` returns a new JSON-safe list on every call.
Entries are sorted by `source_app`; `supported_event_types` and `capabilities`
are sorted lists. Each entry contains only:

```text
source_app
supported_event_types
capabilities
```

The snapshot contains no adapter instances, callables, records, paths,
credentials or network state. LUCIDA/MULTI may cache or serialize it to select
an already registered source route. Mutating a returned snapshot cannot change
the registry. Unknown sources and undeclared event types remain rejected by
`route()`.

## LUCIDA/MULTI candidate discovery contract

`SourceAdapterRegistry.candidates(event_type, required_capabilities=())`
filters the frozen declarations without inspecting or executing adapters. It
returns a new JSON-safe list containing only `source_app`,
`supported_event_types` and `capabilities`. The list and both nested lists are
sorted deterministically. An empty list is the explicit no-match result.

`event_type` and every required capability use the same ASCII identifier rules
as registration. Invalid queries are rejected before registry state is read for
routing, and valid queries never expose records, paths, credentials, network
state or callable objects.

`SourceAdapterRegistry.route_plan(event_type, required_capabilities=())`
returns the same candidate declarations together with the query and a status
of `matched` or `no_match`. It is planning metadata only: it does not choose a
winner, inspect an adapter or call `convert()`. LUCIDA/MULTI must make any
source selection explicit before calling `route()`.
