---
working_dir: "/home/xnihil0zer0/NobleGreedv2"
required_task_ids:
  - p11-gate-table-typed-terminals
  - p11-transition-planner-spawn-middle
  - p11-build-evidence-structural-keys
  - p11-gate-executor-oracle
interfaces: "Trust-spine ROOT. Today only 2 of 10 consecutive PHASE_ORDER transitions are gated; the other 8 auto-advance on ABSENT evidence (fail-OPEN), because `run_gates` returns `advance: (deduped == [])` and `_TRANSITION_GATES.get(t, ())` is empty for un-gated transitions. This brief: (1) `ngv2/gate_executor.py` — register a gate for EVERY consecutive PHASE_ORDER transition so `run_gates(from,to,{})` is fail-CLOSED (advance:False) on empty evidence, plus a TYPED-TERMINAL enum and a `no_template:CWE-<n>` router; (2) `ngv2/transition_planner.py` — `plan_next_action` spawns the FULL agent-phase set (triage/verify/novelty/report), not only hunt/poc/detonate; (3) `ngv2/conductor_seams.py` — `build_evidence` emits the LEAVING-phase structural completion keys the new gates require, so the LIVE conductor still advances and does NOT deadlock (mandatory deadlock-avoidance: a fail-closed gate with no runtime evidence supply would wedge every live hunt). DEADLOCK-AVOIDANCE RULE: each structural gate checks the LEAVING phase's OWN already-produced completion evidence, NEVER the NEXT phase's not-yet-produced output. The existing `poc->detonate` (poc_authenticity) and `detonate->novelty` (3 gates) entries are CORRECT and preserved verbatim."
---

# Title
P1.1 — gate EVERY PHASE_ORDER transition (fail-closed) + typed terminals + deadlock-safe evidence supply

# Scope
EDIT three EXISTING files in the NGv2 package at `/home/xnihil0zer0/NobleGreedv2` (READ each
first): `ngv2/gate_executor.py`, `ngv2/transition_planner.py`, `ngv2/conductor_seams.py`. Pure,
deterministic decision/translation functions (`state_machine` meta_task_type) — no I/O, no clock, no
randomness, no NEW module-level side-effects.

Background — the live shapes (RE-CONFIRM by reading):
- `ngv2/transition_planner.py:9`
  `PHASE_ORDER = ('source','hunt','triage','verify','poc','detonate','novelty','report','awaiting_submission','submitted','done')`
  (11 phases → 10 consecutive transitions).
- `ngv2/gate_executor.py:24` `_TRANSITION_GATES` has ONLY `('poc','detonate')` and
  `('detonate','novelty')`. `run_gates(from,to,ev)` returns
  `{'advance': bool, 'blocked_by': list, 'results': dict}`; `advance` is True when `deduped == []`,
  so any transition NOT in the table advances unconditionally on empty evidence (the fail-OPEN bug).
  `_GateSpec = (name, required_keys, caller)`; a missing required key → `'<name>:missing_evidence'`
  in `blocked_by`, gate NOT called, advance False, NO KeyError.
- `ngv2/transition_planner.py:40` `plan_next_action` only emits `spawn_stage` for `hunt`/`poc`/
  `detonate` when the artifact count is 0; for `triage`/`verify`/`novelty`/`report` it jumps straight
  to `apply_gates`.
- `ngv2/conductor_seams.py` `build_evidence(state)` (≈:86-117) TRANSLATES carried-forward payloads
  into the gate evidence vocab (`poc_source`, `target_import_names`, `target_source`,
  `expected_signature`, `sink_name`, `call_sites`, `detonation_report`). It does NOT yet emit the
  structural completion keys the new gates need.
- Worker modules EXIST for every agent phase (`ngv2/workers/{hunt,triage,verify,poc,detonate,novelty,report}.py`).

## Task 1 — `p11-gate-table-typed-terminals` (gate_executor.py + its existing oracle)
In `ngv2/gate_executor.py`:
1. Add a TYPED-TERMINAL enum (a `class` or frozen string-constant container) naming, at minimum:
   `EMPTY_HUNT`, `NO_TEMPLATE`, `REFUTED`, `MISSING_EVIDENCE`, `SERVICE_NO_BIND`, plus a value per
   structural-gate refusal (`NO_SOURCE`, `NO_FINDINGS`, `NO_TRIAGE`, `NO_VERIFY`, `NO_NOVELTY`,
   `NO_REPORT`, `NO_APPROVAL`, `NO_SUBMISSION`). It MUST be a NEW top-level symbol R-ANCHORED on an
   EXISTING top-level symbol (anchor on `_TRANSITION_GATES` or `run_gates`; extras limited to
   import/assign/def/class; no name collision) so the `__JANUSMASK_PATCHES__` apply does not fail
   with an opaque `auto_commit_failed`.
2. Add a small pure helper `no_template_terminal(cwe)` returning the typed `no_template:CWE-<n>`
   string — so a caller routes to a typed terminal instead of `poc_writer._resolve_template`'s
   `KeyError` collapsing to a bare `blocked`.
