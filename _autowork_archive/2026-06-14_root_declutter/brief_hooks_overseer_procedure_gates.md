---
epic: true
---

<!--
# STATUS: ✅ BUILT (verified 2026-06-08, adversarial cross-check vs HEAD 97a824d)
This epic was fully built in a prior session. A missing plan_hooks_*.json is EXPECTED
for an epic (its record is plan_overseer_procedure_gates_epic.json, currently UNTRACKED).

BUILT modules + SHAs:
  - overseer/gates.py            (f883a25)
  - overseer/procedure.py        (6c6c3dd, 41c45aa)
  - overseer/procedure_state.py  (fe6128e)
  - overseer/turn_runner.py      per-turn procedure loop (a047a1a, turn_runner.py:260-300)
  - overseer/procedure_hook.py   PreToolUse hook (54f770f)
  NOTE: enforcement edits landed in mode_gate.py (can_switch:164),
        actions.py (dispatch_action:33), mode_prompts.py (render_mode_context:57)
        — NOT in procedure.py/procedure_state.py.

Oracles GREEN (55 passed): tests/overseer/test_gates.py test_procedure.py
  test_procedure_state.py test_procedure_hook.py test_mode_gate_sequence.py

OPEN GAP (genuinely un-built, owner-gated — DO NOT build while agent_exec_substrate
is rewriting turn_runner): no default production gate-runner. turn_runner.run_turn's
`gate_runner` seam defaults to None and the only production caller (service.py:70-73)
passes nothing → at runtime the FSM never self-advances. A resolver mapping the 15
procedure phase gate-LABELS (scope_locked, oracle_present, ... pushed) → the 6 real
gates.py functions does not exist (overseer/gate_runner.py absent). The 55 oracles
test the pieces in isolation only. Build as ONE new leaf (overseer/gate_runner.py +
oracle) AFTER the tmux turn_runner wiring lands and WITH owner sign-off.
-->

# Title

JanusMaskJR Overseer — Gated Procedure State Machine. Turn the operator's tribal "recipe"
for safely driving the build pipeline into a DETERMINISTIC, HARD-BLOCKING per-mode phase
machine: while a mode's procedure is mid-sequence the overseer may take ONLY the single next
permitted action and may NOT change modes (except an always-available abort to `observe`);
once the sequence COMPLETES, normal mode switching resumes. The agent is never told to "search
for what to do next" — the next action is COMPUTED from durable state and surfaced every turn,
and out-of-order actions are WITHHELD, not merely discouraged. YOU (the planner) decide how to
decompose this into leaves; a non-binding suggested grouping is given at the end.

# Scope

Driving a JanusMask build correctly today depends on un-encoded operator knowledge — a set of
hard-won lessons that, when skipped, cost failed dispatches, rollbacks, and a broken tree:
1. Commit the RED oracle BEFORE dispatch — the gate verifies from HEAD; an uncommitted oracle is
   invisible and the build rolls back.
2. The oracle must actually be RED first (a green "oracle" pins a fiction — exactly the
   `(no output)` stream-parser bug that shipped behind a green-but-unrealistic fixture).
3. The plan's `task_id` must be unique — the planner's generic `T1` collides with a stale
   `state/tasks/processed/T1.json` marker and the task is silently treated as already complete.
4. The plan must carry ≥2 edge_cases reflected in regression/property tests AND the literal word
   "integration" in `non_goals`, or the plan validator rejects it as a thin draft.
5. Name the exact target file and describe it STRUCTURALLY — the blind-draft jail mounts only
   `inbox/brief.json`, so source line-number citations are noise the worker cannot resolve.
6. A NEW module is a single-file whole-file emission; an EXISTING symbol is a symbol patch; a NEW
   top-level symbol must ride as an R-anchored trailing node — mixing these makes the auto-commit
   fail.
7. After a dispatch, RESTORE the safe posture: `full_stop` present, `orchestrator.flag=pause`,
   allowlist deny-all, daemon dead.

