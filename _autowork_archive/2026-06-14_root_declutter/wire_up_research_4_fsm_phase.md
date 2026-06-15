# WIRE-UP PHASE Research: Overseer Gated-Procedure FSM + P6 Hook

Research target: design a `WIRE_UP` phase as a new phase in the build-lifecycle FSM that
HARD-BLOCKS a build from being marked DONE until wiring (live reachability / non-orphan)
is verified. All citations are `file:line` in `/home/xnihil0zer0/JanusMaskJR`.

NOTE: per-MEMORY, the procedure machinery lives in the repo-root `overseer/` package,
NOT `gates/procedure/` (that path does not exist). Files: `overseer/procedure.py`,
`overseer/procedure_state.py`, `overseer/gates.py`, `overseer/gate_runner.py`,
`overseer/procedure_hook.py`, `overseer/actions.py`, `overseer/mode_gate.py`,
`overseer/mode_prompts.py`, `overseer/turn_runner.py`.

---

## 1. The procedure-gate FSM (`overseer/procedure.py`)

### Core types
- `Phase(name, gate, next_action)` frozen dataclass — `procedure.py:26-36`. `gate` is the
  STRING NAME of a gate resolved against `overseer.gates`; `next_action` is the single
  human-readable instruction surfaced while in that phase.
- `Procedure(mode, phases: List[Phase])` — `procedure.py:38-42`.
- `Blocked(reason, fix_hint)` — `procedure.py:44-48` (terminal-for-now: gate failed).
- `Complete` singleton (`_Complete`) — `procedure.py:50-64` (passing gate on LAST phase).
- `Decision = Union[str, Blocked, _Complete]` — `procedure.py:65`.

### The pure reducer `advance(procedure, phase, gate_result)` — `procedure.py:68-88`
- gate failed (`not gate_result.ok`) → `Blocked(reason, fix_hint)` (`:80-81`).
- gate passed, not last phase → NEXT phase's `.name` (a `str`) (`:82-88`).
- gate passed, last phase → `Complete` (`:87-88`).
- unknown `phase` → `ValueError` (`:84-86`).
No I/O, no spawning — pure data + logic.

### `PROCEDURE_REGISTRY` — phases per mode (`procedure.py:66`)
| mode | phases (name : gate) |
|---|---|
| `brief-author` | SCOPE:`scope_locked` → ORACLE:`oracle_present` → COMMIT:`oracle_committed` → BRIEF:`brief_written` → PLAN:`plan_ready` |
| `oracle-author` | SCOPE:`scope_locked` → DRAFT:`oracle_drafted` → RED:`oracle_is_red` → COMMIT:`oracle_committed` |
| `dispatch` | PREFLIGHT:`preflight_clean` → STAGE:`staged` → BUILD:`built` → VERIFY:`verified` → RESTORE:`restored` |
| `push` | SWEEP:`swept` → ZERO_REG:`registry_zeroed` → POSTURE:`posture_ok` → PUSH:`pushed` |
| `daemon-supervisor` | OBSERVE:`daemon_observed` → HEALTH:`daemon_healthy` → RECONCILE:`reconciled` → REPORT:`reported` |

### COMPLETE / observe=abort semantics
- COMPLETE is the terminal of `advance` on the last phase (`procedure.py:87-88`); persisted
  as the literal phase string `'COMPLETE'` by `turn_runner.run_chat_turn` (`turn_runner.py:309`).
- The mode-switch lock (`mode_gate.can_switch`, `mode_gate.py:164-203`): while a procedure
  is in a NON-terminal phase, EVERY mode switch is withheld except `observe` (abort) or
  staying on `current` (no-op) — `mode_gate.py:181-183`. Terminal-phase detection
  (`_is_phase_terminal`, `mode_gate.py:141-163`): terminal when phase is `None`, the literal
  `'COMPLETE'`, or the `overseer.procedure.Complete` sentinel; only then do the lattice tier
  rules resume (`mode_gate.py:184-203`). `observe` is the abort baseline and is always
  reachable (`mode_gate.py:186-187`).
