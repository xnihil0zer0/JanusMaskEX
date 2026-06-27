# ⚠️ REQUIRED P2.1 INTEGRATION LEAF — NOT YET PLANNED (do not forget)

c1/c2/c3 (and c4-c6) are authored as **pure disjoint handlers** with live-FSM wiring **DEFERRED**.
The external `wire_up` gate NO-OPS on NGv2, so an orphaned handler LANDS GREEN but `run_hunt`
NEVER calls it. Without this integration leaf, the entire P2.1 env-FSM is BUILT-not-WORKS.

## ⚠️ PREREQUISITE — the PRODUCER LAYER (cP), a SEPARATE deliverable (audit A4-G1, 2026-06-24)
The c1-c6 handlers ADJUDICATE pre-staged input dicts that NOTHING currently produces (grep-proven:
`detect_input`/`provision_input`/`jail_input` appear only as consumed params). Author **P2.1-cP
`env_phase_producers`** = the 6 impure seams that BUILD those dicts: os.walk+detect_frameworks
(detect); jailed --unshare-net lockfile venv/node build w/ captured argv (provision — needs P0.2-NGv2);
build_detonation_jail_argv capture (jail_build); in-jail import + loopback service-start (health);
sink_instrument/settrace ping (reach); FS+stdout baseline snapshot (baseline). This is the BULK of the
real work. Without it the FSM is BUILT-not-WORKS and X1 cannot close. Also promote **P0.2-NGv2**
(`poc_runner_live._default_pip_installer` :434 → jailed lockfile-only install) — provision producer
needs it; JM side has only RED oracle 0795605, no impl.

> **★ POLICY — PIPELINE-FIRST IS MANDATORY (owner directive 2026-06-24).** No cP producer / impure helper (jailed venv-build, target service-start+bind, settrace benign-ping, jailed benign-run, or any `poc_runner_live`-class side-effecting code introduced for P2.1) may be declared "requires owner hand-edit" or "irreducible / not-pipeline-built" until it has been ATTEMPTED through the planner→stage→worker pipeline at least once and that attempt has FAILED with a documented, specific reason. First resort: build it through the pipeline, augmenting the agents/planner THROUGH the pipeline as needed (per the spec-only directive). Hand-editing is the LAST resort, escalated to an owner decision ONLY after a real pipeline attempt is recorded as failed. "Owner-gated" never means "leave it built-but-not-working"; the bar remains demonstrated-live (BUILT≠WORKS).

(This TODO does not itself assert the cP producers are hand-authored or owner-gated — it says "Author P2.1-cP",
which is pipeline framing. The block above is inserted as a reinforcing guard so no future reader treats the
"BULK of the real work" / impure-seam description as license to skip the pipeline.)

## Must wire (DECOMP §2 — 4 touch-points × each of the 6 env states)
1. PHASE_ORDER: slot ENV_PHASE_ORDER ahead of hunt in the shared `ngv2/fsm_evidence.PHASE_ORDER`
   (consumed by transition_planner + gate_executor). Fold inert `source` into DETECT.
   ⚠️ AUDIT A4-G2: c0 folded ONLY transition_planner+gate_executor. THREE more live literals must also
   derive from the c0 source or they DESYNC: `session_api.PHASE_ORDER` (:675, used by `_next_phase`/
   `advance`), `session_api._PHASES` (:716, used by `create()`), and `state_machine.py`
   (`LIFECYCLE_PHASES`/`PHASES`/`ALLOWED_TRANSITIONS`). Add an equality oracle + in-order traversal fixture.
2. transition_planner.worker_phases (transition_planner.py:64): add (phase, count_field, next_phase) per state.
3. gate_executor._TRANSITION_GATES (gate_executor.py:39) + a TypedTerminal per state; the gate CALLS the
   c1-c6 handler and consumes its content_hash'd artifact via c0 advance_gate (fail-closed).
   ⚠️ AUDIT A4-G3: the live `gate_executor.run_gates` does NOT import `phase_artifact_hash`/`advance_gate`
   today — it adjudicates a FLAT evidence dict via `classify_*` (zero content-hash check). c0's content-hash
   model has ZERO live consumers. c7 must BRIDGE env-artifact→flat-gate-evidence + re-validate via
   advance_gate, w/ a tampered-artifact-refused oracle (else §3 content-hash guarantee + X5 are vacuous).
4. conductor_seams: _PHASE_COUNT_KEY/persist (conductor_seams.py:20,48) + build_evidence (conductor_seams.py:112)
   evidence key per state + stage_command_map.AGENT_PHASES (stage_command_map.py:10) + a workers/<phase>.py
   per state + its build_seams branch (workers/_runner.py:56).
5. _INITIAL_PHASE 'hunt'→'detect' (run_hunt.py:61) + _ensure_seeded (run_hunt.py:81).

## WORKS bar (capstone, not a green gate)
Analytic script drives REAL run_hunt over a REAL fixture target → proves traversal
detect→provision→jail_build→health_probe→reachability_probe→baseline_capture→hunt→… with genuine
per-state content_hash'd evidence, each advance_gate fail-closed. (Model on x1_demo/demo_run_hunt_endtoend.py.)

## Shape
Probably its own epic / serial set of 6 wiring leaves (one per state — all edit the shared FSM files, so
NOT parallel). Each wiring leaf = the point that state becomes genuinely wired + incrementally demoable.
Coordinate c5 reachability wiring with P1.3/P3.1 sink channels (don't double-wire).

## Position
c0(done)→{c1∥c2∥c3}→{c4→c5}→c6→**THIS INTEGRATION LEAF/EPIC**→P2.2. P2.1 is NOT "done" until this lands + demos.
