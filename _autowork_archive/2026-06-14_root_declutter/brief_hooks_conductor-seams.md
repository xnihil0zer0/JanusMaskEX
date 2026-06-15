---
dependencies:
  - "conductor_glue"
  - "stage_workers"
interfaces: "build_default_seams(session_id, db, llm_client, ctx) -> dict with keys {load_state, plan, command_for_phase, spawn, harvest, persist, build_evidence, run_gates, advance}; binds advance_with_gates(session_id, db, run_gates, advance, build_evidence) -> {advanced: bool, blocked_by}, run_until_terminal(session_id, seams, max_steps) -> {steps: list, final_step}, get_task(session_row: dict) -> {phase, target, prior_findings, parked_package}, StageWorker(task, get_task_fn, stage_fn, write_fn), run_stage(context, seams) -> list[dict]"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

Seam assembler binding the conductor's injected callables to the real pipeline and worker dispatch

# Scope

Build the NEW whole-file module ngv2/conductor_seams.py exposing build_default_seams(session_id, db, llm_client, ctx) -> dict, the live wire-up that returns the exact seam dict hunt_conductor.run_conductor_step expects — load_state, plan, command_for_phase, spawn, harvest, persist, build_evidence, run_gates, advance — with each callable bound to the real Inputs: load_state/persist to session_db + session_api, plan to transition_planner.plan_next_action, command_for_phase to stage_command_map.command_for_phase, harvest to artifact_harvester.harvest_stage_artifacts, run_gates to gate_executor.run_gates, the spawn callable to a worker-spawning closure that constructs a StageWorker and invokes the correct per-phase run_stage, and advance bound through the gated-advance path so the four may_confirm gates actually block. Importing the workers package and the glue modules from this assembler is what makes them reachable (the conductor is the live entry); if the wire-up gate flags an orphan before this import lands, register the ngv2/workers dotted paths under config. Single file with a paired test_authoring sibling whose mutation_target is this module so the pipeline authors the RED oracle, proven by a stub db + stub llm_client that the assembled callables route to correctly, with at least two edge cases (e.g. spawn routing to the wrong phase worker; advance seam refusing to advance when run_gates returns advance False).

# Non-Goals

Do not reimplement the loop (run_until_terminal), gated_advance, get_task, or any worker run_stage — import and bind them. Do not edit any existing committed module in place; bind session_api.py, session_db.py, and the five landed primitives only by composing their existing public functions. Do not weaken any acceptance gate, auto-submit to huntr, or contact any external service — the assembled advance seam must route through the gated-advance path so the four may_confirm gates still block, and the pipeline parks at awaiting_submission. Per the integration policy this assembler composes existing seams, so this integration concern needs no separate heavy cross-module integration test; no real LLM call, network, or subprocess may run inside the oracle (stub db and stub llm_client only).

# Inputs

Consumes from conductor_glue: advance_with_gates(session_id, db, run_gates, advance, build_evidence) -> {advanced: bool, blocked_by} (bound as the gated advance seam), run_until_terminal(session_id, seams, max_steps) -> {steps: list, final_step} (the live driver this seam dict feeds), and get_task(session_row: dict) -> {phase, target, prior_findings, parked_package}. Consumes from stage_workers: StageWorker(task, get_task_fn, stage_fn, write_fn) and run_stage(context, seams) -> list[dict] per phase (dispatched by the spawn closure). Reads (does not modify): ngv2/hunt_conductor.py run_conductor_step(session_id, seams: dict); transition_planner.plan_next_action; stage_command_map.command_for_phase(phase, session_ctx); gate_executor.run_gates(from_phase, to_phase, evidence); artifact_harvester.harvest_stage_artifacts(phase, output_dir); session_api.advance/transition/submit_artifacts/get_current_phase; session_db.get_session/insert_finding/insert_poc/insert_report; ngv2/llm_client.py.

# Deliverables

ngv2/conductor_seams.py exposing build_default_seams(session_id, db, llm_client, ctx) -> dict containing keys load_state, plan, command_for_phase, spawn, harvest, persist, build_evidence, run_gates, advance, each bound to the real pipeline so hunt_conductor.run_conductor_step can consume it and conductor_loop.run_until_terminal can drive it across all agent phases, with the advance key routed through the gated-advance path. A test_authoring sibling with mutation_target set to ngv2/conductor_seams.py and a verification_command naming the authored oracle.
