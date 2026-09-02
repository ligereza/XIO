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

---

objective: Maintain XIO as signal, transport and input-contract infrastructure for LUCIDA/MULTI without owning rendering, learning or host actions.
acceptance_criteria: Snapshot writes must not silently replace state at the same stream version; conflicts must be explicit and tested.
current_state: EventLog gap detection is published. SnapshotStore rejects older versions but overwrites a different same-version snapshot.
verified_evidence: A temporary store saved version 2 with state total 3, then version 2 with state total 99; latest returned total 99 without an error.
assumptions: A snapshot version identifies one materialized state for a stream, matching CheckpointStore conflict semantics.
strongest_failure_mode: Concurrent or stale projectors can replace an already accepted state at the same version, making recovery and audit evidence non-deterministic.
highest_consequence_error: Downstream consumers may observe a state that was never the first accepted materialization for that version.

options:
  - action: continue
    setup_cost: low
    execution_cost: low
    verification_cost: low
    rework_risk: low
    context_cost: low
    expected_benefit: Add an explicit same-version conflict error while preserving idempotent identical saves.
    reversibility: high
    evidence_needed: Regression for identical repeat, conflicting repeat and older version.
  - action: search
    setup_cost: medium
    execution_cost: medium
    verification_cost: medium
    rework_risk: medium
    context_cost: medium
    expected_benefit: Low; local CheckpointStore already defines the matching invariant.
    reversibility: high
    evidence_needed: External guidance would not supersede the declared XIO contract.
  - action: stop
    setup_cost: none
    execution_cost: none
    verification_cost: none
    rework_risk: high
    context_cost: low
    expected_benefit: Leave silent state replacement possible.
    reversibility: high
    evidence_needed: Acceptance would need to allow nondeterministic equal-version writes.

search_gap:
  uncertainty: Whether any caller intentionally uses equal-version snapshots as replacement state.
  consequence: Medium; rejecting replacement could expose an undocumented caller dependency, but accepting it violates stale-write protection.
  expected_error_reduction: Low from external research.
  search_cost: Medium.
  marginal_value: Low.
  stop_reason: SnapshotStore is explicitly described as having stale-write protection, and CheckpointStore already rejects same-version conflicts.

selected_action: continue
confidence: high
next_checkpoint: Implement same-version idempotency/conflict handling, test it, then rerun the complete suite.
previous_action: audit equal-version snapshot writes
decision_delta: change from reproduced overwrite to explicit conflict handling
verification_signal: A different state at the current version must raise before replacing latest.

---

objective: Maintain XIO as signal, transport and input-contract infrastructure for LUCIDA/MULTI without owning rendering, learning or host actions.
acceptance_criteria: JSON contracts must round-trip without coercion; invalid action outputs must become audited failed results.
current_state: EventLog and SnapshotStore integrity fixes are published. Core JSON checks relied on json.dumps, which accepts integer object keys by coercing them to strings.
verified_evidence: An Event payload with key 1 preserved an integer key in memory but round-tripped through JSON as key "1"; TransportMessage accepted the same shape.
assumptions: Object keys at every XIO contract boundary must be non-empty or empty strings as dictated by JSON object semantics, never coerced scalar keys.
strongest_failure_mode: A payload or handler result changes identity across serialization, causing fingerprint mismatch, replay drift or an uncaught ActionResult construction error without an audit result.
highest_consequence_error: A side-effecting handler can complete while its result cannot be represented or audited consistently.

options:
  - action: continue
    setup_cost: low
    execution_cost: medium
    verification_cost: low
    rework_risk: low
    context_cost: low
    expected_benefit: Centralize strict recursive JSON validation and reuse it for transport and handler outputs.
    reversibility: high
    evidence_needed: Contract, transport and audited-handler regressions plus full suite.
  - action: search
    setup_cost: medium
    execution_cost: medium
    verification_cost: medium
    rework_risk: medium
    context_cost: medium
    expected_benefit: Low; the coercion is directly observable in the local contract.
    reversibility: high
    evidence_needed: External facts would not alter JSON round-trip behavior.
  - action: stop
    setup_cost: none
    execution_cost: none
    verification_cost: none
    rework_risk: high
    context_cost: low
    expected_benefit: Keep a known identity and audit gap.
    reversibility: high
    evidence_needed: Acceptance would need to allow coercive JSON keys.

search_gap:
  uncertainty: Whether a caller intentionally depends on integer keys in core mappings.
  consequence: Medium; strict rejection may expose an undocumented caller, but coercion is already lossy.
  expected_error_reduction: Low from external research.
  search_cost: Medium.
  marginal_value: Low.
  stop_reason: ApplicationEvent already rejects non-string mapping keys, establishing the compatible local rule.

selected_action: continue
confidence: high
next_checkpoint: Verify strict key rejection across core, transport and ActionGate, then publish the regression-backed change.
previous_action: audit permission and audit transition invariants
decision_delta: broadened the fix from permission-only behavior to the shared JSON contract after direct reproduction
verification_signal: Non-string mapping keys must be rejected before serialization, and invalid handler output must be audited as failed.

---

objective: Maintain XIO as signal, transport and input-contract infrastructure for LUCIDA/MULTI without owning rendering, learning or host actions.
acceptance_criteria: Explicit selection identity must be preserved or rejected; omitted identity may be generated, but an invalid supplied value must not be silently replaced.
current_state: JSON coercion is fixed and published. SourceAdapterRegistry.select_candidate uses selection_id or uuid4(), so an explicitly empty selection_id is silently replaced.
verified_evidence: A source registry selection call with selection_id="" returns a valid selection with a newly generated id instead of raising.
assumptions: Empty selection_id is invalid under AdapterSelection and should have the same fail-closed behavior at the factory boundary.
strongest_failure_mode: A caller loses correlation with the selection it requested and cannot reliably reconcile audit or retry records.
highest_consequence_error: A retry or handoff keyed by the caller's empty identifier can be treated as a different selection, weakening idempotency and audit traceability.

options:
  - action: continue
    setup_cost: low
    execution_cost: low
    verification_cost: low
    rework_risk: low
    context_cost: low
    expected_benefit: Reject explicit empty IDs while retaining generated IDs for omitted values.
    reversibility: high
    evidence_needed: Focused selection factory regression and full suite.
  - action: stop
    setup_cost: none
    execution_cost: none
    verification_cost: none
    rework_risk: medium
    context_cost: low
    expected_benefit: Preserve compatibility at the cost of silent identity drift.
    reversibility: high
    evidence_needed: An explicit contract allowing empty IDs, which is absent.

search_gap:
  uncertainty: Whether any caller intentionally passes an empty selection_id to request generation.
  consequence: Low to medium; callers should use None for omission, while strict rejection exposes misuse early.
  expected_error_reduction: Low from external research.
  search_cost: Medium.
  marginal_value: Low.
  stop_reason: AdapterSelection already rejects empty IDs and the factory should not bypass that invariant.

selected_action: continue
confidence: high
next_checkpoint: Validate selection_id only when supplied, add regression, then publish if the full suite remains green.
previous_action: audit explicit selection identity boundary
decision_delta: change from observed silent generation to fail-closed factory input handling
verification_signal: selection_id="" must raise InvalidSourceAdapterError while selection_id=None still generates an ID.
verification_note: The first focused run exposed a pre-existing NameError on the valid None path because uuid4 was not imported; the import is part of this bounded correction.