- Durable state: `ProcedureState(phase, last_gate)` read FROM DISK never reconstructed
  (`procedure_state.py:19-23`), per-conversation JSON under
  `state_dir/state/procedures/<cid>.json` (`procedure_state.py:25-27`), unknown conversation
  loads fresh `DEFAULT_PHASE='BRIEF'` (`procedure_state.py:17,41-52`). `load_state`/`save_state`
  at `:41-60`.

### Gate resolution (`overseer/gate_runner.py`)
`make_default_gate_runner(repo_root, state_dir, ...)` returns `gate_runner(mode, phase, rec, state_dir)`
(`gate_runner.py:80,147-152`). It resolves the phase's gate label (`gate_label_for`, `:20-28`),
gathers inputs from `rec['procedure_artifacts']` + injected pytest/git/status/pending/pushed
seams (`:33-78`), and runs the real `overseer.gates` function (`_run_gate`, `:88-145`).
- `verified` → `suite_green_zero_reg(report)` (`gate_runner.py:121-125`) where the report
  carries `oracle_green` + `new_regressions` (`gates.py:116-124`). THIS is the existing
  "is the build good" gate in the `dispatch` procedure — and the natural neighbor of a
  wire-up gate.
- Backed gates with no recorded artifact fail-LOUD with an actionable hint (`_missing`, `:30-31`).
- `_ATTESTED_LABELS` (`:18`) are judgment gates that pass only on
  `rec['procedure_attested'][phase]` (`:141-144`).

---

## 2. The P6 PreToolUse hard-block hook (`overseer/procedure_hook.py`)

### Decision core
- Pure, stdlib-only; maps `(tool_name, tool_input, phase)` → allow/deny. Never executes the
  tool, never spawns, never network (`procedure_hook.py:1-30`).
- `_PHASE_ORDER` (`:33`): `('SCOPE','ORACLE','RED','COMMIT','BRIEF','PLAN','BUILD','SUITE','GREEN','POSTURE','REVIEW')`
  — note this is a SUPERSET/flattened ordering across modes used only for the boundary
  block's monotonic "is phase X before marker Y" comparisons; it is NOT the per-mode registry.
- `_GATE_PHASE` (`:34`) maps gate label → phase marker.
- `_TERMINAL_PHASES` (`:35`): `{'', 'NONE', 'COMPLETE', 'DONE', 'IDLE', 'CLOSED'}` → hook
  inert (`_phase_of`, `:39-55`).
- `_READ_ONLY_TOOLS` (`:36`) always allowed (`_verdict`, `:111-112`).
- `_verdict(tool_name, tool_input, phase)` (`:100-123`): fail-CLOSED. No active phase → allow
  (inert, `:108-109`). `Write` to a `brief_hooks_*` path before BRIEF → DENY (`:113-119`).
  git-commit proxy before oracle is RED → DENY (`:120-122`).
- `evaluate` (`:125-148`) returns `(allow, reason)`; `decide` (`:150-174`) returns the Claude
  Code PreToolUse decision dict.

### env-phase fallback in `decide` — `procedure_hook.py:166-174`
Phase resolved from event first (`event['phase']` / `event['state']` /
`event['procedure_state']`), then falls back to `os.environ.get('JANUSMASK_PROCEDURE_PHASE')`
(`:170`). Real Claude Code PreToolUse events carry NO phase → the env var is the live channel.
An explicit event phase always wins; with neither present the hook is inert (fail-open per `:108`).

### rc=2 hard-block
`main()` (`:177-189`): reads event JSON on stdin, emits decision JSON on stdout, and returns
`2` when `decision['decision'] == 'block'` (`:187-188`). Claude Code treats a PreToolUse hook
exit-2 as a HARD BLOCK of the tool call.

### How `make_seams` registers the hook (`overseer/turn_runner.py`)
`SETTINGS_FRAGMENT` (`procedure_hook.py:175`):
```json
{"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "python -m overseer.procedure_hook"}]}]}}
```
- `make_seams` writes `SETTINGS_FRAGMENT` to `work_dir/.claude/settings.json`
  (`turn_runner.py:136-141`). NO argv / jail-bind change.
