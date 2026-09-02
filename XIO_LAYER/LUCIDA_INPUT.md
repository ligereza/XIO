# LUCIDA input contract

This is a narrow, host-neutral compatibility boundary for a future LUCIDA
Python reducer. It exposes metadata only; it does not import LUCIDA, forward
raw media, render UI, open sockets or choose actions.

## Public record

`LucidaInputRecord` contains exactly these fields:

```text
event_id
source
source_version
event_type
event_time
sequence
capability
privacy_status
data_summary
```

`event_time` is the canonical event source timestamp normalized to UTC.
`sequence` is the existing ingestion sequence and is the replay order. The
source version and capability are explicit caller metadata, not inferred by
the contract.

`data_summary` is bounded to 16 field descriptors. It contains only a value
kind, the number of visible descriptors, sorted field names and a truncation
flag. It never contains source values, bytes, media, credentials or arbitrary
objects. `PrivacyPolicy` supplies the existing top-level allowlist. The status
is `redacted` when fields are omitted or truncated, and `summary_only` when
the complete payload shape fits without exposing values.

## Persistence and replay

`LucidaInputLog` is backed by the existing `ApplicationEventLog`, so it keeps
fsync, sidecar locking, idempotent event ids and sequence-ordered replay. The
storage representation is still an XIO `ApplicationEvent`, but its payload is
only the bounded summary and its provenance contains the contract metadata.
The public replay result is a tuple of `LucidaInputRecord` values and exposes
no storage-only fields.

Appending the same record is idempotent. Reusing an event id with changed
content raises `DuplicateLucidaInputError`. Replacements are explicit:
`replace(previous_event_id, replacement)` appends a new event id and records
the internal replacement relation. History is never mutated; replay removes
the replaced public record and keeps the replacement. No replacement is
inferred from sequence or timestamp.

The synthetic fixture is
`tests/fixtures/lucida_input_events.jsonl`. Its lines are intentionally out of
order and include one identical duplicate to exercise replay behavior.
