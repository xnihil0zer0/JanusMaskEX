---
interfaces: "creates the NEW standalone module ngv2/hunt_conductor.py -- the deterministic CONDUCTOR STEP for the NobleGreed bug-hunt FSM, exposing run_conductor_step(session_id, seams: dict) -> dict. It performs ONE step: load the session state, consult the injected transition planner for the next action, and dispatch on that action over INJECTED SEAMS (callables passed in via `seams`) -- it spawns no real process, opens no DB, imports no heavy module, and has zero hidden side effects, so it is pure/oracle-testable. The committed oracle tests/ngv2/test_hunt_conductor_wired.py is the authoritative acceptance contract and the *_wired reachability proof (importing run_conductor_step from the live ngv2.hunt_conductor module is the wiring contract)."
dependencies: []
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/hunt_conductor.py -- NEW deterministic CONDUCTOR STEP that ties the NobleGreed bug-hunt automation pieces together over INJECTED SEAMS. An audit found the bug-hunt FSM (linear phases source -> hunt -> triage -> verify -> poc -> detonate -> novelty -> report -> awaiting_submission -> submitted -> done) is deterministic but NOT autonomous: no conductor polls the session state and chains the stages, so today an operator or agent launches the drivers and moves artifacts by hand. This module is the missing deterministic conductor: it performs exactly ONE step of the loop. It loads the current session state via an injected seam, asks the injected transition planner (`ngv2/transition_planner.py::plan_next_action`, passed in as the `plan` seam) what to do next, and then DISPATCHES on the returned action -- spawning the agent worker for the current phase and harvesting/persisting its artifacts, or assembling evidence and applying the gate stack (advancing only if the gates pass), or parking for human approval, or advancing, or reporting blocked/done. CRITICAL: every effectful dependency (state load, planner, command map, spawn, harvest, persist, evidence build, gate run, advance) is a CALLABLE PASSED IN via the `seams` dict -- the module never spawns a real subprocess, never touches a real DB, never imports a heavy module. That makes it pure, total, deterministic, and oracle-testable with stub seams that record their invocations. A thin outer loop (mentioned but explicitly NOT built here) repeatedly calls run_conductor_step until the returned step is in {"done","parked","blocked"}. The conductor consumes the planner's action to drive the next deterministic move; it is the live conductor entry point for the NobleGreed hunt FSM.

# Scope

CREATE the NEW single-file module `ngv2/hunt_conductor.py` (NGv2 external-target task -- `working_dir` = /home/xnihil0zer0/NobleGreedv2). The module is coordination logic over INJECTED SEAMS and stdlib-only (`typing` only is needed): NO network, NO disk I/O, NO clock, NO randomness, NO uuid, NO real subprocess, NO MCP, NO third-party import, and NO import of any heavy sibling `ngv2/**` leaf or `harness/**` module. It performs ONE deterministic step by reading the seams and dispatching on the planned action; all effects flow through the injected callables.

The primary function has the EXACT signature `run_conductor_step(session_id, seams: dict) -> dict`. `seams` is a dict of callables (plus one optional dict):
- `load_state(session_id) -> state_dict` -- returns the session state (a dict with at least `"phase"` plus artifact counts and any `"approval"`).
- `plan(state_dict) -> action_dict` -- the transition planner; returns `{"action", "target_phase", "reason"}`.
- `command_for_phase(phase, ctx) -> cmd` -- the stage command map; builds the worker command for a phase.
- `spawn(cmd) -> output_dir` -- runs the agent worker and returns where it wrote its artifacts.
- `harvest(phase, output_dir) -> list[dict]` -- collects the artifacts the worker produced.
- `persist(session_id, phase, artifacts) -> None` -- records the harvested artifacts for the session.
- `build_evidence(state_dict) -> dict` -- assembles the evidence bundle the gates consume.
- `run_gates(from_phase, to_phase, evidence) -> {"advance": bool, "blocked_by": list, ...}` -- the gate stack verdict.
- `advance(session_id, approval=None) -> None` -- moves the session to the next phase.
- `ctx` (dict, OPTIONAL) -- passed through to `command_for_phase`; defaults to an empty dict / None if absent.

