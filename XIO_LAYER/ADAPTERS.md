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

## Explicit selection and handoff

`SourceAdapterRegistry.select_candidate(...)` records the caller's exact
choice as an `AdapterSelection`. The selection contains the caller id, event
type, required capabilities and a fingerprint of the route plan. If a supplied
plan is changed, stale, has no candidates, or names a non-candidate source, the
selection is rejected. No adapter is called during planning or selection.

`prepare_adapter_handoff(...)` revalidates that selection immediately before
calling only the selected adapter's `convert()` method. It creates a
`TransportMessage` for the existing LUCIDA/MULTI application-event bridge but
does not call `send()`, open sockets, discover peers or invoke an XIO executor.
The caller retains the explicit decision to deliver the prepared message.

The default `PrivacyPolicy` exports no payload or source provenance keys and
replaces session and peer identifiers with opaque hashes. A caller must
explicitly allow top-level payload/provenance keys to export them. The handoff
adds only safe provenance markers (`xio_handoff_id`, selection id, privacy
policy and an original event fingerprint). The audit ledger records route and
fingerprint metadata, never the source record, payload, credentials or network
address.

The projected event remains a normal `ApplicationEvent`: it can be appended to
`ApplicationEventLog` and replayed by sequence. Replay reconstructs state only;
it cannot select another adapter or execute an action. Successful and rejected
handoffs are hash-chained in `AuditLedger`.
