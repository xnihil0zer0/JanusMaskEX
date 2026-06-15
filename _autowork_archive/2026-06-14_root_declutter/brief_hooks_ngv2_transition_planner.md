---
interfaces: "creates the NEW standalone module ngv2/transition_planner.py -- a pure, deterministic, stdlib-only decision brain exposing plan_next_action(session_state: dict) -> dict; given the bug-hunt session state (phase, findings, pocs, reports, verdict, novelty, approved, blocked) it returns {action, target_phase, reason} where action is one of {spawn_stage, apply_gates, park_for_approval, advance, blocked, done}, telling a deterministic conductor what to do next without moving any artifact or state by hand; reachable by being importable into the NobleGreed conductor decision path, with the committed oracle tests/ngv2/test_transition_planner_wired.py proving it GREEN"
dependencies: []
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/transition_planner.py -- NEW pure, deterministic DECISION BRAIN that a conductor calls to know what to do next in the NobleGreed bug-hunt state machine. The hunt pipeline runs through linear phases source -> hunt -> triage -> verify -> poc -> detonate -> novelty -> report -> awaiting_submission -> submitted -> done. The owner is automating that pipeline so that deterministic SCRIPTS move work between agent stages -- no agent ever moves artifacts or mutates state by hand. This module is the pure decision function those scripts consult: given the current session state, it returns a single structured action ({action, target_phase, reason}) describing the next move (spawn the agent for the current phase, apply the gates and advance to the next phase, park for human approval, advance, mark blocked, or mark done). It is fail-closed and side-effect-free: it reads a dict and returns a dict; it never executes a stage, mutates state, or performs I/O. The conductor consumes the returned action to drive the next deterministic step.

# Scope

CREATE the NEW single-file module `ngv2/transition_planner.py` (NGv2 external-target task -- `working_dir` = /home/xnihil0zer0/NobleGreedv2). The module is PURE and stdlib-only (`typing` only is needed): NO network, NO disk I/O, NO clock, NO randomness, NO uuid, NO subprocess, NO MCP, NO third-party import, and NO import of any sibling `ngv2/**` leaf. It operates ONLY on the `session_state` dict passed in (so it is differential-fuzzable and byte-stable). The primary function is `plan_next_action(session_state: dict) -> dict`, returning a fixed-shape dict with exactly the keys `action`, `target_phase`, and `reason`.

`session_state` keys (all read, never mutated): `phase` (str), `findings` (int count), `pocs` (int), `reports` (int), `verdict` (`"confirmed"` | `"refuted"` | None), `novelty` (`"NOVEL"` | `"POSSIBLE_DUP"` | `"CONFIRMED_DUP"` | None), `approved` (bool), `blocked` (bool). Missing keys default safely (ints default 0, bools default False, optional strings default None).

Return dict: `action` is one of `{"spawn_stage", "apply_gates", "park_for_approval", "advance", "blocked", "done"}`; `target_phase` is a phase-name str or None; `reason` is a short human-readable str explaining the decision.

Decision logic, fail-closed and deterministic, evaluated in THIS strict precedence order:
- if `blocked` is True -> `action="blocked"`, `target_phase=None` (a blocked session does nothing until unblocked; this is checked FIRST so a blocked done/awaiting session still reports blocked).
- elif `phase == "done"` -> `action="done"`, `target_phase=None`.
- elif `phase == "awaiting_submission"` -> if `approved` is True then `action="advance"`, `target_phase="submitted"`; else `action="park_for_approval"`, `target_phase=None` (NEVER auto-submit without approval).
- elif the current phase has NOT yet produced its required artifact -- i.e. (`phase == "hunt"` and `findings == 0`) or (`phase == "poc"` and `pocs == 0`) or (`phase == "detonate"` and `reports == 0`) -> `action="spawn_stage"`, `target_phase=phase` (run the agent for THIS phase to produce its artifact).
- else (the artifact for the current phase is present, or the phase has no artifact gate) -> `action="apply_gates"`, `target_phase=` the NEXT phase in the linear order (source -> hunt -> triage -> verify -> poc -> detonate -> novelty -> report -> awaiting_submission -> submitted -> done). If the current phase is the last named phase, `target_phase` stays within the order (terminal phases are handled by the `done`/`awaiting_submission` branches above).

The module is reachable/wired by being importable into the NobleGreed conductor decision path (the conductor can `from ngv2.transition_planner import plan_next_action` and use the returned `action`/`target_phase` to drive the next deterministic step). The committed oracle `tests/ngv2/test_transition_planner_wired.py` is the authoritative acceptance contract and proves the module is importable and behaves as specified.

CRITICAL AST-SAFETY CONSTRAINT: the module performs NO eval/exec/`__import__`/os.system/subprocess CALL and uses NO decorators (the AST enforcer bans those). Phase names and action names appear ONLY as string-literal data. The function reads a dict and returns a dict -- it never executes a stage, mutates the input, or performs I/O.

