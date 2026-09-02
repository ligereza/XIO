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

Adapters receive an isolated copy of a source record that was validated by the
host boundary. They must return the existing `ApplicationEvent` contract and
preserve event id, sequence, timestamps, raw hash and caller-supplied provenance.
The registry verifies those fields when supplied, while allowing an adapter to
add provenance or synthesize fields that were absent from the record.

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
`AdapterSelection.to_dict()` and `AdapterSelection.from_dict()` preserve that
explicit choice across a restart; restored selections still require current
plan validation before handoff.

`prepare_adapter_handoff(...)` revalidates that selection immediately before
calling only the selected adapter's `convert()` method. It creates a
`TransportMessage` for the existing LUCIDA/MULTI application-event bridge but
does not call `send()`, open sockets, discover peers or invoke an XIO executor.
The caller retains the explicit decision to deliver the prepared message.

`deliver_adapter_handoff(...)` is the separate explicit delivery step. It
accepts a caller-injected transport, returns an `AdapterHandoffDelivery` with
the transport receipt, and audits accepted, duplicate, rejected and failed
attempts. A transport policy rejection is reported as `rejected`; an
idempotency fingerprint conflict is reported as terminal `conflict`. Neither
case triggers retry or alternate adapter selection.

Delivery also requires a current `PermissionRegistry` grant for the selected
caller, defaulting to `handoff.deliver`. The permission is checked immediately
before `transport.send()`. A revoked or missing grant returns `rejected`, is
audited, and leaves the transport untouched.

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

`AdapterHandoff.to_dict()` is privacy-safe by default and omits `caller_id`.
`AdapterHandoff.from_dict(..., caller_id=...)` requires the caller to re-inject
that identity explicitly, validates the stored LUCIDA/MULTI message against the
projected event, and restores only a `prepared` handoff. It never sends the
restored message.

`JsonLineAuditLedger` is the restart-safe local implementation of that port:
it writes one JSONL entry at a time, fsyncs before exposing the entry in memory,
revalidates the full hash chain on startup, and rejects malformed or tampered
files. Its append path reloads the current ledger while holding a sidecar file
lock, so separate processes extend one hash chain instead of using stale
in-memory state.

`JsonLineHandoffStore` persists prepared handoffs without `caller_id`. Appending
the same handoff id and stable prepared content is idempotent; changing that
content is rejected as `DuplicateHandoffError`. Replay requires an explicit
caller id and restores `prepared` handoffs only. Each JSONL line has a versioned
envelope with a previous hash and record hash; tampering or reordering is
rejected before reconstruction. Calls are serialized both within one process
and across processes through a sidecar lock file. The store never delivers a
message. Its persisted schema version is validated as a real integer, so
boolean values cannot masquerade as version `1` during integrity checks.

## Replayable local source

`LocalAdapterEventSource` reads a caller-owned JSONL file as a read-only source.
It validates timestamps, ids, payload/provenance JSON safety and exact fields,
deduplicates identical event ids, rejects conflicting duplicates, and returns
records ordered by ingestion `sequence`. `prepare_handoffs(...)` requires an
already-created `AdapterSelection` and rejects records belonging to another
source or event type. It prepares one handoff per record and never delivers or
executes them. The fixture
`tests/fixtures/lucida_handoff_records.jsonl` covers source replay, redaction,
the LUCIDA/MULTI envelope, audit and application-event replay together.
Replay-derived handoff ids are deterministic for a given selection and event,
so repeating the same source cannot alter provenance or manufacture an
idempotency conflict.
