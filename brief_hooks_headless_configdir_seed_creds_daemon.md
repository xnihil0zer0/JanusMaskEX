---
slug: headless_configdir_seed_creds_daemon
working_dir: "/home/xnihil0zer0/AI-Data/JanusMaskEX"
complexity_score: medium
required_task_ids:
  - headless-configdir-seed-creds-daemon-impl
  - headless-configdir-seed-creds-daemon-oracle
---

# Title

Make the headless-backend `CLAUDE_CONFIG_DIR` seed in `harness/autowork_daemon.py`
COPY the operator's claude OAuth credentials into the per-spawn config dir,
reusing the already-tested `overseer.tmux_seams.seed_config_dir` copy logic.
(Sibling of the orchestrator fix; same defect, the daemon's duplicate seed.)

# Background

`harness/autowork_daemon.py::_seed_claude_config_dir` (line 1221, consumed via
`_build_worker_env` line 1300) is a near-duplicate of the orchestrator seed: its
claude branch `config_dir.mkdir(...)` (lines 1278-1283) creates an EMPTY
`.claude_config` and returns `{'CLAUDE_CONFIG_DIR': str(config_dir)}` with no
credential copy. So daemon-spawned worker claude processes start "Not logged in"
under the headless backend. Verified live: a creds-less `CLAUDE_CONFIG_DIR` →
claude rc=1 "Not logged in"; the SAME dir seeded via tmux_seams copy → rc=0 "OK".

# Scope

TRUST-CORE: `harness/autowork_daemon.py` is in `orchestrator._NEVER_AUTO_APPROVE`
(orchestrator.py:2651). The impl task is `harness_self_fix` and REQUIRES an
operator decision file at
`state/control/decisions/headless-configdir-seed-creds-daemon-impl.json` granting
approve. TWO tasks, ONE flat plan (NOT an epic): one impl + its paired oracle.

# Non-Goals

- Do NOT change the `claude_backend` config knob, the tmux backend,
  `tmux_worker.py`, or `overseer/tmux_seams.py`. REUSE `seed_config_dir`; do not
  modify it.
- Do NOT change `agent_jail.build_jail_argv` or `bind_credentials` semantics.
- Do NOT copy the whole `~/.claude` tree — only the three files
  `config_seed_plan` enumerates.
- Do NOT change the `_seed_claude_config_dir` return shape
  (`{'CLAUDE_CONFIG_DIR': str(config_dir)}`), the non-claude / no-work_dir
  early-return `{}`, or the `autowork_daemon` positional/keyword arg-parsing
  (the `(state_dir, task_id)` two-arg form resolving agent/work_dir from the task
  file must stay byte-identical).
- This is a focused credential-seed **integration** fix; no clock / uuid /
  random / network.

# Inputs

LIVE FILE (working_dir = `/home/xnihil0zer0/AI-Data/JanusMaskEX`):
- `harness/autowork_daemon.py` — top-level `_seed_claude_config_dir` (line 1221).
  `shutil` already imported (used at line 248). The claude branch
  `config_dir.mkdir` is at lines 1278-1283; after the mkdir, copy creds into
  `config_dir` before building `res = {'CLAUDE_CONFIG_DIR': str(config_dir)}`.

REUSE (read-only, do NOT edit) — the tested copy logic (same call as the
orchestrator sibling):

    from overseer import tmux_seams
    tmux_seams.seed_config_dir(
        str(config_dir),
        home=os.environ.get('HOME') or os.path.expanduser('~'),
        copy=shutil.copy2,
        exists=os.path.exists,
        makedirs=lambda d: os.makedirs(d, exist_ok=True),
    )

  Wrap in `try/except Exception` so a copy failure NEVER raises out of the seed.
  Lazy-import `from overseer import tmux_seams` INSIDE the function.

# Deliverables

TWO tasks, ONE flat plan. Both `priority: high`,
`working_dir: /home/xnihil0zer0/AI-Data/JanusMaskEX`. `verification_command` is bare.

## TASK T1 — `headless-configdir-seed-creds-daemon-impl` (deps: [])

`meta_task_type: harness_self_fix`, `priority: high`, `partial_edit: true`.
files_touched: `["harness/autowork_daemon.py"]`.
Its `non_goals` MUST contain the literal word `integration`.

CHANGE: in the claude branch of `_seed_claude_config_dir` (the
`config_dir.mkdir(...)` block, lines 1278-1283), after the mkdir, call
`overseer.tmux_seams.seed_config_dir` exactly as in Inputs (lazy import,
try/except swallow). The `res = {'CLAUDE_CONFIG_DIR': str(config_dir)}` build, the
`env_dict.update(res)` side-effect, and all arg-parsing stay byte-identical.

`__JANUSMASK_PATCHES__`: ONE symbol patch for `_seed_claude_config_dir`.

`verification_command` (bare):
`python -m pytest tests/harness/test_daemon_configdir_seed_creds.py -q`
regression_tests >= 2 (positional `('claude', work_dir)` form still returns the
dict; the `(state_dir, task_id)` two-arg form still resolves agent/work_dir from
the task file; non-claude returns `{}`).

## TASK T2 — `headless-configdir-seed-creds-daemon-oracle` (deps: [T1])

`meta_task_type: test_authoring`, `mutation_target: harness.autowork_daemon`,
files_touched: `["tests/harness/test_daemon_configdir_seed_creds.py"]`.
Its `non_goals` MUST contain the literal word `integration`. `importlib` import.

Hermetic RED->GREEN (no real `~/.claude`, no network): build a fake HOME tmp tree
(`<home>/.claude/.credentials.json` bytes `b'{"claudeAiOauth":{}}'`,
`<home>/.claude/settings.json`, `<home>/.claude.json`),
`monkeypatch.setenv('HOME', <home>)`; call
`harness.autowork_daemon._seed_claude_config_dir('claude', <work_dir>)`; assert the
seeded `CLAUDE_CONFIG_DIR` contains a byte-equal `.credentials.json` (RED today:
empty dir) plus `settings.json` + `.claude.json`. Negative: `'gemini'` returns
`{}` and copies nothing; `('claude', '')` returns `{}`. Also cover the
`(state_dir, task_id)` arg form resolving `working_dir` from
`<state_dir>/tasks/<task_id>.json`. The declared mutant reverting the copy MUST
make the creds assertion fail.

`verification_command` (bare):
`python -m pytest tests/harness/test_daemon_configdir_seed_creds.py -q`

# Required plan shape

TWO tasks, ONE flat plan (NOT an epic). Dep edge: T2 <- T1. `required_task_ids`
in frontmatter lists both. Both `working_dir: /home/xnihil0zer0/AI-Data/JanusMaskEX`.
Decision file REQUIRED before T1 can land (trust-core `_NEVER_AUTO_APPROVE`):
`state/control/decisions/headless-configdir-seed-creds-daemon-impl.json` granting approve.