3. Complete `_TRANSITION_GATES` so EVERY consecutive `PHASE_ORDER` transition has a gate entry.
   PRESERVE the two existing entries VERBATIM. For each remaining consecutive transition add a
   STRUCTURAL gate whose `required_keys` name the LEAVING phase's OWN completion evidence and whose
   gate fn returns `{'may_confirm': bool, 'terminal': <enum value>}` truthy iff that evidence is
   present/non-empty:
   - `('source','hunt')`     → requires `source_ready`.
   - `('hunt','triage')`     → requires `findings` (non-empty).
   - `('triage','verify')`   → requires `triage_result`.
   - `('verify','poc')`      → requires `verify_result` (NOT `poc_source` — the PoC is written
                                DURING the poc phase; gating it here re-introduces the old deadlock).
   - `('novelty','report')`  → requires `novelty_result`.
   - `('report','awaiting_submission')` → requires `report_artifact`.
   - `('awaiting_submission','submitted')` → requires `approval`.
   - `('submitted','done')`  → requires `submission_result`.
   Use the SAME `_GateSpec` shape and the SAME missing-evidence fail-closed path already in
   `run_gates`. Do NOT change `run_gates`'s signature or its `advance == (deduped == [])` rule.
ALSO update `tests/ngv2/test_gate_executor_wired.py` (in this task's files_touched): the three
assertions encoding the OLD fail-OPEN behavior — `test_source_hunt_no_gate_advances`,
`test_verify_poc_is_ungated_and_advances`, `test_unknown_transition_advances_no_gate` — must be
revised to the NEW contract (a CONSECUTIVE structural transition with EMPTY evidence now returns
`advance:False`; a genuinely NON-consecutive/skip transition stays ungated and advances). Keep every
OTHER existing assertion in that file GREEN (the `poc->detonate` and `detonate->novelty` cases are
unchanged).

## Task 2 — `p11-transition-planner-spawn-middle` (transition_planner.py)
EDIT `plan_next_action` so it emits `spawn_stage` for the FULL agent-phase set
(`hunt`/`triage`/`verify`/`poc`/`detonate`/`novelty`/`report`) when the phase's completion artifact
is absent, not only `hunt`/`poc`/`detonate`. Preserve the existing precedence (`blocked` first, then
`done`, then `awaiting_submission`) and the byte-stable determinism. When the artifact IS present,
fall through to `apply_gates` with `target_phase = _next_phase(phase)` exactly as today. Do NOT change
`PHASE_ORDER`, `_next_phase`, or the result-dict shape. Keep all existing
`test_transition_planner_wired.py` assertions GREEN.

## Task 3 — `p11-build-evidence-structural-keys` (conductor_seams.py)
EDIT `build_evidence(state)` in `ngv2/conductor_seams.py` to ALSO emit the LEAVING-phase structural
completion keys the new gates require, derived from the session `state` already threaded forward —
so the LIVE conductor advances through the gated structural transitions instead of deadlocking. Add,
when derivable and not already present: `source_ready` (truthy when a source/hunt artifact or
`prior_findings` exists), `findings` (the `prior_findings` list / its count), `triage_result`,
`verify_result`, `novelty_result`, `report_artifact`, `submission_result`, and `approval` (from
`state.get('approval')`). Derive each from the existing `state` keys / `artifacts` (mirror the
existing `prior_findings` / `parked_package` / `evidence` threading pattern). Do NOT change
`build_default_seams`'s signature, the seam dict keys, the `persist`/`advance` closures, or
`_spawn_stage`. Keep the function PURE (no new I/O beyond the existing target-source read). Keep all
existing `test_conductor_seams_wired.py` assertions GREEN.

## Inputs
- `ngv2/gate_executor.py` — the table + executor (Task 1).
- `ngv2/transition_planner.py` — `PHASE_ORDER` + `plan_next_action` (Task 2).
- `ngv2/conductor_seams.py` — `build_evidence` (Task 3).
- `ngv2/hunt_conductor.py::run_conductor_step` (READ-ONLY) — the live consumer calling
  `run_gates(state['phase'], target_phase, evidence)`; confirms the 3-arg signature and the
  build_evidence→run_gates data flow.
- `ngv2/poc_writer.py::_resolve_template` / `get_template` (READ-ONLY) — the `KeyError` source the
  `no_template` typed terminal addresses.
- Existing oracles `tests/ngv2/test_gate_executor_wired.py`,
  `tests/ngv2/test_transition_planner_wired.py`, `tests/ngv2/test_hunt_conductor_wired.py`,
  `tests/test_conductor_seams_wired.py` — the regression surface.

# Non-Goals
Integration is out of scope for the implementation tasks (the literal word `integration` MUST appear
here AND in each non-`test_*` task's non_goals to excuse the integration-test requirement). Do NOT
touch `ngv2/hunt_conductor.py`, `ngv2/conductor_loop.py`, `ngv2/run_hunt.py`, `ngv2/poc_writer.py`,
or any phase worker — the full end-to-end live run and the per-CWE evidence channels are FOLLOW-ON
contracts (P1.2 / P1.3 / P2.1). Do NOT change `run_gates`'s signature, the `_GateSpec` shape, or the
`advance == (deduped == [])` rule. Do NOT modify `PHASE_ORDER`. Do NOT add network, subprocess,
clock, or randomness. Do NOT change the existing `poc->detonate` / `detonate->novelty` gate entries.

# Deliverables
- `ngv2/gate_executor.py`: a typed-terminal enum (new top-level symbol, R-anchored); a
  `no_template`-routing helper; `_TRANSITION_GATES` with a gate for EVERY consecutive PHASE_ORDER
  transition; structural gates fail-closed on absent evidence; the two pre-existing entries intact.
- `ngv2/transition_planner.py`: `plan_next_action` spawns the full agent-phase set on a missing
  artifact.
- `ngv2/conductor_seams.py`: `build_evidence` emits the structural completion keys (deadlock-safe).
- `tests/ngv2/test_gate_executor_wired.py`: the three obsolete fail-OPEN assertions revised to the
  new fail-closed contract; all other assertions still GREEN.
- A NEW pipeline-authored RED oracle `tests/ngv2/test_p11_gate_every_transition_typed_terminals.py`
  (Task 4, `test_authoring`) — RED now, GREEN after.

# Required plan shape
- EXACTLY four tasks with these EXACT task_ids (pin via `required_task_ids`):
  - `p11-gate-table-typed-terminals` — meta_task_type: `state_machine`;
    files_touched: `ngv2/gate_executor.py`, `tests/ngv2/test_gate_executor_wired.py`;
    its `verification_command` MUST be the NEW oracle file
    `python -m pytest tests/ngv2/test_p11_gate_every_transition_typed_terminals.py -q`
    (RED-PAIR so `_drop_redundant_precommitted_oracles`'s red-pair guard KEEPS the oracle —
    `test_gate_executor_wired.py` already imports `ngv2.gate_executor`, which would otherwise drop it);
    non_goals MUST contain the literal word `integration`.
  - `p11-transition-planner-spawn-middle` — meta_task_type: `state_machine`;
    files_touched: `ngv2/transition_planner.py`; non_goals MUST contain `integration`.
  - `p11-build-evidence-structural-keys` — meta_task_type: `io_adapter`;
    files_touched: `ngv2/conductor_seams.py`; non_goals MUST contain `integration`.
  - `p11-gate-executor-oracle` — meta_task_type: `test_authoring`;
    files_touched: `tests/ngv2/test_p11_gate_every_transition_typed_terminals.py`;
    mutation_target: `ngv2.gate_executor`.
- The three implementation tasks have DISJOINT files_touched so they parallelize.
  `p11-gate-table-typed-terminals` depends on `p11-gate-executor-oracle` (RED-pair: oracle first,
  impl makes it GREEN).
- EVERY non-`test_*` task's `non_goals` MUST contain the literal word `integration` (the
  integration-test excuse — a prior malformed draft of this brief OMITTED it, causing a deterministic
  `missing_integration_test` PlanViolation on the conductor_seams task; do NOT repeat that).
- verification_command (BARE, selects ≥1 real test, never pytest exit 5; no `cd `):
  `python -m pytest tests/ngv2/test_p11_gate_every_transition_typed_terminals.py -q`
- Wire-up: the new gates/enum/keys are reachable from the live conductor path
  (`run_hunt` → `conductor_seams.build_default_seams` wires `gate_executor.run_gates` as the
  `run_gates` seam and `build_evidence` as the `build_evidence` seam consumed by
  `hunt_conductor.run_conductor_step`); the oracle asserts the symbols import from the LIVE modules.

## The pre-committed oracle (Task 4) MUST assert (RED-now → GREEN-after, non-vacuous):
1. Import `run_gates` and the typed-terminal enum from the LIVE `ngv2.gate_executor`, and
   `PHASE_ORDER` from `ngv2.transition_planner` (wiring/reachability proof).
2. X4 PROGRAM ORACLE — enumerate every consecutive pair in `PHASE_ORDER`; for EACH:
   (a) a gate entry exists in `_TRANSITION_GATES`; (b) `run_gates(frm, to, {})` returns
   `advance: False` (fail-closed on empty evidence). RED today: 8 of the 10 advance True.
3. An un-templatable CWE routes to a typed `no_template:CWE-<n>` value (RED: KeyError → opaque
   blocked).
4. NEGATIVE CONTROL — a transition WITH valid evidence still advances (no over-blocking):
   `('poc','detonate')` with a real-target PoC → `advance: True`, AND a structural transition
   (e.g. `('hunt','triage')`) with its completion evidence present → `advance: True`.
5. Determinism: identical inputs yield byte-identical `json.dumps(..., sort_keys=True)` output.
- regression_tests >= 2 (the X4 enumeration + the negative control are distinct, non-vacuous tests).
