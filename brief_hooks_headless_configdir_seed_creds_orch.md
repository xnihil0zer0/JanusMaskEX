---
slug: headless_configdir_seed_creds_orch
working_dir: "/home/xnihil0zer0/AI-Data/JanusMaskEX"
complexity_score: medium
required_task_ids:
  - headless-configdir-seed-creds-orch-impl
  - headless-configdir-seed-creds-orch-oracle
---

# Title

Make the headless-backend `CLAUDE_CONFIG_DIR` seed in `harness/orchestrator.py`
COPY the operator's claude OAuth credentials into the per-spawn config dir,
reusing the already-tested `overseer.tmux_seams.seed_config_dir` copy logic.

# Background

`harness/orchestrator.py::_seed_claude_config_dir` (line 212) only `mkdir`s an
EMPTY `.claude_config` and returns `{'CLAUDE_CONFIG_DIR': str(config_dir)}` with
no credential copy. `spawn_agent` (orchestrator.py:397-399) calls it for EVERY
claude spawn (planner blind-draft AND worker synthesis), so under the headless
backend every jailed claude starts "Not logged in" and emits no draft — silently
degrading the factory to single-agent (gemini-only). Verified live: a creds-less
`CLAUDE_CONFIG_DIR` → claude rc=1 "Not logged in"; the SAME dir seeded via the
tmux_seams copy → rc=0 "OK". The tmux backend masked this because it routes claude
through `tmux_seams.seed_config_dir` which copies the creds; the headless path
(`spawn_agent` → this seed) does not.

# Scope

TRUST-CORE: `harness/orchestrator.py` is in `orchestrator._NEVER_AUTO_APPROVE`
(orchestrator.py:2651). The impl task is `harness_self_fix` and REQUIRES an
operator decision file at
`state/control/decisions/headless-configdir-seed-creds-orch-impl.json` granting
approve. TWO tasks, ONE flat plan (NOT an epic): one impl + its paired oracle.

# Non-Goals

- Do NOT change the `claude_backend` config knob, the tmux backend,
  `tmux_worker.py`, or `overseer/tmux_seams.py`. This brief makes the HEADLESS
  seed REUSE the existing `tmux_seams.seed_config_dir`; it does not modify it.
- Do NOT change `agent_jail.build_jail_argv` or `bind_credentials` semantics; do
  NOT broaden the jail credential surface.
- Do NOT copy the whole `~/.claude` tree — only the three files
  `config_seed_plan` enumerates.
- Do NOT change the `_seed_claude_config_dir` signature, its return shape
  (`{'CLAUDE_CONFIG_DIR': str(config_dir)}`), or the non-claude / no-work_dir
  early-return `{}`.
- This is a focused credential-seed **integration** fix; no clock / uuid /
  random / network.

# Inputs

LIVE FILE (working_dir = `/home/xnihil0zer0/AI-Data/JanusMaskEX`):
- `harness/orchestrator.py` — top-level `_seed_claude_config_dir(agent, work_dir,
  task_id=None)` (line 212). `import shutil` (line 9), `import os`, `from pathlib
  import Path` (line 15) already present. After `config_dir.mkdir(parents=True,
  exist_ok=True)` succeeds, copy creds into `config_dir`.

REUSE (read-only, do NOT edit) — the tested copy logic:
- `overseer/tmux_seams.py::seed_config_dir(config_dir, *, home, copy, exists,
  makedirs)` (line 50) + `config_seed_plan(home)` (line 40). Idempotent: copies
  `.credentials.json` + `settings.json` from `~/.claude` and `~/.claude.json`,
  only when src exists and dst absent. Call it as:

    from overseer import tmux_seams
    tmux_seams.seed_config_dir(
        str(config_dir),
        home=os.environ.get('HOME') or os.path.expanduser('~'),
        copy=shutil.copy2,
        exists=os.path.exists,
        makedirs=lambda d: os.makedirs(d, exist_ok=True),
    )

  Wrap in `try/except Exception` so a copy failure NEVER raises out of the seed
  (degrade to prior creds-less behavior rather than crash the spawn). Lazy-import
  `from overseer import tmux_seams` INSIDE the function to avoid an import cycle.

# Deliverables

TWO tasks, ONE flat plan. Both `priority: high`,
`working_dir: /home/xnihil0zer0/AI-Data/JanusMaskEX`. `verification_command` is bare.

## TASK T1 — `headless-configdir-seed-creds-orch-impl` (deps: [])

`meta_task_type: harness_self_fix`, `priority: high`, `partial_edit: true`.
files_touched: `["harness/orchestrator.py"]`.
Its `non_goals` MUST contain the literal word `integration`.

CHANGE: in `_seed_claude_config_dir`, after `config_dir.mkdir(parents=True,
exist_ok=True)` succeeds, call `overseer.tmux_seams.seed_config_dir` (see Inputs)
to copy the three creds files into `config_dir`, inside a `try/except Exception`
that swallows failures. The existing `OSError`/`Exception` fallbacks and the
`{'CLAUDE_CONFIG_DIR': ...}` return shape stay byte-identical.

`__JANUSMASK_PATCHES__`: ONE symbol patch for `_seed_claude_config_dir`.

`verification_command` (bare):
`python -m pytest tests/harness/test_headless_configdir_seed_creds.py -q`
regression_tests >= 2 (non-claude agent still returns `{}`; missing work_dir still
returns `{}`; a missing host `~/.credentials.json` must NOT raise).

## TASK T2 — `headless-configdir-seed-creds-orch-oracle` (deps: [T1])

`meta_task_type: test_authoring`, `mutation_target: harness.orchestrator`,
files_touched: `["tests/harness/test_headless_configdir_seed_creds.py"]`.
Its `non_goals` MUST contain the literal word `integration`. Ordinary pytest
source; import the SUT via `importlib` (exec/eval/__import__ are AST-banned).

RED-before / GREEN-after, non-vacuous, hermetic (no real `~/.claude`, no network):
1. Build a fake HOME tmp tree: `<home>/.claude/.credentials.json` (bytes
   `b'{"claudeAiOauth":{}}'`), `<home>/.claude/settings.json`, `<home>/.claude.json`.
   `monkeypatch.setenv('HOME', <home>)`.
2. Call `harness.orchestrator._seed_claude_config_dir('claude', <work_dir>)`.
3. Assert the returned `CLAUDE_CONFIG_DIR` directory now CONTAINS
   `.credentials.json` whose bytes EQUAL the source (RED today: the dir is empty).
   Also assert `settings.json` and `.claude.json` were copied.
4. Anti-vacuity / negative: `_seed_claude_config_dir('gemini', <work_dir>)` returns
   `{}` and copies nothing; `_seed_claude_config_dir('claude', '')` returns `{}`.

The declared mutant (reverting the copy / leaving the dir empty) MUST make
assertion 3 fail.

`verification_command` (bare):
`python -m pytest tests/harness/test_headless_configdir_seed_creds.py -q`

# Required plan shape

TWO tasks, ONE flat plan (NOT an epic). Dep edge: T2 <- T1. `required_task_ids`
in frontmatter lists both. Both `working_dir: /home/xnihil0zer0/AI-Data/JanusMaskEX`.
Decision file REQUIRED before T1 can land (trust-core `_NEVER_AUTO_APPROVE`):
`state/control/decisions/headless-configdir-seed-creds-orch-impl.json` granting approve.
