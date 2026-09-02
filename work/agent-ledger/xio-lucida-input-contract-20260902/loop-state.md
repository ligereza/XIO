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
status: paused
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
  tests_and_checks: The current XIO_LAYER test command passed before this state-only correction; no technical source files are changed by this correction.
  assumptions: XIO remains the signal and transport owner; LUCIDA consumes declared events through its own adapter boundary.
  open_questions:
    - The next XIO contract defect must be selected after the user resumes the paused agent.
  blockers:
    - Agent execution is paused by the user; do not resume from this state without explicit direction.
  next_action: Remain paused. When resumed, read this state only, work on the current XIO branch and never reopen LIMEN.
  next_checkpoint_trigger: before resuming autonomous work or publishing any XIO code change
