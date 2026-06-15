# HANDOFF PROMPT — Execute P6: register the overseer PreToolUse hard-block hook

> ## ✅ DONE 2026-06-09 (UNPUSHED, posture restored)
> All handoff claims verified accurate against source. Both leaves built oracle-first
> via the single-task pipeline, 0 new regressions (overseer suite 349→357 pass).
> - **P6a** oracle `16e5c1f` → impl `952cba1` (`decide` falls back to
>   `JANUSMASK_PROCEDURE_PHASE`; worker used a function-local `import os`).
> - **P6b** oracle `b2fd861` → impl `6c011a5` (`make_seams` writes
>   `work_dir/.claude/settings.json` = `SETTINGS_FRAGMENT`; `env_builder` exports the
>   live `conversation['procedure_phase']`; MCP/jail wiring byte-for-byte).
> - **End-to-end proven**: a real `run_chat_turn` (brief-author, phase seeded SCOPE,
>   gate held) → `run_turn` → `make_seams`' real `env_builder` exported
>   `JANUSMASK_PROCEDURE_PHASE=SCOPE`; the literal `python -m overseer.procedure_hook`
>   subprocess (risk #1 — `python` resolves on PATH) BLOCKED a `brief_hooks_*` Write
>   (rc=2 deny), allowed a Read, and stayed inert in observe mode (no phase exported).
> - Posture unchanged: `orchestrator.flag=pause`, `full_stop` absent, allowlist
>   deny-all, no daemon/worker. Plans archived to
>   `_autowork_archive/2026-06-09_p6_hook_registration/`. Awaiting owner push sign-off.

Paste everything below into a fresh Claude Code session at `/home/xnihil0zer0/JanusMaskJR`.

---

## 0. Mission

Make the overseer's **PreToolUse hard-block hook** actually fire, so out-of-order
*tool calls* are WITHHELD at the tool boundary (e.g. a `Write` to `brief_hooks_*`
before the oracle is committed is denied). The hook logic is already built and
unit-tested in `overseer/procedure_hook.py`; it is simply **not registered into
the live overseer spawn, and cannot see the procedure phase**. Two small leaves,
oracle-first, owner-gated. Neither touches a deny-listed path.

This completes the procedure-gates epic. The rest of it is already LIVE (built
2026-06-08, commits `17973b2..9886c7b`): `gate_runner.py` resolves each phase's
gate-label to a real `overseer/gates.py` check, `procedure_artifacts.py` +
`turn_runner` capture artifacts each turn, `service.py` builds+passes the
gate_runner so the FSM steps every turn, and `mode_set` locks mid-procedure mode
switches. P6 is the only remaining piece.

## 1. Why it doesn't work today (verified facts)

`overseer/procedure_hook.py` already exposes:
- `decide(event) -> {'decision': 'allow'|'block', ...}` — the PreToolUse entry.
- `main()` — a stdin→decision CLI shim (`python -m overseer.procedure_hook`).
- `SETTINGS_FRAGMENT = {'hooks': {'PreToolUse': [{'matcher': '*', 'hooks':
  [{'type': 'command', 'command': 'python -m overseer.procedure_hook'}]}]}}`.
- `_verdict(tool_name, tool_input, phase)` / `_phase_of(state)` — the policy:
  before the `BRIEF` phase a `brief_hooks_*` write is denied, read-only tools and
  terminal phases (`''`,`COMPLETE`,...) pass, etc.

**Gap 1 — the hook can't see the phase.** `decide` reads the phase only from the
event (`event.get('phase') or event.get('state') or event.get('procedure_state')`).
Real Claude Code PreToolUse events carry `tool_name`/`tool_input`/`cwd` — **never**
the procedure phase. So as-registered the hook runs with `phase=None` and is inert.

**Gap 2 — nothing registers the hook into the spawn.** `overseer/turn_runner.make_seams`
builds the claude argv + jail but never writes a settings.json or otherwise wires
the hook into the spawn. (Confirmed: `grep -n "settings\|hooks\|SETTINGS" overseer/turn_runner.py` → nothing.)

## 2. The design (low-risk; do NOT touch the jail argv)

KEY FACT that avoids a `--settings`/jail-binding change: `_build_overseer_env`
(in `overseer/turn_runner.py`) already sets `CLAUDE_PROJECT_DIR = str(work_dir)`,
and `make_seams`'s `runner` spawns claude with `cwd=work_dir`. Claude Code
auto-discovers project hooks from `$CLAUDE_PROJECT_DIR/.claude/settings.json`.
So **writing `SETTINGS_FRAGMENT` to `work_dir/.claude/settings.json` registers the
hook with NO argv change and NO new jail bind** (work_dir is already bound into
the jail and is the cwd). The hook subprocess inherits the spawn env (so it sees
`JANUSMASK_PROCEDURE_PHASE`) and `PYTHONPATH` already includes `repo_root` (so
`python -m overseer.procedure_hook` resolves).

ALSO VERIFIED: `overseer/driver.run_turn(conversation, ...)` calls
`env_builder(conversation, **kw)` where `conversation` IS the `rec` from
`run_chat_turn` — and the procedure loop sets `rec['procedure_phase']` BEFORE
`run_turn`. So `env_builder` can read the live phase off `conversation`.

### Leaf P6a — `overseer/procedure_hook.py` reads the phase from env
Make `decide` fall back to `os.environ.get('JANUSMASK_PROCEDURE_PHASE')` when the
event has no phase. Add `import os` (the module currently imports only `re`,`json`).
Exact change: in `decide`, replace the phase resolution with
`phase = event.get('phase') or event.get('state') or event.get('procedure_state') or os.environ.get('JANUSMASK_PROCEDURE_PHASE')`.
- **Build shape:** NEW-ish import + one symbol edit → **whole-file emission** is
  safest for this ~180-line module (avoids import-block partial-edit fragility).
- **Oracle** `tests/overseer/test_procedure_hook_env_phase.py`:
  - With `monkeypatch.setenv('JANUSMASK_PROCEDURE_PHASE','SCOPE')` and event
    `{'tool_name':'Write','tool_input':{'file_path':'brief_hooks_x.md'}}` (no
    `phase` key) → `decide(event)['decision'] == 'block'`.
  - Event `phase` still WINS when present: same event with `phase='COMPLETE'` in
    the event → allow, even with env=`SCOPE`.
  - Env unset + no event phase → allow (inert, fail-open) for that write.
  - A read-only tool (`{'tool_name':'Read',...}`) → allow regardless.

### Leaf P6b — `overseer/turn_runner.py` registers the hook + exports the phase
Edit `make_seams` only:
1. **env_builder**: after `env = _build_overseer_env(...)`, add
   `phase = (conversation or {}).get('procedure_phase')` and, if truthy,
   `env['JANUSMASK_PROCEDURE_PHASE'] = str(phase)`. (Currently `env_builder`
   ignores `conversation` and returns `_build_overseer_env(...)` directly.)
2. **settings file**: write `json.dumps(procedure_hook.SETTINGS_FRAGMENT)` to
   `work_dir/.claude/settings.json` (mkdir parents, fail-safe under `OSError`).
   Do it once in `make_seams` (it has `work_dir`) or inside `runner` before the
   Popen. Import `procedure_hook` locally.
   - **Do NOT modify `jail_builder`'s argv, the MCP token logic, the
     `build_jail_argv(... extra_ro=mcp_ro_list, extra_rw=mcp_rw_list)` call, or
     `bind_credentials=True` — keep all of that byte-for-byte.**
- **Build shape:** two small partial edits inside `make_seams` (env_builder
  closure + a write). `make_seams` is large (~120 lines) → if a single-symbol
  patch of `make_seams` AST-truncates, SPLIT: do the env_builder phase-export as
  its own pass first, then the settings-write. `overseer/turn_runner.py` is NOT
  deny-listed (the MCP-wire and P3 leaves edited it via `data_model`) → no
  decision file.
- **Oracle** `tests/overseer/test_make_seams_hook_registration.py` (deterministic,
  no real spawn — call `make_seams(config=..., repo_root=tmp, state_dir=tmp/state,
  work_dir=tmp/wd)` and exercise the returned seams):
  - `env_builder({'procedure_phase':'ORACLE'})['JANUSMASK_PROCEDURE_PHASE']=='ORACLE'`;
    `env_builder({})` has no such key (fail-safe when absent).
  - After constructing the seams (or after one `env_builder`/`runner` call,
    whichever you choose as the write site — pick `make_seams` body so it's
    unconditional), `json.loads((work_dir/'.claude'/'settings.json').read_text())
    == procedure_hook.SETTINGS_FRAGMENT`.
  - Regression: `jail_builder(['claude','-p','--tools','Read'])` is unchanged
    vs. today (no `--settings` token added); the MCP path still works.

## 3. The pipeline recipe (proven this project — follow exactly)

For EACH leaf, oracle-first:
1. **Hand-author the RED oracle** under `tests/overseer/`. Run it; confirm RED for
   the right reason (ImportError / contract mismatch, not a typo).
2. **`git commit` the oracle BEFORE dispatch** (the gate verifies from HEAD in a
   staging worktree; an uncommitted oracle is invisible → rollback). End commit
   messages with the `Co-Authored-By: Claude Opus 4.8 (1M context)` trailer.
3. **Hand-build a one-task plan** (clone the schema from `plan_hooks_wire_overseer_mcp.json`).
   Set `meta_task_type: data_model`, `files_touched`, `verification_command` =
   your committed oracle (+ an existing regression oracle), and for a NEW-file or
   small module put the FULL intended source in `spec.implementation_notes` after
   a `NEW module -> emit the COMPLETE file verbatim` line; for an EDIT describe the
   exact insertion structurally. Then:
   `python` →
   `from harness.planner import plan_normalizer, plan_validator`;
   `plan = plan_normalizer._inject_oracle_sources(plan, repo_root='.')`;
   `json.dump(plan, open(out,'w'), indent=2)`;
   `plan_validator.validate_plan(out)` MUST return `[]`.
   - **Validator ratio rules (these bit me — satisfy them up front):**
     `len(unit_tests) >= len(spec.functional_requirements)`;
     `minimum_test_count >= 1.5 * len(functional_requirements)`;
     `>= 2` entries in `regression_tests`+`property_tests` (edge cases);
     `>= 1 integration_test` UNLESS an entry in `spec.non_goals` contains the word
     "integration"; `token_budget_ratio.test_tokens >= 1.5 * implementation_tokens`.
     Easiest: keep `functional_requirements` to 2-3 and split your oracle's tests
     across unit/integration/regression to clear the ratios.
4. **Stage + build (single-task worker — ignores full_stop/flag/allowlist, so the
   safe posture stays locked):**
   `from harness.planner import staging; staging.stage_task(Path(plan), task_id,
   Path('state'), canonical=True, working_dir='/home/xnihil0zer0/JanusMaskJR')`
   then
   `python -m harness.orchestrator_worker --state-dir state --task-id <id> --config harness/config.yaml`
   (run it backgrounded; watch `state/impl_progress.jsonl` for `accepted`/`auto_commit`
   vs `rejected`/`verification_failed`). Run all the above python with
   `PYTHONPATH=/home/xnihil0zer0/JanusMaskJR` (or `cd` there) or imports fail.
5. **On a non-deterministic miss:** clean ALL stale state for the id
   (`find state -name '*<id>*' -delete` — the `state/output/<id>.patches.json`
   sidecar REPLAYS the bad submission and overrides a re-stage), harden
   `implementation_notes` with the exact contract, re-stage, re-dispatch.
6. **Verify:** named oracle green + `python -m pytest tests/overseer/ -q` shows 0
   new regressions (baseline at handoff = **349 passed, 0 failed**).

Order: P6a first (so the hook can read the env), then P6b. After both: a
procedure-mode turn whose agent tries a `brief_hooks_*` Write before the COMMIT
phase is denied at the tool boundary.

## 4. Risks / gotchas to watch

- **`python` inside the jail.** `SETTINGS_FRAGMENT`'s command is the literal
  `python -m overseer.procedure_hook`. Verify `python` is on PATH inside the bwrap
  jail and resolves the module (PYTHONPATH already carries `repo_root`, and
  `repo_root` is bound ro). If `python` isn't found, the lowest-risk fix is to make
  the command `python3` or an absolute interpreter — but that is a SEPARATE small
  edit to `procedure_hook.SETTINGS_FRAGMENT` with its own oracle; do not silently
  change it inside P6b.
- **Keep MCP wiring byte-for-byte** in `make_seams` (tokens, `extra_ro`/`extra_rw`,
  `bind_credentials`). The oracle's jail_builder regression test guards this.
- **Fail-safe phase.** When `conversation` has no `procedure_phase` (observe / no
  procedure), export NO `JANUSMASK_PROCEDURE_PHASE` and the hook stays inert — the
  spawn must behave exactly as today for non-procedure modes.
- **Do NOT flip enable flags or push.** Posture at handoff: `full_stop` absent
  (owner-authorized removal — see `[[triple-lock-was-claude-invented]]`),
  `state/control/orchestrator.flag=pause`, allowlist deny-all, no daemon/worker.
  Leave it that way; report unpushed SHAs for owner push sign-off.
- **Memory to read first:** `[[overseer-pillars-and-fsm-wired]]` (this session's
  full state + the exact gate_runner/artifact design), `[[implementation-is-not-wired-defect]]`
  (oracles MUST assert wiring/reachability, not just unit behavior — your P6b
  oracle asserting the settings file is written + env exported is exactly this),
  `[[never-hand-edit-production-outside-pipeline]]`.

## 5. Done criteria
- `tests/overseer/test_procedure_hook_env_phase.py` + `test_make_seams_hook_registration.py`
  green and committed; `tests/overseer/` 0 new regressions vs 349/0.
- `work_dir/.claude/settings.json` carries `SETTINGS_FRAGMENT` on a real turn and
  `JANUSMASK_PROCEDURE_PHASE` is exported with the live phase.
- Brief updated / status noted; unpushed SHAs reported; posture restored.
