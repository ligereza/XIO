run_id: xio-source-registry-20260901
objective: Extend XIO source registry into a reliable declarative boundary for LUCIDA/MULTI and future application signal adapters.
scope: XIO_LAYER only; preserve unrelated worktree changes.
core_acceptance_criteria:
  - deterministic registry declarations and candidate queries
  - route planning metadata with explicit no-match
  - no adapter execution, sockets, discovery, credentials or host state
  - focused tests, ASCII technical artifacts, pushed commits
authorized_extensions:
  - bounded declarative planning/selection metadata
status: complete
superseded_by: xio-lucida-input-contract-20260902
superseded_reason: The LIMEN extraction is historical and is no longer an active XIO objective.

completed:
  - item: SourceAdapterRegistry registration, routing and declaration snapshots
    evidence: commit 173e96e; full suite previously passed with 63 tests
  - item: Deterministic candidate queries by event type and capability set
    evidence: commit bd74b61; full suite previously passed with 70 tests
  - item: Declarative route planning with explicit matched/no_match status
    evidence: commit c95fab2 pushed to origin/codex/xio-transport; full suite passes 73 tests
  - item: Caller-selected adapter handoff with privacy projection and audit
    evidence: commit dc374bf; full suite passes 79 tests
  - item: Replayable local JSONL source connected to selected handoff and LUCIDA/MULTI fixture
    evidence: uncommitted milestone; full suite passes 83 tests; fixture covers dedupe, ordering, redaction, bridge and replay
  - item: Restart-safe JSONL audit ledger integrated into the local-source fixture
    evidence: uncommitted milestone; full suite passes 86 tests; persistence tests cover restart, chain continuation, tamper rejection and no partial write
  - item: Persistent audit milestone committed and pushed
    evidence: commit 5d1ad72 pushed to origin/codex/xio-transport; full suite passes 86 tests
  - item: Explicit delivery receipts and audit outcomes committed and pushed
    evidence: commit 5a8bb4b pushed to origin/codex/xio-transport; full suite passes 87 tests
  - item: Delivery permission gate with revocation protection
    evidence: uncommitted milestone; full suite passes 88 tests; missing/revoked permission prevents transport.send and is audited
  - item: Delivery permission gate committed and pushed
    evidence: commit aefc051 pushed to origin/codex/xio-transport; full suite passes 88 tests
  - item: Idempotency conflicts separated as terminal delivery outcome
    evidence: uncommitted milestone; full suite passes 89 tests; conflicting message id yields conflict and no extra delivery
  - item: Idempotency conflict classification committed and pushed
    evidence: commit d36cbdb pushed to origin/codex/xio-transport; full suite passes 89 tests
  - item: Replay-derived handoff identities made deterministic
    evidence: uncommitted milestone; full suite passes 89 tests; repeated fixture preparation yields identical handoff and event fingerprints
  - item: Deterministic replay identity committed and pushed
    evidence: commit 4e03383 pushed to origin/codex/xio-transport; full suite passes 89 tests
  - item: AdapterSelection restart reconstruction contract
    evidence: uncommitted milestone; full suite passes 90 tests; strict round-trip and extra-field rejection tests pass
  - item: AdapterSelection reconstruction committed and pushed
    evidence: commit f725626 pushed to origin/codex/xio-transport; full suite passes 90 tests
  - item: Prepared AdapterHandoff strict reconstruction and fixture replay
    evidence: uncommitted extension; full suite passes 90 tests; restored handoffs validate bridge/event equality and require caller identity
  - item: Prepared handoff reconstruction committed and pushed
    evidence: commit a3e2999 pushed to origin/codex/xio-transport; full suite passes 90 tests
  - item: Restored handoff schema type validation
    evidence: uncommitted extension; full suite passes 90 tests; malformed message ids and sequences are rejected by AdapterHandoffError
  - item: Restored handoff schema validation committed and pushed
    evidence: commit d81e1f1 pushed to origin/codex/xio-transport; full suite passes 90 tests
  - item: Persistent JsonLineHandoffStore with fixture replay
    evidence: uncommitted extension; full suite passes 93 tests; idempotent append, conflicting ID rejection and caller-explicit replay pass
  - item: Prepared handoff persistence committed and pushed
    evidence: commit e6641ac pushed to origin/codex/xio-transport; full suite passes 93 tests
  - item: Tamper/conflict/idempotency hardening selected for next extension
    evidence: current store has logical dedupe and bridge validation but no persisted record hash envelope; extension in progress
  - item: Versioned tamper-evident handoff store
    evidence: uncommitted milestone; full suite passes 95 tests; tamper, reorder, same-id conflict and duplicate append tests pass offline
  - item: Tamper-evident handoff store committed and pushed
    evidence: commit 59de577 pushed to origin/codex/xio-transport; full suite passes 95 tests
  - item: Shared TransportMessage restoration contract selected
    evidence: handoff.py currently contains a private transport parser; extension will centralize strict wire restoration without changing schema
  - item: Shared TransportMessage strict restoration contract
    evidence: uncommitted milestone; full suite passes 96 tests; transport round-trip and malformed-field tests pass, handoff restoration reuses core parser
  - item: Shared transport wire restoration committed and pushed
    evidence: commit a658ef5 pushed to origin/codex/xio-transport; full suite passes 96 tests
  - item: In-process handoff store concurrency serialization
    evidence: commit 09450b3 pushed to origin/codex/xio-transport; full suite passes 97 tests; concurrent same-content appends yield one write and idempotent duplicates
  - item: Cross-process handoff store file locking
    evidence: commit 5ae6d43 pushed to origin/codex/xio-transport; full suite passes 98 tests; four separate Python processes share a sidecar lock and preserve one idempotent record
  - item: Shared cross-process locking for persistent audit ledger
    evidence: commit 374aafa pushed to origin/codex/xio-transport; full suite passes 99 tests; four separate Python processes reload under the sidecar lock and preserve one verified audit hash chain
  - item: Durable concurrent event JSONL logs
    evidence: commit cb25f2c pushed to origin/codex/xio-transport; full suite passes 101 tests; EventLog assigns unique sequences and ApplicationEventLog deduplicates identical IDs across four separate processes
  - item: Deterministic checkpoint version conflicts
    evidence: commit 36c5675 pushed to origin/codex/xio-transport; full suite passes 102 tests; identical stream/version saves are idempotent and differing state is rejected under directory lock
  - item: Semantic checkpoint validation before recovery
    evidence: commit b58ccfa pushed to origin/codex/xio-transport; full suite passes 103 tests; an internally hash-valid but event-inconsistent checkpoint is reported and bypassed in favor of full replay
  - item: Strict checkpoint restoration schema
    evidence: commit 1f2eb1d pushed to origin/codex/xio-transport; full suite passes 104 tests; exact fields, scalar types and state hash are required for checkpoint reconstruction
  - item: Strict Event and ApplicationEvent restoration schemas
    evidence: commit 04328ae pushed to origin/codex/xio-transport; full suite passes 106 tests; event and application-event round-trips remain valid while missing, extra and wrong-type fields are rejected
  - item: Strict AuditEntry restoration schema
    evidence: commit 02a4f33 pushed to origin/codex/xio-transport; full suite passes 107 tests; audit round-trip remains valid while non-text actors, non-mapping details and wrong hash types are rejected
  - item: Windows cross-process lock race regression fix
    evidence: commit 02a4f33 pushed to origin/codex/xio-transport; handoff and audit four-process tests pass in three repeated rounds after lock initialization ordering change
  - item: Strict ConnectionStatus restoration schema
    evidence: commit 3944a0b pushed to origin/codex/xio-transport; full suite passes 108 tests; endpoint fields, counters, latency, sequence and state types are validated without coercion
  - item: Direct transport and connectivity constructor invariants
    evidence: commit 9f2f75a pushed to origin/codex/xio-transport; full suite passes 109 tests; Endpoint, TransportMessage and ConnectionStatus reject coercible invalid types consistently with restoration parsers
  - item: Direct event and snapshot temporal invariants
    evidence: commit 295d75d pushed to origin/codex/xio-transport; full suite passes 111 tests; Event, EventRecord, Snapshot, Checkpoint and ApplicationEvent reject boolean schema/version/sequence values and invalid provenance mappings
  - item: ExplicitAction confirmation type guard
    evidence: commit bbadc5e pushed to origin/codex/xio-transport; full suite passes 112 tests; truthy non-boolean confirmations and non-mapping parameters are rejected before ActionGate
  - item: Atomic permission check and action execution
    evidence: commit 27ffddd pushed to origin/codex/xio-transport; full suite passes 113 tests, focused race test passes in ten repeated runs, and revocation cannot interleave between authorization and handler invocation
  - item: Strict session wire contracts
    evidence: commit c49b922 pushed to origin/codex/xio-transport; full suite passes 116 tests; strict peer/request/ack/signal/delivery-ack constructors and parsers reject coercive wire values
  - item: Session manager concurrency serialization
    evidence: commit 3b2941c pushed to origin/codex/xio-transport; full suite passes 117 tests, repeated concurrent fan-out test passes ten times, and manager transitions are serialized
  - item: Session JSON safety at the boundary
    evidence: commit d3a8ee3 pushed to origin/codex/xio-transport; full suite passes 118 tests; invalid bytes, NaN, arbitrary objects and non-JSON envelopes are rejected before fingerprinting
  - item: Strict DeliveryReceipt constructor invariants
    evidence: commit 6da46f6 pushed to origin/codex/xio-transport; full suite passes 118 tests; invalid receipt flags, sequences and latency are rejected before status mapping
  - item: Strict TransportPolicy constructor invariants
    evidence: commit b94eeed pushed to origin/codex/xio-transport; full suite passes 118 tests; ambiguous allow_network and malformed policy collections are rejected at construction
  - item: Explicit action result output validation
    evidence: commit 595a13d pushed to origin/codex/xio-transport; full suite passes 119 tests; invalid handler output and non-JSON result values become failed/audited or rejected outcomes
  - item: Explicit peer-session recovery checkpoint
    evidence: commit d533ab0 pushed to origin/codex/xio-transport; full suite passes 122 tests; JSON checkpoint round-trip preserves fingerprints/revocations and restore requires fresh handshake
  - item: Reauthorization invalidates stale peer session state
    evidence: commit 8860500 pushed to origin/codex/xio-transport; full suite passes 123 tests; replacing a peer refreshes endpoint/session, clears capabilities and invalidates pending handshakes while retaining history
  - item: Explicit PeerSessionManager API input validation
    evidence: commit a41e593 pushed to origin/codex/xio-transport; full suite passes 124 tests; malformed public record types and peer ids are rejected before state or transport mutation
  - item: Complete public session exports
    evidence: commit 1d5e7af pushed to origin/codex/xio-transport; full suite passes 125 tests; AckStatus is available through core.sessions.__all__ and wildcard import regression passes
  - item: Recovered receiver history coverage
    evidence: commit 161846d pushed to origin/codex/xio-transport; full suite passes 126 tests; restored receiver preserves duplicate, conflict and stale-sequence outcomes after fresh handshake
  - item: Invalid handshake ACK atomicity
    evidence: commit f9b849d pushed to origin/codex/xio-transport; full suite passes 128 tests; invalid responder/session ACK regressions prove a later valid ACK can complete
  - item: Session boundary re-audit
    evidence: no further XIO_LAYER-only defect selected; remaining persistence/session binding choices require a host integration contract
  - item: Persistent event-log input validation
    evidence: commit 1fdf616 pushed to origin/codex/xio-transport; full suite passes 130 tests; wrong-type append tests prove no in-memory or file mutation
  - item: Snapshot-store input validation
    evidence: commit e5a3e47 pushed to origin/codex/xio-transport; full suite passes 131 tests; wrong-type saves prove no in-memory or checkpoint-file mutation
  - item: Recovery input validation
    evidence: commit 7052165 pushed to origin/codex/xio-transport; full suite passes 132 tests; malformed recovery inputs are rejected before replay or checkpoint creation
  - item: Adapter handoff boundary validation
    evidence: commit 59acad8 pushed to origin/codex/xio-transport; full suite passes 134 tests; invalid store append and incoherent handoff constructor regressions pass
  - item: Adapter registry input validation
    evidence: commit 8f7909f pushed to origin/codex/xio-transport; full suite passes 135 tests; invalid ids, plans and records are rejected without adapter calls
  - item: Atomic delivery permission boundary
    evidence: commit d42a096 pushed to origin/codex/xio-transport; full suite passes 136 tests; revocation race regression proves send remains inside the permission lock
  - item: Permission registry input validation
    evidence: commit 48cc1fc pushed to origin/codex/xio-transport; full suite passes 138 tests; invalid permission inputs leave revision and audit unchanged
  - item: Direct AuditEntry invariants
    evidence: commit 58d6ca9 pushed to origin/codex/xio-transport; full suite passes 139 tests; direct and restored audit entries now share scalar and hash validation
  - item: Audit append input validation
    evidence: commit 08c81c0 pushed to origin/codex/xio-transport; full suite passes 140 tests; non-mapping details are rejected without ledger or file mutation
  - item: Delivery result coherence
    evidence: commit db9b91c pushed to origin/codex/xio-transport; full suite passes 141 tests; impossible status/receipt combinations are rejected
  - item: Privacy allowlist input validation
    evidence: commit 682907b pushed to origin/codex/xio-transport; full suite passes 142 tests; ambiguous key collections are rejected before projection
  - item: Selection and projection input validation
    evidence: commit d2554b0 pushed to origin/codex/xio-transport; full suite passes 144 tests; ambiguous capability and projection identity inputs are rejected
  - item: ApplicationEvent JSON safety
    evidence: commit 977fe31 pushed to origin/codex/xio-transport; full suite passes 145 tests; non-finite and unsupported event values are rejected at construction
  - item: ApplicationEvent restore error normalization
    evidence: commit 89a7b31 pushed to origin/codex/xio-transport; full suite passes 146 tests; malformed reversible values use the documented contract error
  - item: Lucida envelope schema type validation
    evidence: commit b386946 pushed to origin/codex/xio-transport; focused bridge suite passes 7 tests and full suite passes 147 tests; boolean and non-integer envelope schema values are rejected before conversion
  - item: Protocol envelope constructor validation
    evidence: commit dc78401 pushed to origin/codex/xio-transport; focused transport suite passes 11 tests and full suite passes 148 tests; OSC and Art-Net direct inputs are rejected before serialization
  - item: Persisted handoff schema type validation
    evidence: commit 9fec525 pushed to origin/codex/xio-transport; focused handoff-store suite passes 9 tests and full suite passes 149 tests; boolean and non-integer store schema values fail at integrity validation
  - item: Proposal constructor boundary validation
    evidence: commit c2b728c pushed to origin/codex/xio-transport; focused core suite passes 26 tests and full suite passes 150 tests; invalid text, mapping and event-id collections are rejected without creating an executable action
  - item: Snapshot stream isolation
    evidence: commit 21f5ceb pushed to origin/codex/xio-transport; focused core suite passes 27 tests and full suite passes 151 tests; foreign records and base snapshots are rejected
  - item: Incremental snapshot prefix protection
    evidence: commit 144b2a4 pushed to origin/codex/xio-transport; focused core suite passes 28 tests and full suite passes 152 tests; records at or before a base snapshot version are rejected
  - item: Narrow LUCIDA input compatibility contract
    evidence: commit eb60c66 pushed to origin/codex/xio-lucida-input-contract; focused input suite passes 5 tests and full suite passes 157 tests; public output is limited to nine metadata fields with bounded redaction summary and explicit replacement replay
  - item: LUCIDA input storage replay validation
    evidence: commit 02c36ed pushed to origin/codex/xio-lucida-input-contract; focused input suite passes 6 tests and full suite passes 158 tests; malformed storage payloads and missing replacement targets fail as contract errors
  - item: LUCIDA input storage schema validation
    evidence: commit 5ff295a pushed to origin/codex/xio-lucida-input-contract; focused input suite passes 6 tests and full suite passes 158 tests; unsupported storage schemas and null replacement metadata are rejected
  - item: LUCIDA input summary size bound
    evidence: commit ff53e88 pushed to origin/codex/xio-lucida-input-contract; focused input suite passes 6 tests and full suite passes 158 tests; data_summary rejects field names over 64 characters while retaining the 16-descriptor cap
  - item: LIMEN serialized contract hardening
    evidence: local commit a5a94ba on codex/limen-xio-adapter; documented root-level discovery passes 12 tests, compileall and diff check pass; Event/EventRecord/Checkpoint reject coercive serialized types and SnapshotProjector rejects foreign streams and stale base versions

