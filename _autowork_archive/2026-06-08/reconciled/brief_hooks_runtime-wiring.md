---
dependencies:
  - "procedure-substrate"
  - "enforcement-integration"
interfaces: "Consumes PROCEDURE_REGISTRY; advance(procedure, phase, gate_result) -> Decision; GateResult(ok: bool, reason: str, fix_hint: str); ProcedureState(phase: str, last_gate: GateResult | None); load_state(conversation_id, *, state_dir) -> ProcedureState; save_state(conversation_id, state, *, state_dir) -> None; render_mode_context(mode, state). Edits run_chat_turn additively (preserving its signature and behaviour) and produces overseer/procedure_hook.py with a PreToolUse hook entrypoint plus its settings fragment."
---

# Title

Runtime wiring: per-turn gate execution and the agent-boundary PreToolUse hook

# Scope

Wire the procedure machine into the live overseer loop, one file per leaf. (1) EDIT overseer/turn_runner.py::run_chat_turn — each turn: load the procedure_state for the conversation, run the CURRENT phase's bound gate via the injected seams (run_seam, git_seam, fs/state_dir), advance the phase with the reducer and persist the new state, and thread the procedure state into render_mode_context so the computed next action and last-gate result surface every turn; preserve all existing per-turn behaviour and tests. (2) NEW overseer/procedure_hook.py — the PreToolUse hook entrypoint on the overseer's claude invocation that DENIES a raw tool call inconsistent with the active phase (the agent-boundary hard-block), e.g. a Write to a brief_hooks_* path while the phase is before BRIEF, or any git commit proxy before the oracle is RED, closing the gap where the jailed agent bypasses the structured action seam with a raw tool; ship the settings fragment wiring the hook onto the overseer's claude invocation. The deterministic hook logic is pure/stdlib-only over the substrate's state and gate names. Extend tests/overseer/test_turn_runner.py and author tests/overseer/test_procedure_hook.py (new) as the per-leaf verification_command targets.

# Non-Goals

Do NOT author or modify the substrate modules or the enforcement edits (can_switch, dispatch_action, render_mode_context) — consume them. No new agent spawns, model/API/network/SSE calls, or un-injected subprocesses; the hook performs deterministic deny decisions only and does not itself execute tests or shell out un-injected. No changes to harness/** or the autowork daemon, and no change to the harness build pipeline. No procedures or registry entries for the out-of-scope modes. The run_chat_turn edit is an EXISTING-symbol additive integration that preserves all current behaviour and tests; the hook is a new single-file whole-file module. Each leaf edits/creates exactly ONE file. This child does not dispatch a build or author the production oracles; the owner gate stays paused.

# Inputs

From procedure_substrate: PROCEDURE_REGISTRY; advance(procedure, phase, gate_result) -> Decision (next phase | Blocked(reason, fix_hint) | Complete); GateResult(ok: bool, reason: str, fix_hint: str); ProcedureState(phase: str, last_gate: GateResult | None); load_state(conversation_id, *, state_dir) -> ProcedureState; save_state(conversation_id, state, *, state_dir) -> None; the six gate functions oracle_is_red/oracles_committed_at_head/brief_lint/plan_preflight/suite_green_zero_reg/posture_locked invoked via injected seams. From enforcement_integration: the updated render_mode_context(mode, state) that consumes procedure state, and dispatch_action(mode, command, args, *, seams) with its (phase, command) fail-closed check. The ALREADY-BUILT seams: overseer/turn_runner.py::run_chat_turn and the overseer's claude PreToolUse settings surface.

# Deliverables

Edited overseer/turn_runner.py whose run_chat_turn loads procedure state, runs the current phase's gate through injected seams, advances and persists the phase, and threads the state into render_mode_context each turn. New overseer/procedure_hook.py exposing the PreToolUse hook entrypoint that denies raw tool calls inconsistent with the active phase, plus the settings fragment wiring it onto the overseer's claude invocation. Oracles tests/overseer/test_turn_runner.py (extended) and tests/overseer/test_procedure_hook.py (new), each named as a leaf verification_command python -m pytest tests/overseer/<oracle>.py -q.
