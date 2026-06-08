---
dependencies:
  - "procedure-substrate"
interfaces: "Consumes PROCEDURE_REGISTRY; advance(procedure, phase, gate_result) -> Decision; GateResult(ok: bool, reason: str, fix_hint: str); ProcedureState(phase: str, last_gate: GateResult | None); load_state(conversation_id, *, state_dir) -> ProcedureState. Edits can_switch(current, target, unlocked), dispatch_action(mode, command, args, *, seams), render_mode_context(mode, state) additively, preserving their existing signatures and behaviour."
---

# Title

Enforcement integration: mode-switch lock, action sequence-lock, phase guidance

# Scope

Additively edit three EXISTING overseer symbols (one file per leaf) so the substrate's procedure machine WITHHOLDS out-of-order actions and mode switches rather than discouraging them, preserving every current behaviour and passing test. (1) EDIT overseer/mode_gate.py::can_switch — while the conversation's active procedure phase is not the terminal COMPLETE, return False for EVERY target except observe (the always-available abort that abandons the procedure) and current (no-op); once the phase reaches COMPLETE the existing lattice rules resume unchanged. (2) EDIT overseer/actions.py::dispatch_action — add a fail-closed (phase, command) check BESIDE the existing (mode, command) check: a command not permitted by the CURRENT phase is REFUSED with a ModeViolation BEFORE any seam fires, and the current phase's gate must PASS before the phase advances. (3) EDIT overseer/mode_prompts.py::render_mode_context — render the state-derived CURRENT phase, the last gate's pass/fail plus its fix_hint, and the SINGLE next action, all read from durable procedure state and never inferred. Extend the existing oracles tests/overseer/test_mode_gate_sequence.py (new), test_actions.py, and test_mode_prompts.py as the per-leaf verification_command targets.

# Non-Goals

Do NOT author the substrate (gates.py, procedure.py, procedure_state.py) — consume it. Do NOT touch run_chat_turn or the PreToolUse hook (the runtime_wiring child owns those). No new agent spawns, model/API/network/SSE calls, or un-injected subprocesses. No changes to harness/** or the autowork daemon. No procedures or registry entries for the out-of-scope modes. The word 'integration' is load-bearing here: these are EXISTING-symbol additive edits that must preserve all current behaviour and tests, each leaf editing exactly ONE file (no multi-file emission). This child does not dispatch a build or author the production oracles.

# Inputs

From procedure_substrate: PROCEDURE_REGISTRY (mode name -> ordered phases, each phase binds a gate name + next-action string); advance(procedure, phase, gate_result) -> Decision (next phase | Blocked(reason, fix_hint) | Complete); GateResult(ok: bool, reason: str, fix_hint: str); ProcedureState(phase: str, last_gate: GateResult | None) with load_state(conversation_id, *, state_dir) -> ProcedureState and save_state(conversation_id, state, *, state_dir) -> None. The ALREADY-BUILT seams being edited: overseer/mode_gate.py::can_switch(current, target, unlocked), overseer/actions.py::dispatch_action(mode, command, args, *, seams), overseer/mode_prompts.py::render_mode_context(mode, state), and the ModeViolation exception type already raised by dispatch_action.

# Deliverables

Edited overseer/mode_gate.py whose can_switch consults the active procedure phase and returns False for all targets except observe/current while phase != COMPLETE, resuming the existing lattice once phase == COMPLETE. Edited overseer/actions.py whose dispatch_action raises ModeViolation on a (phase, command) pair not permitted by the current phase, before any seam fires, beside the existing (mode, command) fail-closed check. Edited overseer/mode_prompts.py whose render_mode_context emits the current phase, last GateResult pass/fail + fix_hint, and the single next-action string from durable procedure state. Oracles tests/overseer/test_mode_gate_sequence.py (new), test_actions.py (extended), and test_mode_prompts.py (extended), each named as a leaf verification_command python -m pytest tests/overseer/<oracle>.py -q.
