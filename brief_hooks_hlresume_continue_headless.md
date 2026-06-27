---
working_dir: "/home/xnihil0zer0/JanusMaskJR"
required_task_ids:
  - hlresume-continue-headless-impl
interfaces: "harness/orchestrator.py::spawn_agent — EDIT the EXISTING function (HEAD :353-473). Today the multi-turn session-resume feature (workers.resume_pinned_session, commit b6967b5) appends claude's `--continue` ONLY on the tmux backend (harness/tmux_worker.py::spawn_claude_tmux:376-379). On 2026-06-19 the live claude backend was switched tmux->headless (config.yaml:176 claude_backend: headless), so that resume wiring is now DORMANT: the headless dispatch path (spawn_agent, the non-tmux Popen branch at :463) has NO --continue. FIX, flag-gated default-OFF: add the HEADLESS equivalent so an AST-retry RE-DISPATCH of the same task resumes its prior claude session instead of cold-starting. PURE refactor: when the resume flags are OFF (or any check raises, or no prior transcript exists) the headless argv is BYTE-IDENTICAL to today. Add exactly ONE NEW module-level pure helper `_headless_resume_argv` to harness/orchestrator.py and a minimal guarded EDIT to spawn_agent that appends `--continue` to the built headless `cmd`. harness/orchestrator.py is _NEVER_AUTO_APPROVE trust-core -> an operator decision file at state/control/decisions/hlresume-continue-headless-impl.json is provided (owner pre-approved trust-core edits for the NGv2 closure program)."
---

# Title
Re-wire claude session-resume (`--continue`) onto the HEADLESS backend (headless parity for the dormant tmux-only resume_pinned_session feature)

# Scope
EDIT the EXISTING file `harness/orchestrator.py` (READ it first). SINGLE PRODUCTION FILE plus one NEW
pre-committed oracle under `tests/harness/`. This is the headless-parity follow-on to the multi-turn
resume feature (`workers.resume_pinned_session`, commit `b6967b5`) which today fires ONLY on the tmux
backend (`harness/tmux_worker.py::spawn_claude_tmux:376-379`):

```
if _resume_pinned_session_enabled():
    from harness.orchestrator import _pin_task_cwd_enabled
    if _pin_task_cwd_enabled() and _pinned_session_present(config_dir, work_dir):
        interactive = list(interactive) + ['--continue']
```

On 2026-06-19 the live claude backend was switched `tmux -> headless` (`config.yaml:176`
`claude_backend: headless`), so the resume feature is DORMANT — the headless `-p` dispatch path has no
`--continue` trigger. Add the equivalent to the headless claude invocation so an AST-validation RETRY
re-dispatch of the SAME task (which, with `workers.pin_task_cwd` ON, lands in the SAME deterministic
`work_dir` cwd) resumes its prior claude session (reusing cached context) instead of cold-starting.

THE RESUMABLE SEAM (verified): the headless spawn path is `harness/orchestrator.py::spawn_agent`
(HEAD :353). It builds `cmd = _build_agent_command(agent, resolved_prompt, config)` (:390), jails it
via `agent_jail.build_jail_argv(cmd, ...)` (:413) when sandbox is enabled, then for the headless
backend (the `_use_tmux_claude(agent, config)` branch at :414 is FALSE for headless) reaches the live
`subprocess.Popen(cmd, ...)` at :463. The AST-retry loop re-spawns the SAME agent/round_number/task,
and with `pin_task_cwd` ON `_build_agent_env` (:270) derives the SAME `session_slug` -> SAME
`env['JANUSMASK_WORK_DIR']` -> the headless claude runs with the SAME deterministic cwd
(`cwd=str(Path(env['JANUSMASK_WORK_DIR']))`, :463) every attempt. claude's `--continue` resumes "the
most recent conversation in the current directory", so the SAME cwd is what makes resume re-attach to
the prior turn.