Each lesson is really a DETERMINISTIC GATE. JanusMask's design principle is to enforce by
WITHHOLDING and CHECKING, never by prompt (this is exactly what `overseer/mode_gate.py` already
does for tools and routes). So the recipe must become a CHECKED PHASE MACHINE whose gates are
pure, testable functions — not a longer system prompt the agent may ignore.

# Inputs

The new leaves consume three fixed inputs, none of which they may rebuild:
1. The operator recipe encoded as the seven lessons in the Scope above — these are the GATES.
2. The committed overseer foundation modules listed under "ALREADY BUILT" below (the seams the
   procedure machine plugs into).
3. The existing `harness.planner.plan_validator` (wrapped, not reimplemented, by the
   `plan_preflight` gate) and the project posture flags under `state/control/` (read by the
   `posture_locked` gate): `state/control/autowork/full_stop`, `state/control/orchestrator.flag`,
   `state/control/autowork/auto_promote.allowlist`.

# ALREADY BUILT — do NOT rebuild; these are DONE inputs the new leaves import

The overseer foundation is committed and oracle-green. Treat as fixed seams:
- `overseer/modes.py` — the 14-mode registry (`ModeSpec`, tiers R/W/S, `MODE_REGISTRY`,
  `get_mode`, `list_available_modes`). Each mode already declares `inbox_contract`/`outbox_contract`.
- `overseer/mode_gate.py` — tool/route WITHHOLDING + the lattice transition fn `can_switch(current,
  target, unlocked)` (free movement in R, down anytime, R→W only for default-available W, S only if
  unlocked, observe always reachable). THIS is where the mode-switch hard-block plugs in.
- `overseer/mode_prompts.py` — `render_mode_context(mode, state)` builds the `--append-system-prompt`
  block. THIS is where state-derived "current phase + next action" guidance plugs in.
- `overseer/actions.py` — `dispatch_action(mode, command, args, *, seams)` is already FAIL-CLOSED on
  `(mode, command)`. THIS is where the `(phase, command)` gate plugs in beside it.
- `overseer/driver.py` / `overseer/turn_runner.py` — the per-turn loop (`run_turn` / `run_chat_turn`)
  that re-derives everything each turn and persists to the store. THIS is where the gate is run and
  the phase advanced each turn.
- `overseer/session_store.py` / `overseer/transcript.py` — conversation persistence.

# Which modes get a procedure, and why — ranked by reliability win

A procedure is worth its gates only where there is a real, repeatable failure mode whose cost is
high. The four below form the END-TO-END build lifecycle and chain naturally
(`brief-author → oracle-author → dispatch → push`); the sequence-lock means you cannot jump ahead
mid-task. Read-only modes (`observe`/`analyze`/`audit`) get NO procedure — there is nothing to gate.
The remaining W/S modes (`triage`, `daemon-supervisor`, `ui-tester`, `flag-steward`,
`harness-self-fix`, `security-review`, `rebuild-factory`) are explicitly OUT OF SCOPE for this epic
(lower frequency / lower cost-of-error); the substrate is built generically so they can adopt a
procedure later by adding a registry entry, no new code.

1. **brief-author (Tier W) — BIGGEST WIN.** Every lesson above lives here. Procedure:
   `SCOPE → ORACLE → COMMIT → BRIEF → PLAN → COMPLETE`.
   - SCOPE: a `target` artifact naming exactly ONE file + its meta_task_type + patch-strategy
     (new-module=whole-file / existing-symbol=patch / new-top-level-symbol=R-anchor). Gate: single
     target chosen, strategy classified.
   - ORACLE: author the RED test. Gate `oracle_is_red` — RUN it, assert it FAILS.
   - COMMIT: gate `oracles_committed_at_head` — each oracle path is committed at HEAD, not just on disk.
   - BRIEF: write `brief_hooks_<slug>.md`. Gate `brief_lint` — contains `# Required plan shape`, names
     the exact file, no naked source line-number citations, single-file scope.
   - PLAN: generate `plan_hooks_<slug>.json`. Gate `plan_preflight` — unique non-`T1` task_id with no
     `processed/<id>` collision, ≥2 edge_cases in regression/property tests, literal "integration" in
     non_goals (wraps the existing `plan_validator`).

