run_id: xio-lucida-input-contract-20260902
objective: Maintain XIO as signal, transport and input-contract infrastructure for LUCIDA/MULTI without owning rendering, learning or host actions.
scope: XIO_LAYER only; preserve unrelated root worktree changes.
core_acceptance_criteria:
  - one canonical XIO objective and one active XIO worktree
  - explicit source, version, event and capability contracts
  - replayable and redacted inputs with deterministic ordering
  - English ASCII technical identifiers, fixtures, logs and tests
  - no overlay, camera, LUCIDA reducer, VIZZ/PUPILA policy or host action
authorized_extensions:
  - bounded signal and transport reliability fixes with reproducible tests
status: active
supersedes: xio-source-registry-20260901

completed:
  - item: State drift was diagnosed and the historical LIMEN state was closed.
    evidence: The superseded state is marked complete and names this canonical state.
  - item: The historical LIMEN worktree was moved to an archive branch and is not an active XIO worktree.
    evidence: The archive operation preserves commit a5a94ba without retaining the LIMEN branch name.
  - item: Local event input restoration rejects coercive field types.
    evidence: Commit 0efe36c is published on codex/xio-lucida-input-contract; LocalEventRecord rejects non-string identifiers and timestamps before constructing a record, with a focused regression.
  - item: Transport messages reject non-JSON payloads and envelopes.
    evidence: Transport-focused tests pass (11 tests); the complete XIO_LAYER suite passes 159 tests, and the JSONL writer rejects non-JSON numeric values.
  - item: Persistent EventLog fails closed on missing or reused ingestion sequences.
    evidence: A temporary 1,3 JSONL previously loaded and appended as 4; it now raises EventLogPersistenceError, as does the same event id at sequences 1 and 2. The focused regressions and full suite pass.
  - item: SnapshotStore preserves equal-version idempotency and rejects conflicting state.
    evidence: A temporary version-2 overwrite previously replaced total 3 with total 99; it now raises SnapshotConflictError and preserves the accepted snapshot. Documentation is synchronized.
  - item: Core JSON boundaries reject coercive object keys and audit invalid handler output.
    evidence: Event, ActionResult and TransportMessage reject integer mapping keys; ActionGate turns an invalid handler mapping into a failed, hash-verifiable audit entry. Documentation is synchronized.
  - item: Source selection preserves explicit identity semantics.
    evidence: select_candidate now rejects an explicitly empty selection_id, generates only when selection_id is None, and imports uuid4 for that valid path. Focused and full-suite tests pass.
  - item: Adapter routing isolates records and rejects identity drift.
    evidence: route now gives adapters a deep-copied record, normalizes serialized timestamps for comparison, and rejects changed caller-supplied identity/sequence/provenance. Adapter integration tests pass after the fixture was corrected to preserve supplied timestamps.
  - item: Wire timestamp restoration is non-coercive.
    evidence: TransportMessage, AdapterSelection and AdapterHandoff now require ISO string timestamp fields before parsing; focused restoration tests and the full suite pass. Documentation is synchronized.
  - item: Revocation and explicit disconnect invalidate stale pending handshakes.
    evidence: revoke_peer and disconnect now remove pending requests for the affected peer before changing trust state; focused handshake regressions and the complete XIO_LAYER suite pass (168 tests).
  - item: Handshake ACK status and acceptance are semantically consistent.
    evidence: HandshakeAck rejects accepted=True with a non-accepted status and accepted=False with accepted status before construction/restoration; contract regressions and the complete XIO_LAYER suite pass (168 tests).
  - item: Canonical ApplicationEvent preserves explicit identity semantics.
    evidence: ApplicationEvent now generates an event_id only when event_id is None; empty and falsy supplied values are rejected, with the complete XIO_LAYER suite passing 169 tests.
  - item: Handoff and bridge correlation IDs use None-only generation.
    evidence: prepare_adapter_handoff and application_event_to_transport now preserve explicit IDs for validation; empty supplied IDs fail, with focused regressions and the complete XIO_LAYER suite passing 171 tests.

current_state:
  files_or_resources:
    - XIO_LAYER
    - work/agent-ledger/xio-lucida-input-contract-20260902/loop-state.md
    - work/agent-ledger/xio-lucida-input-contract-20260902/critique.md
  branch: codex/xio-lucida-input-contract
  worktree: C:\IA\XIO
  tests_and_checks: XIO_LAYER suite passes 171 tests; focused stale-handshake, handshake-contract, explicit-event-identity and adapter-correlation regressions pass; adapter/handoff integration subset passes 40 tests; transport-focused suite passes 11 tests; event-log, snapshot, JSON-key, selection-identity, adapter-isolation and strict-restoration regressions pass; compileall, technical ASCII and diff checks pass.
  assumptions: XIO remains the signal and transport owner; LUCIDA consumes declared events through its own adapter boundary.
  open_questions:
    - Further work remains bounded to signal, transport and input-contract reliability.
  blockers: []
  next_action: Reassess the next XIO signal, transport or input-contract boundary after publishing this bounded adapter-correlation fix; preserve unrelated root changes and never reopen the archived extraction.
  next_checkpoint_trigger: before resuming autonomous work or publishing any XIO code change