Dispatch logic -- ONE deterministic step, switching on `plan(state)["action"]` (where `state = load_state(session_id)` and `action_dict = plan(state)`):
- `"spawn_stage"`: `cmd = command_for_phase(state["phase"], ctx)`; `out = spawn(cmd)`; `arts = harvest(state["phase"], out)`; `persist(session_id, state["phase"], arts)`; return `{"step": "spawned", "phase": state["phase"], "n_artifacts": len(arts)}`. (The four seam calls happen in exactly this order.)
- `"apply_gates"`: `g = run_gates(state["phase"], action_dict["target_phase"], build_evidence(state))`; if `g["advance"]` is truthy: `advance(session_id)`; return `{"step": "advanced", "to": action_dict["target_phase"]}`; ELSE return `{"step": "blocked", "blocked_by": g["blocked_by"]}`. The conductor MUST NOT call `advance` when the gates do not pass.
- `"park_for_approval"`: return `{"step": "parked"}` -- NO seam mutating call (no spawn/persist/advance).
- `"advance"`: `advance(session_id, state.get("approval"))`; return `{"step": "advanced", "to": action_dict.get("target_phase")}`.
- `"done"`: return `{"step": "done"}`.
- `"blocked"`: return `{"step": "blocked", "blocked_by": action_dict.get("reason")}`.

The thin outer loop that repeatedly calls `run_conductor_step` until `step in {"done","parked","blocked"}` is described here for context only and is EXPLICITLY OUT OF SCOPE -- do NOT build it.

The module is reachable/wired by being importable as the live conductor entry: a caller does `from ngv2.hunt_conductor import run_conductor_step` and drives the hunt FSM one step at a time. The committed oracle `tests/ngv2/test_hunt_conductor_wired.py` is the authoritative acceptance contract and proves the module importable and behaving as specified.

CRITICAL AST-SAFETY CONSTRAINT: the module performs NO eval/exec/`__import__`/os.system/real-subprocess CALL and uses NO decorators (the AST enforcer bans those). Phase names, action names, and step names appear ONLY as string-literal data. The function reads `seams` callables and dispatches; the only "execution" is calling the INJECTED seams.

# Non-Goals