CONFIG-DIR FINDING (load-bearing — read carefully): UNLIKE the tmux path (which seeds an explicit
per-task `CLAUDE_CONFIG_DIR = <work_dir>/.tmuxcfg` at tmux_worker.py:373-374), the HEADLESS path does
NOT set `CLAUDE_CONFIG_DIR` at all. `_build_agent_env` (:303-304) only ALLOWLISTS an ambient
`CLAUDE_*` var through to the child; it never pins one. So headless claude stores/reads its session
transcripts under the config dir it resolves at runtime: `env['CLAUDE_CONFIG_DIR']` when present in the
built env, else the default `~/.claude` (i.e. `os.path.join(env.get('HOME') or os.path.expanduser('~'),
'.claude')`). The resume predicate MUST check THAT directory (the one headless claude actually uses) —
do NOT hardcode `.tmuxcfg` (that is the tmux-only seam). The `_pinned_session_present` predicate
already in `harness/tmux_worker.py` is config-dir-agnostic (it takes `config_dir` as an arg and checks
`<config_dir>/projects/<dir>/*.jsonl`), so REUSE it — import it into orchestrator and pass the
headless config dir.

PREDICATE PARITY (exact predicate set, fail-safe): append `--continue` to the headless `cmd` IFF ALL of:
  1. the backend is headless AND the agent is claude (i.e. NOT `_use_tmux_claude(agent, config)`, and
     `agent == 'claude'`),
  2. `harness.tmux_worker._resume_pinned_session_enabled()` is True,
  3. `_pin_task_cwd_enabled()` is True (resume is meaningless without a stable cwd),
  4. `harness.tmux_worker._pinned_session_present(<headless_config_dir>, <work_dir>)` is True (a prior
     transcript actually exists — otherwise `--continue` ERRORS on a fresh task).
If ANY of these checks raises OR the transcript is absent, do NOT add `--continue` — cold-start,
byte-identical to today's headless behavior. This OFF-safety mirrors how `resume_pinned_session` and
`pin_task_cwd` shipped (default-OFF, fail-safe readers).

