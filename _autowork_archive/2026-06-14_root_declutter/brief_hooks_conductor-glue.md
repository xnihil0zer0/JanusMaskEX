---
interfaces: "run_until_terminal(session_id, seams, max_steps) -> {steps: list, final_step}; advance_with_gates(session_id, db, run_gates, advance, build_evidence) -> {advanced: bool, blocked_by}; get_task(session_row: dict) -> {phase, target, prior_findings, parked_package}"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

Conductor runtime glue: bounded loop, gated-advance, and per-worker get_task assembler

# Scope

Build three NEW whole-file pure-glue modules under ngv2/ that tie the five already-committed conductor primitives into an autonomous-loop substrate, each over INJECTED SEAMS so they are deterministic and oracle-testable with no subprocess/network/model call: (1) ngv2/conductor_loop.py exposing run_until_terminal(session_id, seams, max_steps) that repeatedly calls hunt_conductor.run_conductor_step(session_id, seams) until the returned step is in {done, parked, blocked} or max_steps is hit, returning {steps: list, final_step}; (2) ngv2/gated_advance.py exposing advance_with_gates(session_id, db, run_gates, advance, build_evidence) that computes the pending (from_phase, to_phase) transition from the session, builds evidence via build_evidence, calls run_gates(from_phase, to_phase, evidence), and advances ONLY when the gate result advance is True (returning {advanced: True, blocked_by: None}), otherwise returns {advanced: False, blocked_by: <list>} and does NOT call advance; (3) ngv2/session_get_task.py exposing get_task(session_row: dict) -> {phase, target, prior_findings, parked_package} as a pure assembler from a session row, fail-closed (raise/return error sentinel) on missing keys. Each module is a single file with a paired test_authoring sibling whose mutation_target is that module so the pipeline authors the RED oracle, with at least two edge cases (e.g. loop hitting max_steps without terminal; gate result advance False never touching advance; get_task on a row missing target/prior_findings).

# Non-Goals

Do not implement the seam assembler (build_default_seams) or any worker stage here. Do not call run_conductor_step, run_gates, advance, or build_evidence as real implementations — they are injected callables in these signatures and the oracles stub them. Do not edit any existing committed module in place (session_api.py, session_gate.py, or the five landed primitives). Do not remove or weaken any acceptance gate, auto-submit to huntr, contact any external service, or touch irreducible-trust files. No real LLM call, network, or subprocess may run inside any oracle; this is integration glue and the gated_advance leaf composes existing seams.

# Inputs

Reads (does not modify) the signatures of already-committed primitives: ngv2/hunt_conductor.py run_conductor_step(session_id, seams: dict) -> {step, ...}; ngv2/gate_executor.py run_gates(from_phase, to_phase, evidence) -> {advance, blocked_by, results}; ngv2/transition_planner.py plan_next_action(session_state: dict) -> {action, target_phase, reason}. Composes ngv2/session_db.py get_session(session_id) and ngv2/session_api.py advance(session_id, approval_decision) only as INJECTED callables passed through the signatures (not imported and called directly in these modules). The session_row shape passed to get_task is the dict produced by session_db.get_session.

# Deliverables

ngv2/conductor_loop.py exposing run_until_terminal(session_id, seams, max_steps) -> {steps: list, final_step}, where seams['run_conductor_step'] (or the conductor step callable in seams) is invoked each iteration and termination is step in {done, parked, blocked}. ngv2/gated_advance.py exposing advance_with_gates(session_id, db, run_gates, advance, build_evidence) -> {advanced: bool, blocked_by}; advances only when run_gates returns advance True, else blocked and advance is never called. ngv2/session_get_task.py exposing get_task(session_row: dict) -> {phase, target, prior_findings, parked_package}, fail-closed on missing keys. Each has a test_authoring sibling with mutation_target set to that file and a verification_command naming the authored oracle.
