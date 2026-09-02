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

current_state:
  files_or_resources:
    - XIO_LAYER
    - work/agent-ledger/xio-lucida-input-contract-20260902/loop-state.md
  branch: codex/xio-lucida-input-contract
  worktree: C:\IA\XIO
  tests_and_checks: The current XIO_LAYER test command passed before this iteration; local source strict-restore regression is in progress.
  assumptions: XIO remains the signal and transport owner; LUCIDA consumes declared events through its own adapter boundary.
  open_questions:
    - Further work remains bounded to signal, transport and input-contract reliability.
  blockers: []
  next_action: Verify and publish the strict LocalEventRecord restore fix on the current XIO branch; never reopen the archived extraction.
  next_checkpoint_trigger: before resuming autonomous work or publishing any XIO code change