This brief is coordination/orchestration logic over INJECTED SEAMS, so the differential fuzzer is bypassed for it and the integration-test requirement is excused (the literal word integration appears here per the loader's non-goals rule). Do NOT build the outer driver loop, the real session DB, the real stage command map, the real agent spawner, the real harvester/persister, the real evidence builder, or the real gate stack -- every one of those is an INJECTED seam supplied by the caller and is OUT OF SCOPE. Wiring this conductor INTO the live NobleGreed driver / daemon, the real `ngv2/session_*` modules, the real `ngv2/transition_planner.py`, the real gate stack, or any other existing module is a separate downstream integration EDIT leaf and is OUT OF SCOPE here. Do NOT spawn any real process, model, network call, or un-injected subprocess; do NOT touch the real filesystem, clock, randomness, or uuid; do NOT import any third-party package, any `harness/**` module, or any heavy sibling `ngv2/**` leaf. Do NOT author or modify any test other than the committed oracle. Do NOT introduce any eval/exec/`__import__`/os.system/real-subprocess CALL or any decorator (the AST enforcer bans them). Do NOT call `advance` on the `apply_gates` path when the gates do not pass; do NOT call any mutating seam on the `park_for_approval`/`done`/`blocked` paths.

# Inputs

The committed authoritative oracle `tests/ngv2/test_hunt_conductor_wired.py` (currently RED -- the module does not yet exist) is the fixed acceptance contract; do NOT rebuild or re-author it. It imports `run_conductor_step` from `ngv2.hunt_conductor`, builds a `seams` dict of STUB callables that record every invocation (an ordered list of called seam names, plus the arguments they received), and asserts the dispatch behavior and the call-ordering / no-advance-when-blocked invariants enumerated in Deliverables. The Python `typing` stdlib module is the ONLY dependency. The full seams contract above (the nine callables plus optional `ctx`) and the linear phase order (source -> hunt -> triage -> verify -> poc -> detonate -> novelty -> report -> awaiting_submission -> submitted -> done) are fixed inputs. The sibling pure decision brain `ngv2/transition_planner.py::plan_next_action(session_state) -> {action,target_phase,reason}` is the reference shape behind the injected `plan` seam (referenced, NOT imported by this module). The existing NobleGreed driver/daemon that will later import this conductor is a fixed downstream input -- do NOT modify it here.

# Deliverables

The NEW file `ngv2/hunt_conductor.py` containing the primary function with the EXACT signature `run_conductor_step(session_id, seams: dict) -> dict`. Behavior: read `state = seams["load_state"](session_id)`, `action_dict = seams["plan"](state)`, then dispatch on `action_dict["action"]` per the Scope logic, returning the fixed-shape result dict for each branch:
- action `"spawn_stage"` -> calls `command_for_phase`, `spawn`, `harvest`, `persist` IN THAT ORDER, returns `{"step": "spawned", "phase": <current phase>, "n_artifacts": <len of harvested artifacts>}`.
- action `"apply_gates"` with `run_gates(...)["advance"]` truthy -> calls `advance(session_id)` EXACTLY ONCE, returns `{"step": "advanced", "to": <target_phase>}`.
- action `"apply_gates"` with `run_gates(...)["advance"]` falsy -> does NOT call `advance`, returns `{"step": "blocked", "blocked_by": <gate blocked_by list>}`.
- action `"park_for_approval"` -> calls NO mutating seam (no spawn/persist/advance), returns `{"step": "parked"}`.
- action `"advance"` -> calls `advance(session_id, state.get("approval"))`, returns `{"step": "advanced", "to": <target_phase>}`.
- action `"done"` -> returns `{"step": "done"}`.
- action `"blocked"` -> returns `{"step": "blocked", "blocked_by": <action reason>}`.

This module is the live conductor entry point for the NobleGreed hunt FSM, and `tests/ngv2/test_hunt_conductor_wired.py` proves it (the committed `*_wired` reachability proof: it imports `run_conductor_step` from the live `ngv2.hunt_conductor` module).

The behavior that proves it done -- AT LEAST these concrete edge cases (mirrored as the oracle's cases and as regression/property tests), each driven with FAKE/STUB seams that record their calls into a shared list:
- (a) `plan` returns `action="spawn_stage"` -> `command_for_phase`, `spawn`, `harvest`, `persist` are all called, IN THAT ORDER; the result is `{"step": "spawned", ...}` with `n_artifacts` equal to the number of stub-harvested artifacts.
- (b) `plan` returns `action="apply_gates"` and the stub `run_gates` returns `{"advance": True, ...}` -> `advance` is called EXACTLY ONCE and the result is `{"step": "advanced", "to": <target_phase>}`.
- (c) `plan` returns `action="apply_gates"` and the stub `run_gates` returns `{"advance": False, "blocked_by": [...]}` -> `advance` is NOT called (the recorded call list contains no `"advance"`) and the result is `{"step": "blocked", "blocked_by": [...]}` (the no-advance-when-blocked INVARIANT).
- (d) `plan` returns `action="park_for_approval"` -> NO mutating seam (`spawn`/`persist`/`advance`) is called and the result is `{"step": "parked"}`.
- (e) `plan` returns `action="done"` -> the result is `{"step": "done"}`.

Plan shape: EXACTLY ONE impl task with `task_id` VERBATIM `ngv2_hunt_conductor`, `meta_task_type: orchestration` (coordination over injected seams -- `bypass_fuzzer`), `priority: high`, `dependencies: []`, `working_dir: "/home/xnihil0zer0/NobleGreedv2"`, `files_touched: ["ngv2/hunt_conductor.py"]` ONLY, WHOLE-FILE single-file emission. `verification_command: python3 -m pytest -q tests/ngv2/test_hunt_conductor_wired.py` (CWD-relative, NO `cd`). The committed `tests/ngv2/test_hunt_conductor_wired.py` is the authoritative oracle and the `*_wired` reachability proof; make it GREEN. `spec.functional_requirements` CONSOLIDATED to at most 5 entries; `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements`; `test_spec.regression_tests` MUST list at least two entries naming the committed-oracle cases for edge case (c) the no-advance-when-blocked invariant and edge case (d) park_for_approval (no mutating seam). Verified GREEN by `python3 -m pytest -q tests/ngv2/test_hunt_conductor_wired.py`.
