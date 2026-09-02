objective: Maintain XIO as signal, transport and input-contract infrastructure for LUCIDA/MULTI without owning rendering, learning or host actions.
acceptance_criteria: Deterministic replay and safe recovery with explicit contracts; no action execution or unrelated repository changes.
current_state: Transport JSON safety is published on codex/xio-lucida-input-contract. EventLog replay orders by ingestion sequence but persistent loading does not reject missing sequence numbers.
verified_evidence: A temporary JSONL with sequences 1 and 3 loads successfully and a later append receives sequence 4, silently preserving a recovery gap.
assumptions: EventLog sequence is global ingestion order; an append-only log must be contiguous after duplicate elimination.
strongest_failure_mode: A deleted or lost persisted event is treated as a valid log, so replay and checkpoint recovery can produce incomplete state without an integrity issue.
highest_consequence_error: Marking recovered state as complete when an unobserved event is missing is worse than failing closed and reporting a persistence error.

options:
  - action: continue
    setup_cost: low
    execution_cost: low
    verification_cost: low
    rework_risk: low
    context_cost: low
    expected_benefit: Add contiguous-sequence validation and regression coverage at the persistent EventLog boundary.
    reversibility: high
    evidence_needed: Focused corruption test and full XIO_LAYER suite.
  - action: search
    setup_cost: medium
    execution_cost: medium
    verification_cost: medium
    rework_risk: medium
    context_cost: medium
    expected_benefit: Low; this is an internal contract already defined by the code and documentation.
    reversibility: high
    evidence_needed: External source would not change the local append-only invariant.
  - action: stop
    setup_cost: none
    execution_cost: none
    verification_cost: none
    rework_risk: high
    context_cost: low
    expected_benefit: Preserve current behavior but leave silent data loss possible.
    reversibility: high
    evidence_needed: Acceptance would need to permit silent sequence gaps.

search_gap:
  uncertainty: Whether any in-scope caller intentionally uses sparse global EventLog sequences.
  consequence: Medium; rejecting a sparse corrupted log could affect compatibility, while accepting one weakens recovery integrity.
  expected_error_reduction: Low from external research; callers and tests define this local contract.
  search_cost: Medium.
  marginal_value: Low.
  stop_reason: The append-only, monotonic-sequence contract and current tests support fail-closed validation.

selected_action: continue
confidence: high
next_checkpoint: Implement sequence-gap and duplicate-sequence detection, then run focused and complete tests before publishing.
previous_action: audit event ordering and snapshot recovery boundaries
decision_delta: change from observation to a bounded fail-closed recovery fix
verification_signal: EventLog must reject the temporary sequence 1,3 fixture before replay or append.