- `_build_overseer_env` sets `CLAUDE_PROJECT_DIR = work_dir` (`turn_runner.py:88`); the
  `runner` spawns with `cwd=work_dir` (`turn_runner.py:230`). Claude Code auto-discovers
  project hooks from `$CLAUDE_PROJECT_DIR/.claude/settings.json`, so the hook fires with no
  argv change (`turn_runner.py:114-124`).
- `env_builder` exports the LIVE phase: it reads `conversation['procedure_phase']` and, when
  truthy, sets `env['JANUSMASK_PROCEDURE_PHASE']` (`turn_runner.py:218-223`). Observe /
  non-procedure modes carry no phase → env var unset → spawn byte-for-byte unchanged.
- `run_chat_turn` populates `rec['procedure_phase']` BEFORE the spawn (`turn_runner.py:316`),
  closing the loop: gate → advance → persist → thread phase into rec → env exports it → hook
  reads it.

---

## 3. FSM wiring into chat/build runtime (`overseer/turn_runner.py`)

`run_chat_turn(store, cid, user_text, *, config, repo_root, state_dir, logs_dir, ...,
gate_runner=None, ...)` (`turn_runner.py:254-373`).

Per-turn procedure wiring (`turn_runner.py:287-327`), additive — a mode with no bound
procedure is a complete no-op:
1. resolve `mode = rec['current_mode']` (`:285`); if `mode in PROCEDURE_REGISTRY` (`:299`):
2. `load_state(cid)` → `phase` (default first phase) (`:301-302`).
3. if `gate_runner` injected: `gr = gate_runner(mode, phase, rec, state_dir)` (`:304`),
   `dec = advance(proc, phase, gr)` (`:305`), persist new state — next phase / `'COMPLETE'` /
   hold-on-Blocked (`:306-313`).