2. **oracle-author (Tier W).** Oracle-first is the load-bearing precondition of the whole factory.
   Procedure: `SCOPE → DRAFT → RED → COMMIT → COMPLETE` (gates: `oracle_is_red`, then
   `oracles_committed_at_head`).

3. **dispatch (Tier W).** The two costliest mistakes (uncommitted oracle; un-restored posture) are
   here. Procedure: `PREFLIGHT → STAGE → BUILD → VERIFY → RESTORE → COMPLETE`.
   - PREFLIGHT gate: `oracles_committed_at_head` AND `plan_preflight`.
   - VERIFY gate: `suite_green_zero_reg` — the named oracle is GREEN and the full suite shows 0 new
     regressions vs baseline.
   - RESTORE gate: `posture_locked` — `full_stop` present, `orchestrator.flag==pause`, allowlist
     deny-all.

4. **push (Tier S, already unlock-gated) — biggest SAFETY win.** Push is irreversible and
   outward-facing; gating it behind a verified-green sweep prevents publishing a broken tree.
   Procedure: `SWEEP → ZERO_REG → POSTURE → PUSH → COMPLETE` (gates: `suite_green_zero_reg`,
   `posture_locked`, then the push action).

# The hard-block rules (the cardinal behaviour)

- **Action sequence-lock (within a mode):** in `dispatch_action`, a `command` not permitted by the
  CURRENT phase is REFUSED with a `ModeViolation` BEFORE any seam fires — exactly as `(mode, command)`
  is refused today. The current phase's gate must PASS before the phase advances.
- **Mode-switch lock (between modes):** while a conversation's mode has a procedure whose phase is not
  the terminal `COMPLETE`, `can_switch` returns False for EVERY target except `observe` (the always-
  available abort, which ABANDONS the active procedure) and `current` (no-op). Once the phase reaches
  `COMPLETE`, the normal lattice rules resume and the operator may advance to the next mode.
- **Agent-boundary hard-block:** a PreToolUse hook on the overseer's `claude` invocation DENIES a raw
  tool call that would skip a gate (e.g. `Write` to a `brief_hooks_*` path while the phase is before
  BRIEF, or any `git commit` proxy before the oracle is RED). This is the deepest withholding — it
  closes the gap where the jailed agent could bypass the structured action seam with a raw tool.
- **Guidance, every turn:** `render_mode_context` renders the CURRENT phase, the last gate's
  pass/fail + its `fix_hint`, and the SINGLE next action — read from durable state, never inferred.

# Correctness regimes (the build boundary)

DETERMINISTIC logic (the gate functions, the phase reducer, the registry, the state store) is fully
JM-rebuildable and MUST be pure/stdlib-only over INJECTED seams (a `run_seam` for executing a test,
a `git_seam` for HEAD membership, plain filesystem reads). It NEVER spawns a real process, makes a
model/API/network/SSE call, or shells out un-injected — all such I/O flows through injected seams so
the oracles drive it hermetically. The INTEGRATION edits (`can_switch`, `dispatch_action`,
`render_mode_context`, `run_chat_turn`, the hook) modify EXISTING symbols additively and must
preserve every current behaviour and passing test.

THE CARDINAL PROJECT RULE the procedure machine encodes and must never violate: NEVER hand-edit
production outside the pipeline. The whole point is to make the safe path the only reachable path.

# Per-leaf contract (oracle-first)

Each leaf's `verification_command` MUST name its own pre-committed RED oracle as
`python -m pytest tests/overseer/<oracle>.py -q`. Those oracles are the authoritative contracts and
are HAND-AUTHORED + committed BEFORE any leaf is dispatched (that is the next gated step after this
digestion — this epic is decomposition only; nothing is built or dispatched here). NEW modules are
single-file whole-file emissions; integration leaves are existing-symbol edits to ONE file each
(do NOT bundle multiple files into one leaf — multi-file emission is fragile here).