current_state:
  files_or_resources: XIO_LAYER/adapters/lucida_input.py, XIO_LAYER/LUCIDA_INPUT.md, XIO_LAYER/tests/fixtures/lucida_input_events.jsonl, XIO_LAYER/tests/test_lucida_input.py, LIMEN/core/contracts/models.py, LIMEN/core/snapshots/projector.py, LIMEN/tests/test_core.py, LIMEN/README.md
  tests_and_checks: XIO focused input tests pass 6 and full suite 158; LIMEN suite passes 12 tests with the documented discovery command from root, compileall, ASCII and diff checks pass; LIMEN local HEAD is a5a94ba; unrelated root changes preserved
  assumptions: route planning and selection remain explicit caller responsibilities; prepared messages are not delivered automatically
  open_questions: none blocking; further work would require host-specific integration or multi-process locking
  blockers: none
  research_refs: none required; extension is local and deterministic
  delegation_refs: source thread 01a03125-8e25-7d51-b81a-8ee0eddd683c requested next milestone
  last_critique: serialized LIMEN contracts must reject coercion and cross-stream snapshot projection before replay or recovery
  estimated_remaining_effort: no additional in-scope change is justified without a new reproducible contract defect or an explicit host integration specification
  next_action: no further action; this autonomous state is superseded by xio-lucida-input-contract-20260902
next_checkpoint_trigger: before any host-specific integration, external mutation, or new XIO_LAYER change

forecasts:
  - id: F-001
    horizon: H1
    event: host integration will require a concrete writer, identity policy or persistence contract not defined by XIO_LAYER
    likelihood: medium
    impact: medium
    trigger: request to connect LUCIDA/MULTI, MAK or a real device
    prevention: keep adapters injected and document the missing host contract before implementation
    prevention_cost: low
    expected_avoided_cost: medium
    confidence: high
    validation_signal: an explicit integration interface and executable host fixture
    status: tested
