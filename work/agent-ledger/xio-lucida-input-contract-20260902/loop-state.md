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

current_state:
  files_or_resources:
    - XIO_LAYER
    - work/agent-ledger/xio-lucida-input-contract-20260902/loop-state.md
    - work/agent-ledger/xio-lucida-input-contract-20260902/critique.md
  branch: codex/xio-lucida-input-contract
  worktree: C:\IA\XIO
  tests_and_checks: XIO_LAYER suite passes 164 tests; transport-focused suite passes 11 tests; event-log, snapshot, JSON-key and selection-identity regressions pass; compileall, technical ASCII and diff checks pass.
  assumptions: XIO remains the signal and transport owner; LUCIDA consumes declared events through its own adapter boundary.
  open_questions:
    - Further work remains bounded to signal, transport and input-contract reliability.
  blockers: []
  next_action: Reassess the next XIO signal, transport or input-contract boundary before another code change; preserve unrelated root changes and never reopen the archived extraction.
  next_checkpoint_trigger: before resuming autonomous work or publishing any XIO code change