# Suggested decomposition (NON-BINDING — you decide the final tree)

Substrate (NEW, deterministic, stdlib-only, single-file whole-file):
- `overseer/gates.py` → `tests/overseer/test_gates.py`. The pure gate-check functions, each
  returning a typed `GateResult(ok, reason, fix_hint)`: `oracle_is_red(test_path, *, run_seam)`,
  `oracles_committed_at_head(paths, *, git_seam)`, `brief_lint(brief_text)`,
  `plan_preflight(plan, *, state_dir)` (wraps the existing plan_validator),
  `suite_green_zero_reg(report)`, `posture_locked(*, state_dir)`. One lesson per gate.
- `overseer/procedure.py` → `tests/overseer/test_procedure.py`. `Phase`/`Procedure` dataclasses,
  the `PROCEDURE_REGISTRY` (the four mode→ordered-phase definitions above, each phase binding a gate
  by name + a next-action string), and the pure reducer `advance(procedure, phase, gate_result) ->
  Decision` returning the next phase, a `Blocked(reason, fix_hint)`, or `Complete`.
- `overseer/procedure_state.py` → `tests/overseer/test_procedure_state.py`. Durable per-conversation
  phase pointer + recorded gate results (the inbox/outbox of the machine), so state is READ not
  reconstructed and survives `--resume`/restart. New module (avoids new-method edits to session_store).

Enforcement integration (EDIT existing symbols, one file per leaf):
- EDIT `overseer/mode_gate.py::can_switch` → `tests/overseer/test_mode_gate_sequence.py`. The
  mode-switch lock (block all but observe/current while phase != COMPLETE).
- EDIT `overseer/actions.py::dispatch_action` → extend `tests/overseer/test_actions.py`. The
  `(phase, command)` fail-closed check beside the existing `(mode, command)` check.
- EDIT `overseer/mode_prompts.py::render_mode_context` → extend `tests/overseer/test_mode_prompts.py`.
  Render the state-derived phase + last-gate result + single next action.

Runtime wiring (EDIT / NEW, one file per leaf):
- EDIT `overseer/turn_runner.py::run_chat_turn` → extend `tests/overseer/test_turn_runner.py`. Each
  turn: load procedure_state, run the current phase's gate via the injected seams, advance+persist,
  and thread the state into render_mode_context.
- `overseer/procedure_hook.py` → `tests/overseer/test_procedure_hook.py`. The PreToolUse hook
  entrypoint that denies a raw tool call inconsistent with the active phase (the agent-boundary
  hard-block), plus the settings fragment wiring it onto the overseer's claude invocation.

# Deliverables

A decomposed leaf tree (one `brief_hooks_<slug>.md` per leaf, written to repo root) plus an epic
plan record, covering: the deterministic substrate (`overseer/gates.py`, `overseer/procedure.py`,
`overseer/procedure_state.py`), the enforcement integration (edits to `can_switch`,
`dispatch_action`, `render_mode_context`), and the runtime wiring (edit to `run_chat_turn`, the new
`overseer/procedure_hook.py`). Each leaf names its own pre-committed RED oracle under
`tests/overseer/` as its `verification_command`. The end state: the overseer in a procedure-bearing
mode can take ONLY the computed next action, cannot leave the mode until the sequence COMPLETEs
(except aborting to `observe`), and is told the next action every turn. This epic delivers the
DECOMPOSITION only — no oracle is authored and no leaf is built or dispatched here.

# Non-Goals

No new agent spawns, model/API/network/SSE calls, or un-injected subprocesses in the deterministic
leaves. No changes to the harness build pipeline itself, to `harness/**`, or to the autowork daemon.
No procedures for the out-of-scope modes (triage/daemon-supervisor/ui-tester/flag-steward/
harness-self-fix/security-review/rebuild-factory) — substrate-only readiness, no registry entries.
INTEGRATION leaves preserve all existing behaviour and tests. This epic is DECOMPOSITION ONLY: it
authors no oracle and dispatches no build; the owner gate stays paused.
