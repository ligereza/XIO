objective:
  Reduce the XIO repository to exactly three purposeful branches, preserve all relevant Router/RD/FOH work, delete obsolete open branches, and leave MAK synchronized.
acceptance_criteria:
  Three explicitly named target branches remain; relevant commits are integrated into the correct targets; branch tips and MAK are verified; no work is deleted without evidence.
current_state:
  origin/integration/xio-field-20260911 is the tested monolithic XIO line and contains main plus the Router/RD/FOH work. MAK is clean and at ea02d4c. Six codex branches contain additional unique LIMEN/XIO_LAYER or semantic-light-field work not in integration.
verified_evidence:
  Branch inventory shows main, integration, and six codex branches. origin/main is an ancestor of origin/integration. The codex branches have unique commits, including 97 on xio-lucida-input-contract and 76 on xio-transport.
assumptions:
  The requested three branches correspond to Router, RD, and FOH, but exact branch names and whether LIMEN/XIO_LAYER belongs to any of them were not specified.
strongest_failure_mode:
  Deleting codex branches because they look exploratory could discard unreconciled transport, import, or semantic-light-field work.
highest_consequence_error:
  Permanently removing a branch before its unique commits are either integrated or explicitly archived.
options:
  - action: continue
    setup_cost: low
    execution_cost: high
    verification_cost: high
    rework_risk: high
    context_cost: medium
    expected_benefit: immediate three-branch cleanup
    reversibility: low after remote deletion
    evidence_needed: exact target branch names and ownership of unique codex work
  - action: ask_user
    setup_cost: low
    execution_cost: paused
    verification_cost: low
    rework_risk: low
    context_cost: low
    expected_benefit: prevents irreversible misclassification
    reversibility: high
    evidence_needed: user confirms Router/RD/FOH branch names and treatment of LIMEN/XIO_LAYER
search_gap:
  uncertainty: target branch names and disposition of unique non-RD/FOH work
  consequence: high
  expected_error_reduction: high
  search_cost: low; branch graph and diffs already inspected
  marginal_value: low without user decision
  stop_reason: further inspection cannot determine intended ownership
selected_action: ask_user
confidence: high
next_checkpoint: after user confirms the three branch names and whether unique LIMEN/XIO_LAYER work should be archived or discarded
previous_action: inspect branch graph and unique diffs
decision_delta: changed from planned deletion to clarification because six branches contain unreconciled unique work
verification_signal: branch names and retention policy confirmed by user