4. thread guidance into rec: `rec['procedure_phase']` (`:316`), `rec['procedure_next_action']`
   (the matched phase's `.next_action`, `:318-322`), `rec['procedure_last_gate']` (`:323-327`).

`render_mode_context(mode, state)` (`overseer/mode_prompts.py:57-97`) renders the
SessionStart-style block. When `state['procedure_phase']` is truthy it appends `Current phase:`,
`Next action:`, and — only when the last gate FAILED — `Last gate: FAILED -- <reason>` +
`Fix hint: <hint>` (`mode_prompts.py:85-95`). This is how the COMPUTED next action surfaces in
the agent's system prompt EVERY turn.

`dispatch_action(mode, command, args, *, seams, phase, phase_policy)` (`overseer/actions.py:33-81`):
TWO fail-closed checks before any seam fires: (mode,command) authority (`:64-68`) then the
additive (phase,command) sequence-lock against `PHASE_COMMAND_POLICY` (`:72-78`). A command not
sanctioned by the active phase raises `ModeViolation` BEFORE any seam resolves (zero side
effects on rejection).

mode-set procedure-lock = `mode_gate.can_switch` (`mode_gate.py:164-203`, see §1).

---

## 4. Where a WIRE_UP phase slots

The build lifecycle is the **`dispatch` mode procedure**:
`PREFLIGHT → STAGE → BUILD → VERIFY → RESTORE` (`procedure.py:66`).
- `VERIFY`:`verified` runs `suite_green_zero_reg` (oracle GREEN + zero new regressions,
  `gates.py:116-124`). This proves the oracle passes but NOT that the new module is REACHABLE
  on a live path — exactly the "IMPLEMENTATION ≠ WIRED" defect from MEMORY (unit-green
  isolated oracle, zero live importers).
- `RESTORE`:`restored` cleans the workspace and is the LAST phase → its pass yields `Complete`
  (DONE).

So the wire-up check is a NEW PHASE INSIDE the `dispatch` procedure, inserted **between VERIFY
and RESTORE** — i.e. a build cannot reach RESTORE/`Complete` (DONE) until wiring is proven.
It is NOT a separate mode: the build-lifecycle FSM is `dispatch`, and the reducer's terminal
(`Complete`) is what "DONE" means; gating DONE means inserting a phase before the terminal.

There is ALSO an integrate-time chokepoint worth a defense-in-depth second gate:
`harness/orchestrator_worker._print_json_line` → `_reap_spent_briefs_safe` (the brief reaper)
fires on `outcome in ('accepted','no_diff')` (`orchestrator_worker.py:55,73-79`). This is the
pipeline's actual "task integrated / DONE" signal (separate from the overseer chat FSM). A
wire-up assertion can be wired here too so daemon-driven builds (no overseer chat) are also
guarded. RECOMMENDATION: primary gate = the `dispatch` FSM WIRE_UP phase; defense-in-depth =
an integrate-time orphan check at the worker accept chokepoint.

---

## RECOMMENDED WIRE_UP PHASE FSM

### (a) FSM states / phase
Add ONE phase to the `dispatch` Procedure between VERIFY and RESTORE
(`procedure.py:66`), binding a NEW gate label `wired`:

```python
'dispatch': Procedure(mode='dispatch', phases=[
    Phase('PREFLIGHT', 'preflight_clean', 'Confirm the workspace is preflight-clean.'),
    Phase('STAGE',     'staged',          'Stage the target files for the worker.'),
    Phase('BUILD',     'built',           'Synthesize the implementation.'),
    Phase('VERIFY',    'verified',        'Verify the build against the oracle.'),
    Phase('WIRE_UP',   'wired',           'Prove the new module is reachable on a live '
                                          'import/call path (not an orphan).'),
    Phase('RESTORE',   'restored',        'Restore the workspace to a clean state.'),
]),
```

The reducer (`advance`, `procedure.py:68-88`) needs NO change — it walks the phase list
generically. The "internal" wire-up state machine
`UNVERIFIED → WIRING_CHECK_RUN → WIRED | ORPHANED` maps cleanly onto the existing
GateResult contract:
- `UNVERIFIED` / `WIRING_CHECK_RUN` = phase is WIRE_UP with no `wired` artifact recorded yet
  → gate returns `_missing(...)` (fail-loud, hold phase).
- `WIRED` = gate `ok=True` → `advance` emits next phase `RESTORE`.
- `ORPHANED` = gate `ok=False` → `advance` emits `Blocked(reason, fix_hint)` → phase HELD,
  build cannot reach RESTORE/`Complete`.

### (b) The `wired` gate (NEW in `overseer/gates.py`) + runner handler
Add a pure gate mirroring the existing style (`gates.py`, `__all__` at `:18`):

```python
def wired(report: Mapping[str, Any]) -> GateResult:
    """Assert the just-built module is reachable on a live import/call path.

    Expects a wiring report:
      target: the module/symbol just built (str)
      live_importers: count of NON-TEST, NON-ORACLE modules that import/reference target (int)
      reachable: optional explicit bool the caller may set
    A target with zero live importers is an ORPHAN -- unit-green but never reached.
    """
    target = str(report.get('target', '') or '')
    if not target:
        return GateResult(False, 'no wiring target recorded', 'Record the built module/symbol.')
    if report.get('reachable') is True:
        return GateResult(True, '', '')
    importers = int(report.get('live_importers', 0) or 0)
    if importers <= 0:
        return GateResult(
            False,
            f'{target!r} has zero live importers -- it is an ORPHAN (unit-green but never '
            f'reached on any live path)',
            'Wire the module into a live caller/route (not just its oracle) and re-run the '
            'wiring check; a green isolated oracle does not prove reachability.')
    return GateResult(True, '', '')
```

Runner handler in `gate_runner.py:_run_gate` (alongside the `verified` branch, `:121-125`):

```python
if label == 'wired':
    report = arts.get('wiring_report')
    if report is None:
        return _missing('wiring report',
                        'Run the orphan/import-reachability check + record the wiring_report '
                        '(target + live_importers).')
    return wired(report)
```

The live-importer count seam should reuse repo grep/AST (e.g. count non-test, non-`oracle`,
non-`brief_hooks_*` modules importing/referencing the target) — implementable as a default
seam in `gate_runner.make_default_gate_runner` next to `_default_run_seam` (`:33-40`), keeping
gates pure and I/O in the seam.

### (c) How it HARD-BLOCKS "DONE" if ORPHANED
1. **FSM block (primary).** WIRE_UP precedes RESTORE; RESTORE's pass is the only path to
   `Complete` (`advance` last-phase branch, `procedure.py:87-88`). An ORPHANED `wired` gate →
   `Blocked` → `run_chat_turn` HOLDS the phase (`turn_runner.py:310-311`) and never advances to
   RESTORE, so `Complete`/DONE is unreachable. The mode-switch lock keeps `dispatch` engaged
   (only `observe` abort or no-op allowed, `mode_gate.py:181-183`) so the operator cannot
   side-step into another mode to "mark done".
2. **P6 boundary block (defense).** Extend `procedure_hook._PHASE_ORDER` (`:33`) to include
   `WIRE_UP` after `GREEN`, add `'wired': 'WIRE_UP'` to `_GATE_PHASE` (`:34`), and add a
   `_verdict` rule (`:100-123`): while active phase is before WIRE_UP-satisfied, DENY any
   commit-proxy / push / "mark-done" tool — so a raw tool call cannot bypass `dispatch_action`
   to commit an orphan. Phase is delivered via `JANUSMASK_PROCEDURE_PHASE` (already wired,
   `turn_runner.py:218-223`); rc=2 hard-block already in `main` (`:187-188`). Crucially: keep
   `'DONE'` OUT of any allow-list interpretation — note `'DONE'` is in `_TERMINAL_PHASES`
   (`:35`) meaning "no procedure active", so the gate must run BEFORE phase reaches a terminal
   sentinel (it does: WIRE_UP is non-terminal).
3. **Integrate-time defense (daemon path).** At `_reap_spent_briefs_safe`
   (`orchestrator_worker.py:45-72`), before treating `outcome=='accepted'` as integrated, run
   the same orphan check on the task's target; an ORPHAN routes to `_mark_blocked(...,
   'orphan_unwired')` (mirroring `auto_commit_failed`, `orchestrator_worker.py:491`) instead of
   reaping the brief — so daemon builds (no overseer chat FSM) are also blocked from DONE.
   Gate behind a default-off config flag (mirroring `autowork.archive_spent_briefs`,
   `orchestrator_worker.py:59`) for safe rollout.

### (d) How it surfaces the COMPUTED next action each turn
No new surfacing code needed — the existing `next_action` threading carries it:
- `run_chat_turn` matches the active phase in `proc.phases` and writes its `.next_action` into
  `rec['procedure_next_action']` (`turn_runner.py:318-322`). For WIRE_UP that string is
  "Prove the new module is reachable on a live import/call path (not an orphan)."
- On an ORPHANED gate, `advance` returns `Blocked` and the phase is held with `last_gate` set
  (`turn_runner.py:310-313`); `render_mode_context` appends `Current phase: WIRE_UP`,
  `Next action: ...`, `Last gate: FAILED -- <orphan reason>`, `Fix hint: Wire the module into a
  live caller...` (`mode_prompts.py:85-95`) into the agent's system prompt every turn.
- This is byte-identical to how every existing phase surfaces its computed next action —
  WIRE_UP inherits the behavior purely by being a registry `Phase` with a `next_action` string.

### Oracle / wiring note (process)
Per MEMORY's "Oracles MUST assert wiring" and "NEW top-level symbol → R-ANCHOR" lessons:
the new `wired` gate must itself be wired (added to `gates.__all__` `:18` and dispatched in
`gate_runner._run_gate`), and the RED oracle must assert the `dispatch` registry contains a
`WIRE_UP` phase before RESTORE AND that `advance` yields `Blocked` on a zero-importer report —
i.e. assert the WIRING, not just the isolated gate function.

### Summary of edit sites
| change | file:anchor |
|---|---|
| add `WIRE_UP` Phase to `dispatch` | `overseer/procedure.py:66` (PROCEDURE_REGISTRY) |
| add `wired` gate fn + `__all__` | `overseer/gates.py:18,116` (near `suite_green_zero_reg`) |
| add `wired` runner branch + default importer seam | `overseer/gate_runner.py:121` and `:33-40` |
| extend P6 hook phase order + deny rule | `overseer/procedure_hook.py:33,34,100-123` |
| integrate-time orphan block (daemon path) | `harness/orchestrator_worker.py:45-72` |
| (no change) reducer / surfacing / state | `procedure.py:68-88`, `turn_runner.py:318-327`, `mode_prompts.py:85-95` |