Use `--continue` (NOT `--resume <id>`): parity with the tmux design — it resumes the most-recent
session in the pinned cwd/config dir, no session-id capture needed. NEVER emit `--input-format
stream-json` (the GH #3187 hang DO-NOT-BUILD path).

Emit a `__JANUSMASK_PATCHES__` SYMBOL patch against `harness/orchestrator.py` (do NOT emit
`__JANUSMASK_MANIFEST__`). Add exactly:

1. NEW pure module-level helper `_headless_resume_argv(cmd, agent, env, config, *, work_dir) -> list[str]`
   in `harness/orchestrator.py`. It returns a NEW argv list: `cmd` unchanged when resume must not fire,
   or `list(cmd) + ['--continue']` when all predicates hold. It does the work-dir/config-dir
   resolution and the 4-predicate guard, with a TOP-LEVEL `try/except Exception: return cmd` so ANY
   failure (import error, missing key, OSError, anything) falls back to the byte-identical cold-start
   argv. Inside:
     - if `_use_tmux_claude(agent, config)` is True or `agent != 'claude'`: `return cmd` (headless-claude only).
     - lazily `from harness.tmux_worker import _resume_pinned_session_enabled, _pinned_session_present`.
     - if not `_resume_pinned_session_enabled()`: `return cmd`.
     - if not `_pin_task_cwd_enabled()`: `return cmd`.
     - resolve the headless config dir:
       `config_dir = env.get('CLAUDE_CONFIG_DIR') or os.path.join(env.get('HOME') or os.path.expanduser('~'), '.claude')`.
     - if not `_pinned_session_present(config_dir, work_dir)`: `return cmd`.
     - else `return list(cmd) + ['--continue']`.
   Make it idempotent-safe: if `cmd` already ends with / contains `--continue`, still return a single
   `--continue` (e.g. guard `if '--continue' in cmd: return cmd`). Keep it PURE (no Popen, no spawn).

2. EDIT `spawn_agent`: in the HEADLESS branch ONLY — after `cmd` is finalized (post-jail, i.e. AFTER
   the `if agent_jail.sandbox_enabled(config): ... cmd = agent_jail.build_jail_argv(...)` block at
   :396-413) and AFTER the `if _use_tmux_claude(agent, config): ... return ...` early-return at
   :414-416 (so this only runs for the headless path), and BEFORE the `_is_agy` branch / the final
   `subprocess.Popen(cmd, ...)` at :463 — insert exactly ONE statement:
   `cmd = _headless_resume_argv(cmd, agent, env, config, work_dir=env['JANUSMASK_WORK_DIR'])`.
   Place it so it applies to the plain-Popen headless claude spawn (agy is NOT claude, so the helper's
   `agent != 'claude'` guard makes it a no-op for agy regardless of placement — but place it on the
   headless claude path, after the tmux early-return, before the Popen, to keep the diff minimal and
   obviously headless-scoped). Change NOTHING ELSE in `spawn_agent` — env-building, outbox creation,
   `_stage_inbox`, prompt resolution, interceptors, `_build_agent_command`, `_assert_claude_hook_config`,
   jailing, the tmux early-return, the agy branch, stream threads, `record_agent_pid`, and the
   `_ExitedProc`/Popen returns ALL stay byte-identical when the helper returns `cmd` unchanged (the
   default-OFF and fail-safe paths).

Because the new statement only mutates `cmd` (appending `--continue`) right before the headless Popen,
when the flags are OFF / no prior transcript exists / any check raises, `_headless_resume_argv` returns
`cmd` UNCHANGED and the headless spawn is byte-identical to HEAD. PURE refactor of the dispatch wiring.

# Inputs
READ `harness/orchestrator.py`. VERIFIED at HEAD:
- `:353` `def spawn_agent(agent, prompt, config, round_number=1) -> subprocess.Popen` — the headless spawn path; EDIT site.
- `:390` `cmd = _build_agent_command(agent, resolved_prompt, config)` — builds the `-p` argv.
- `:396-413` sandbox block: `cmd = agent_jail.build_jail_argv(cmd, repo_root=..., work_dir=env['JANUSMASK_WORK_DIR'], ...)`.
- `:414-416` `if _use_tmux_claude(agent, config): import harness.tmux_worker; return harness.tmux_worker.spawn_claude_tmux(...)` — tmux early-return (FALSE for headless).
- `:463` `proc = subprocess.Popen(cmd, stdout=..., stderr=..., env=env, start_new_session=True, cwd=str(Path(env['JANUSMASK_WORK_DIR'])))` — the live headless spawn; the new `cmd =` statement goes ABOVE the `_is_agy` branch (:419) or, more precisely, between the tmux early-return (:416) and the `_is_agy` check (:419).
- `:240` `def _pin_task_cwd_enabled() -> bool` — fail-safe flag reader, already module-level in orchestrator.py; the helper calls it directly.
- `:270` `def _build_agent_env(...)` — sets `env['JANUSMASK_WORK_DIR']` (deterministic when pin_task_cwd ON) and allowlists ambient `CLAUDE_*`/`HOME`; CONFIRM it does NOT set `CLAUDE_CONFIG_DIR` for headless (it does not — that is why the helper resolves the default `~/.claude` from `env.get('HOME')`).
- `:4286` `def _use_tmux_claude(agent, config) -> bool` — already module-level; the helper calls it.
- `os` and `Path` are imported at module top of orchestrator.py.
READ `harness/tmux_worker.py`. VERIFIED at HEAD:
- `:305` `def _resume_pinned_session_enabled() -> bool` — fail-safe reader for `workers.resume_pinned_session`; REUSE (lazy import into the helper).
- `:319` `def _pinned_session_present(config_dir, work_dir, *, exists=os.path.exists, listdir=os.listdir) -> bool` — config-dir-agnostic prior-transcript check (`<config_dir>/projects/<dir>/*.jsonl`); REUSE (lazy import into the helper).
- `:376-379` the tmux-only `--continue` injection (the parity reference) — DO NOT EDIT tmux_worker.py.

# Non-Goals
- Do NOT change the tmux backend path (`spawn_claude_tmux`) — it already appends `--continue` correctly; this brief is HEADLESS parity only. Its behavior must stay byte-identical.
- Do NOT build the `--input-format stream-json` resume loop (GH #3187 hang, VERDICT_v3 DO-NOT-BUILD).
- Do NOT pin a new `CLAUDE_CONFIG_DIR` for headless or otherwise change `_build_agent_env`'s env construction — only READ the config dir headless already uses.
- Do NOT edit `overseer/tmux_seams.py` or `harness/tmux_worker.py`.
- Do NOT change behavior when `workers.resume_pinned_session` OR `workers.pin_task_cwd` is OFF, or when no prior transcript exists — the headless argv MUST be byte-identical to HEAD in every such case.
- This is a PURE-argv / predicate unit change. `integration` with a real claude/PTY/subprocess spawn is explicitly out of scope — the oracle tests the pure argv-builder/predicate over seams, never a live spawn (no exec/eval/compile/__import__, no real Popen).

# Deliverables
- An edited `harness/orchestrator.py` adding `_headless_resume_argv` and the one-line guarded `cmd = _headless_resume_argv(...)` injection in the headless branch of `spawn_agent`, byte-identical to HEAD when resume is OFF / no prior transcript / any check raises.
- A NEW pre-committed RED oracle `tests/harness/test_hlresume_continue_headless.py` (>= 2 non-vacuous regression tests) that FAILS against HEAD (helper + injection do not yet exist) and goes GREEN after the impl, asserting:
  (a) headless + resume flags ON + prior transcript present -> built headless claude argv (cmd) CONTAINS `--continue` (and still contains `-p` and the prompt);
  (b) NEGATIVE: resume flag OFF -> NO `--continue` (byte-identical to HEAD);
  (c) NEGATIVE: no prior transcript present -> NO `--continue` (fresh-task safety);
  (d) NEGATIVE: tmux backend path is unchanged (the helper is a no-op / not invoked for tmux);
  (e) WIRED: via `inspect.getsource(harness.orchestrator.spawn_agent)` the resume injection calls `_headless_resume_argv(` on the headless path, and `_headless_resume_argv`'s guard references the 4 predicates (`_use_tmux_claude`/`agent`, `_resume_pinned_session_enabled`, `_pin_task_cwd_enabled`, `_pinned_session_present`).
- The verification_command passes: `python -m pytest tests/harness/test_hlresume_continue_headless.py -q`.

# Required plan shape
Emit EXACTLY TWO tasks forming a RED-PAIR: a `test_authoring` oracle that AUTHORS the RED test FIRST,
and an **implementation** task that makes it green. Do NOT drop the oracle.

CRITICAL DEPENDENCY DIRECTION (matches every landed red-pair): the oracle runs FIRST (it authors the
test file the impl is verified against), so the **implementation task MUST declare
`dependencies: ["hlresume-continue-headless-oracle"]`** and the **oracle MUST declare
`dependencies: []`**. NEVER make the oracle depend on the impl.

FIRST task — the paired RED oracle (`hlresume-continue-headless-oracle`, dependencies: []):
- meta_task_type: test_authoring
- priority: critical
- mutation_target: the dotted module `harness.orchestrator`.
- It AUTHORS `tests/harness/test_hlresume_continue_headless.py` with >= 2 REAL, non-vacuous regression
  tests (no test that passes on an empty/HEAD module). Prefer driving the PURE helper
  `harness.orchestrator._headless_resume_argv(cmd, agent, env, config, work_dir=...)` directly (build a
  minimal `cmd` like `['/opt/claude/bin/claude', '-p', 'BODY']`, a minimal `config` with
  `agents.claude.command` and `workers.claude_backend = 'headless'`, an `env` dict with
  `JANUSMASK_WORK_DIR` and `HOME` pointing into tmp_path), monkeypatching the flag readers and
  `_pinned_session_present`/transcript-on-disk as needed. The oracle MUST prove (a)-(e) from Deliverables.
  For (c) create/omit `<config_dir>/projects/<dir>/*.jsonl` under the resolved headless config dir
  (`env['CLAUDE_CONFIG_DIR']` or `<HOME>/.claude`) OR monkeypatch `_pinned_session_present`. For (d)
  set `config['workers']['claude_backend'] = 'tmux'` (or call with `agent` non-claude) and assert the
  helper returns `cmd` unchanged. Use string/AST/inspect/seam-driven checks — do NOT spawn a real
  claude/PTY/subprocess and do NOT call exec/eval/compile/__import__.
- CRITICAL — EXACT CONFIG-FLAG KEYS (do NOT invent flag-key spellings like `headless_resume`/`resume`/
  `claude_resume`; those are NOT read by anything and will make the positive test fail). The helper
  reuses the EXISTING parity readers, so the test's `config['workers']` dict MUST use these LITERAL keys:
    * `workers.resume_pinned_session` (read by `harness.tmux_worker._resume_pinned_session_enabled` ->
      `cfg['workers']['resume_pinned_session']`) — `True` for warm-resume positive, `False` for the
      resume-OFF negative.
    * `workers.pin_task_cwd` (read by `harness.orchestrator._pin_task_cwd_enabled` ->
      `cfg['workers']['pin_task_cwd']`) — `True` except for the pin-cwd-OFF negative.
    * `workers.claude_backend` = `'headless'` (or `'tmux'` for the tmux-unchanged negative).
  Monkeypatch `harness.orchestrator.load_config` to return this config (BOTH readers resolve
  `load_config` from `harness.orchestrator`, so ONE monkeypatch on `harness.orchestrator.load_config`
  drives `_resume_pinned_session_enabled` AND `_pin_task_cwd_enabled`). In the all-predicates-TRUE
  positive test the resulting argv MUST contain `--continue`; if it does not, the fixture has the WRONG
  flag keys — FIX THE KEYS, do not relax/skip the assertion. This positive assertion is the load-bearing
  RED->GREEN test; it MUST be satisfiable by an impl that reads `workers.resume_pinned_session` +
  `workers.pin_task_cwd`.
- verification_command (BARE, no `cd`): `python -m pytest tests/harness/test_hlresume_continue_headless.py -q`
- MANDATORY: this task carries ZERO `integration_tests` (the plan validator requires that 0
  integration_tests be EXCUSED by a non_goals entry). Its `spec.non_goals` array MUST therefore include
  this EXACT entry verbatim:
  `"No live integration test: this is a pure argv/predicate unit change; no real claude/PTY/subprocess spawn (integration is out of scope)."`
  (the literal substring `integration` in a non_goals array element is what satisfies the validator's
  `missing_integration_test` excuse — plan_validator.py:250-256). regression_tests >= 2.

SECOND task — the implementation (`hlresume-continue-headless-impl`, dependencies: ["hlresume-continue-headless-oracle"]):
- task_id MUST be exactly `hlresume-continue-headless-impl`.
- priority: critical
- meta_task_type: harness_self_fix
- files_touched: ["harness/orchestrator.py"]
- Emit a `__JANUSMASK_PATCHES__` SYMBOL patch with `kind: symbol`, `name: "spawn_agent"`. Put the NEW
  helper `_headless_resume_argv` AND the edited `spawn_agent` BOTH in that single patch's `code` body
  (the existing `spawn_agent` is the R-ANCHOR — co-locating the new top-level helper in the SAME patch
  as the existing anchor symbol lets the AST-merge add the new top-level function without a KeyError on
  a not-yet-existing name).
- OMIT mutation_target on the impl.
- harness/orchestrator.py IS in `_NEVER_AUTO_APPROVE` (trust-core) — an operator decision file at
  `state/control/decisions/hlresume-continue-headless-impl.json` is provided alongside this brief
  (owner pre-approved trust-core orchestrator.py edits for the NGv2 closure program). The factory must
  honor it; do NOT author another.
- verification_command (BARE, no `cd`, BOTH impl and oracle, SAME authored file):
  `python -m pytest tests/harness/test_hlresume_continue_headless.py -q`
- MANDATORY: this impl task carries ZERO `integration_tests`. Its `spec.non_goals` array MUST include
  this EXACT entry verbatim (same as the oracle's):
  `"No live integration test: this is a pure argv/predicate unit change; no real claude/PTY/subprocess spawn (integration is out of scope)."`
  Without a non_goals element containing the literal substring `integration`, the plan validator
  REJECTS the plan with `missing_integration_test` (plan_validator.py:250-256). regression_tests >= 2.
- IMPORTANT: BOTH tasks (oracle AND impl) MUST each carry the `integration`-excuse non_goals entry
  above — the validator checks EVERY task's own non_goals independently; an excuse on the oracle does
  NOT cover the impl.