# Non-Goals

Do NOT actually move artifacts, mutate session state, spawn an agent, run a stage, or perform any I/O -- this is a PURE decision function that reads a dict and returns a dict; executing the action it recommends is the conductor's job and is explicitly OUT OF SCOPE. Wiring this planner INTO the live NobleGreed conductor (the actual script that consumes `action`/`target_phase` and dispatches the next stage) is a separate downstream EDIT leaf and is OUT OF SCOPE here -- integration with the conductor, the hunt loop, the session DB, the gate stack, or any other existing module is NOT part of this leaf. Because this is a pure, self-contained decision function with no live call site of its own, the integration-test requirement is excused (the literal word integration appears here per the loader's non-goals rule). Do NOT author or modify any test other than the committed oracle. Do NOT add real network, disk I/O, clock, randomness, subprocess, or logging. Do NOT import any third-party package or any sibling `ngv2/**` leaf. Do NOT introduce any eval/exec/`__import__`/os.system/subprocess CALL or any decorator (AST enforcer bans them).

# Inputs

The committed authoritative oracle `tests/ngv2/test_transition_planner_wired.py` (currently RED -- the module does not yet exist) is the fixed acceptance contract; do NOT rebuild or re-author it. It imports `plan_next_action` from `ngv2.transition_planner` and pins the return-dict shape (keys exactly `{action, target_phase, reason}`), the `action` enum (`spawn_stage` | `apply_gates` | `park_for_approval` | `advance` | `blocked` | `done`), and the six edge cases enumerated in Deliverables. The Python `typing` stdlib module is the ONLY dependency. The linear phase order (source -> hunt -> triage -> verify -> poc -> detonate -> novelty -> report -> awaiting_submission -> submitted -> done) is a fixed input. The existing NGv2 conductor (the consumer that will later import this planner) is a fixed downstream input -- do NOT modify it here.

# Deliverables

The NEW file `ngv2/transition_planner.py` containing the primary function with the EXACT signature `plan_next_action(session_state: dict) -> dict` that returns a dict with exactly the keys `action` (one of `"spawn_stage"`, `"apply_gates"`, `"park_for_approval"`, `"advance"`, `"blocked"`, `"done"`), `target_phase` (a phase-name str or None), and `reason` (a short str). Behavior: read `session_state` (defaulting missing keys safely), apply the fail-closed precedence logic from Scope (`blocked` first, then `done`, then `awaiting_submission`/`approved`, then the missing-artifact `spawn_stage` check for hunt/poc/detonate, else `apply_gates` to the next phase in the linear order), and return the fixed-shape dict deterministically (identical inputs yield byte-identical output). The module is reachable/wired by being importable into the conductor decision path; the committed `tests/ngv2/test_transition_planner_wired.py` is the `*_wired` reachability proof.

The behavior that proves it done -- AT LEAST these concrete edge cases (mirrored as the oracle's cases and as regression/property tests):
- (a) `phase="hunt"`, `findings=0` -> `action == "spawn_stage"`, `target_phase == "hunt"` (hunt has not yet produced a finding; run the hunt agent).
- (b) `phase="hunt"`, `findings=2` -> `action == "apply_gates"`, `target_phase == "triage"` (the finding artifact is present; gate and advance to the next phase).
- (c) `phase="awaiting_submission"`, `approved=False` -> `action == "park_for_approval"`, `target_phase == None` (never auto-submit without human approval).
- (d) `phase="awaiting_submission"`, `approved=True` -> `action == "advance"`, `target_phase == "submitted"`.
- (e) `phase="done"` -> `action == "done"`, `target_phase == None`.
- (f) `blocked=True` (any phase) -> `action == "blocked"`, `target_phase == None` (checked first; a blocked session does nothing).

Plan shape: EXACTLY ONE impl task with `task_id` VERBATIM `ngv2_transition_planner`, `meta_task_type: validation`, `priority: high`, `dependencies: []`, `working_dir: "/home/xnihil0zer0/NobleGreedv2"`, `files_touched: ["ngv2/transition_planner.py"]` ONLY, WHOLE-FILE single-file emission. `verification_command: python3 -m pytest -q tests/ngv2/test_transition_planner_wired.py` (CWD-relative, NO `cd`). The committed `tests/ngv2/test_transition_planner_wired.py` is the authoritative oracle and the `*_wired` reachability proof; make it GREEN. `spec.functional_requirements` CONSOLIDATED to at most 5 entries; `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements`; `test_spec.regression_tests` MUST list at least two entries naming the committed-oracle cases for edge cases (c) park_for_approval and (f) blocked above. Verified GREEN by `python3 -m pytest -q tests/ngv2/test_transition_planner_wired.py`.
