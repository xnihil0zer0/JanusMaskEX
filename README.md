__JANUSMASK_MANIFEST__ = {"README.md": r'''# JanusMask — Autonomous Code-Generation Factory

JanusMask compiles a plain-English **brief** into *verified* working code. Two independent
LLM agents (Claude + Gemini) each draft a candidate blind to the other; a result is accepted
only when the two are proven **differentially equivalent** under a property-based fuzzer, are
AST-valid, pass a pre-committed pytest oracle, and are reachable from a live entry point — then
it is committed through an isolated git worktree behind a read-only-parent gate.

A self-driving **daemon** promotes briefs, runs the planner, stages tasks, dispatches workers,
retries failures, and self-heals — all behind an explicit operator control surface. The system
builds **its own harness** through this same pipeline, and builds/edits **external repos** (e.g.
`/home/xnihil0zer0/NobleGreedv2`) through an isolated staging worktree.

**Design principle: correctness is enforced by *withholding and checking*, never by prompting.**
The LLMs only *propose*; pure deterministic verifiers *decide*.

This README is an **operator reference for running the pipeline completely hands-off**, for both
**internal** (factory fixing its own `harness/**`) and **external** (factory building another repo)
work. It documents the real system as it runs today — including the places that still need a human
(see [Gaps / steps still requiring a human](#gaps--steps-still-requiring-a-human)).

---

## Table of contents

1. [What the system is — lifecycle](#1-what-the-system-is--lifecycle)
2. [Requirements / prerequisites](#2-requirements--prerequisites)
3. [How to start it hands-off](#3-how-to-start-it-hands-off)
4. [How to feed work: authoring a brief](#4-how-to-feed-work-authoring-a-brief)
5. [External projects (`working_dir`)](#5-external-projects-working_dir)
6. [Pause / resume / stop](#6-pause--resume--stop)
7. [Monitoring (autonomous)](#7-monitoring-autonomous)
8. [Configuration reference](#8-configuration-reference)
9. [`meta_task_type` taxonomy](#9-meta_task_type-taxonomy)
10. [Submission formats](#10-submission-formats-what-the-agent-emits)
11. [Troubleshooting](#11-troubleshooting)
12. [Gaps / steps still requiring a human](#12-gaps--steps-still-requiring-a-human)
13. [State directory layout](#13-state-directory-layout)
14. [Glossary](#14-glossary)

---

## 1. What the system is — lifecycle

```
  brief_hooks_<slug>.md            (markdown + YAML frontmatter — the ONLY hand-authored artifact)
        │  placed at repo ROOT; <slug> added to the allowlist
        ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │ AUTOWORK DAEMON  (harness/autowork_daemon.py, supervised by run-autowork.sh)│
  │  each iteration:                                                            │
  │   reap workers → retry blocked → block dead-dep tasks → harvest self-heal   │
  │   → AUTO-PROMOTE (stage unstaged plan tasks; plan ≤1 unplanned brief)       │
  │   → DECIDE (rank dispatchable tasks; gate on pause/full_stop) → dispatch    │
  └──────────────────────────────────────────────────────────────────────────┘
        │  promote: only for ALLOWLISTED slugs (deny-all by default)
        ▼
  ┌──────────────────┐  blind Claude draft  ┐
  │     PLANNER      │  blind Gemini draft  ├─► diff → reconcile → adversarial review
  │ harness/planner  │                      ┘     → auto-amend → validate → normalize
  └──────────────────┘
        │  emits plan_hooks_<slug>.json  — a list of TASKS (each with its own oracle)
        ▼
  ┌──────────────────┐  one task claimed atomically (<id>.json → <id>.json.processing)
  │ ORCHESTRATOR     │   ┌─ Claude ─┐
  │   _WORKER        │   │           ├─► two candidate implementations (blind to each other)
  └──────────────────┘   └─ Gemini ─┘
        ▼
   ╔══════════════ ACCEPTANCE GATES (pure, deterministic) ══════════════╗
   ║ AST validity · differential-fuzz equivalence · pre-committed oracle ║
   ║ (verification_command) · wired-ness · apply-scope + RO-parent gate  ║
   ╚════════════════════════════════════════════════════════════════════╝
        │ PASS → AST-merge winner into staging worktree → verify vs RO parent → ff-merge → commit
        │ FAIL → roll back live tree (declared files only) → route to blocked/ → retry / self-heal
        ▼
   a real commit on your branch  (and the spent brief+plan auto-archived to _autowork_archive/)
```

The daemon's **two safety boundaries** are both deny-all by default:
- **`state/control/autowork/auto_promote.allowlist`** — which brief slugs may be promoted.
- **`state/control/autowork/external_roots.allow`** — which filesystem roots an external `working_dir` may target.

---

## 2. Requirements / prerequisites

### OS / binaries on PATH
- **Linux** (kernel namespaces required for the sandboxes).
- **`bwrap`** (bubblewrap) + **`libseccomp`** — the agent jail and the fuzz sandbox. `agent_sandbox.bwrap: true` is set, so agent spawns are **fail-closed**: if `bwrap` is missing the spawn aborts rather than running un-jailed.
- **`git`** — staging worktrees, commit, ff-merge.
- **`xdg-dbus-proxy`** — filtered D-Bus. **Fail-closed startup guard:** if the host has `DBUS_SESSION_BUS_ADDRESS` set but `xdg-dbus-proxy` is absent and `JANUSMASK_ALLOW_HOSTBUS` is unset, the daemon **raises and refuses to start** (it will not bind the unfiltered host bus into the jail).
- **`python`** (3.10+) — the conda/venv interpreter the daemon and workers run under.
- **`node` / `nvm`** — only for the JS differential target (`autocompiler/js/`), pinned via `~/.nvm/versions/node/<v>/bin`.

### Python env
`pip install -r requirements.txt` — `hypothesis`, `pyyaml`, `pytest` (+ `pytest-xdist`, `pytest-testmon`, `pytest-timeout`), `psutil`, `Pygments`. The current core worker path uses CLI subprocess agents consumed as NDJSON/outbox artifacts. The WebUI/config schema also contains optional API-backed model-provider surfaces (`harness/model_backends.py`, `harness/webui_config_schema.py`) gated on provider credentials and lazy SDK availability; those are not the default autonomous worker path.

> **Interpreter-ABI caveat for external builds:** the daemon may run under conda Python (e.g. 3.13) while an external jail detonates with `/usr/bin/python3` (e.g. 3.10). Compiled-extension wheels installed with one interpreter will not import under the other. External targets must declare/resolve the jail interpreter; keep the host and detonation interpreters ABI-aligned for any external task that installs compiled deps.

### Scripted tests
The root `Makefile` defines the supported local test tiers:
- `make test-changed` — testmon impact-selected inner loop. First run warms `.testmondata`; later runs are the quickest feedback.
- `make test-fast` — parallel screen with known non-hermetic offenders pruned. It is useful for broad smoke feedback but is **not** authoritative.
- `make test-full` — serial authoritative gate (`python -m pytest -p no:cacheprovider -q`), intended before commit or release decisions.

Known current caveats from focused verification on 2026-06-17: the old smoke replication oracle still expects removed root files `brief_hooks_smoke.md` and `plan_hooks_smoke.json`; `tests/harness/test_sandbox_child_env_external.py` still expects byte-identical self-build `PYTHONPATH` even though `autocompiler.determinism: true` now deliberately prepends `/tmp/janusmask_det_site`; and live D-Bus proxy smoke tests can fail on hosts where `xdg-dbus-proxy` cannot bind the user bus even when the deterministic argv/unit tests pass.

### Agent backends (how each is configured / authenticated)
Configured under `harness/config.yaml` `agents:` and `config/` worker settings. One-time `scripts/bootstrap.sh` is broader than agent config seeding: it creates the gitignored state tree, seeds a comment-only deny-all `auto_promote.allowlist`, initializes `state/impl_progress.jsonl` and `state/STATE.json`, seeds operator memory when available, creates `venv`, installs `requirements.lock`/`requirements.txt`, and warns if the `claude`/`gemini` CLIs or template files are missing.

| Backend | Binary (templated) | Auth | Notes |
|---|---|---|---|
| **claude** (default worker) | `${PROJECT_ROOT}/.agents/claude-code/node_modules/.bin/claude` | OAuth/subscription (tmux/PTY backend) **or** API key (headless backend) | `--model opus`, `--tools Read,Glob,Grep,Write`, `--disallowedTools Bash,Edit,Task,NotebookEdit,WebFetch,WebSearch,Skill,ToolSearch`. Hooks via `config/claude_worker.json` + `config/claude_mcp.json`. |
| **gemini / antigravity** | `${PROJECT_ROOT}/.agents/agy/agy` | `~/.gemini` credentials | args `-p --dangerously-skip-permissions`. Policy in `config/gemini_worker_policy*.toml`. |
| **claude_fallback** | `${PROJECT_ROOT}/.agents/agy/agy` | as gemini | covers a Claude failure. |
| **codex** | `/home/xnihil0zer0/.nvm/versions/node/v22.17.0/bin/codex` | Codex CLI auth | selectable in `agents:` and routed through the outbox-style worker path; default `synthesis.active_agents` remains `[claude, gemini]`. |

**Claude worker transport** (`workers.claude_backend`, currently **`tmux`**):
- `tmux` — a bwrap-jailed **interactive** claude driven over a direct **PTY** (`harness/tmux_worker.py::spawn_claude_tmux`), billed to the Max/OAuth subscription. ("tmux" is historical; the transport is a PTY.) This is the hands-off default.
- `headless` — `claude -p` streamed subprocess, **API-billed**. Switch to this if a PTY regression appears.

### Config flags that must hold for unattended operation
All of these are **already set** in `harness/config.yaml` (see [§8](#8-configuration-reference)); verify them before a long run:

- `autowork.enabled: true`
- `autowork.auto_approve_sensitive_harness: true` — eligible, non-deny `harness/**` `harness_self_fix` commits may auto-approve behind the content/RO-parent/TOCTOU gates. `config/**`, `scripts/**`, `services/**`, and denied core files still require an explicit operator decision or fail closed.
- `autowork.auto_approve_ro_gate: true` — RO-checkout rollback protector on that path.
- `autowork.archive_spent_briefs: true` — green integrate auto-archives the brief+plan.
- `autowork.wire_up_gate: true` — new modules must be reachable from a live root at accept.
- `hierarchical_planning.enabled: true` — epics decompose; allowlisting an epic transitively admits its children.
- `agent_sandbox.bwrap: true` — kernel-enforced jail.

---

## 3. How to start it hands-off

The supervisor `scripts/run-autowork.sh` **self-starts and self-sustains** the daemon: it launches
`python -m harness.autowork_daemon` under `setsid`, writes the supervised PID to
`state/control/autowork.pid`, and **respawns the child** with capped exponential backoff if it dies.

```bash
cd /home/xnihil0zer0/JanusMaskJR

# (first time only) seed gitignored state, configs, venv, deps, and memory
scripts/bootstrap.sh

# only when you intentionally want to resume a previously stopped/paused run
rm -f state/control/autowork/pause state/control/autowork/full_stop

# start the supervisor (foreground; or wrap with your own setsid/nohup ONCE)
scripts/run-autowork.sh --state-dir state --logs-dir logs --config harness/config.yaml
```
Options: `--state-dir` (default `state`), `--logs-dir` (`logs`), `--config` (`harness/config.yaml`),
`--max-backoff` (respawn cap, default 60s), `--once` (single iteration, no respawn).
Logs append to `logs/autowork.log`.

### CRITICAL — supervisor model (do not break it)
- The **supervisor** is the long-lived process. The **daemon is its child** (`python -m harness.autowork_daemon`).
- To restart the daemon (e.g. after a harness change — see [§11/§12](#12-gaps--steps-still-requiring-a-human)), **kill the child PID** in `state/control/autowork.pid`; the supervisor respawns it:
  ```bash
  kill -TERM "$(cat state/control/autowork.pid)"     # supervised graceful drain (≤30s), then respawn
  ```
- **NEVER `nohup`/launch a second daemon.** Two daemons race the queue and clobber state. There is exactly one supervised child at a time.
- The daemon installs its own SIGTERM handler and **drains workers** (grace 30s) before exiting; the supervisor forwards SIGINT/SIGTERM to the daemon's process group.

### Polling cadence
When there is work, the daemon polls every `poll_interval_sec` (5s). When idle, it sleeps `heartbeat_sec` (1800s) but **wakes early** on an allowlist edit or a new/changed `brief_hooks_*.md` (emits `idle_wake`) — so dropping in a brief takes effect within seconds, not 30 minutes.

---

## 4. How to feed work: authoring a brief

A brief is the **only** hand-authored artifact. Everything downstream (plan, tasks, oracles, code) is produced by the pipeline.

> **Production code is changed only through this pipeline — never by hand.** Every `harness/**` / `config/**` /
> `scripts/**` / `services/**` change is authored as a brief and decided by the verifiers (the author never grades
> its own exam). The only hand-authorable artifacts are the brief itself and pre-committed test oracles; an
> unavoidable manual edit must be cleared with the owner **first**.

### 4.1 The load schema (HARD requirement — `harness/planner/brief_loader.py`)

`load_brief` parses YAML frontmatter (between `---` fences) plus markdown `# Heading` sections. It enforces **five REQUIRED_SECTIONS**:

```
title   scope   non_goals   inputs   deliverables
```

Each must appear **either** as a frontmatter key **or** as a bare `# Heading` section (heading match is case/`-`/space-insensitive → e.g. `# Non-Goals` → `non_goals`), **and be non-empty**. A missing or empty section raises `BriefValidationError` and the brief is **rejected at load**.

> **Heading gotcha:** the loader matches the *bare* normalized name. A decorated heading like `# Inputs (do not rebuild)` does **NOT** match `inputs` → the brief fails validation. Keep the five headings bare (`# Inputs`, `# Scope`, …).

Recognized **frontmatter** keys (`load_brief` reads these; all others are passed through as prose only):
| Key | Meaning |
|---|---|
| `title`,`scope`,`non_goals`,`inputs`,`deliverables` | the five required sections (frontmatter form). |
| `working_dir` | target repo root (see [§5](#5-external-projects-working_dir)). Absent ⇒ build into JanusMask itself. If it resolves *inside* the repo but is not the repo root, the brief is rejected. |
| `epic` | `true` ⇒ hierarchical decomposition into child briefs. |
| `required_task_ids` | list (or comma string) of task IDs the plan MUST contain; `validate_plan` rejects a plan that drops one (`missing_required_task`). Use on gated/internal leaves. |
| `required_child_slugs` | (epic-only) child-brief slugs the decomposition MUST include; `validate_epic_plan` emits a `missing_required_child` error and the epic is **refused** if one is dropped. The epic analogue of `required_task_ids`. |
| `dependencies` | sibling-**slug** build-order hints (stripped at plan normalization — they are NOT in-plan task IDs; see [§4.4](#44-sequencing--epics)). |
| `complexity_score`, `interfaces` | advisory. |

> **`meta_task_type`, `files_touched`, `verification_command` are NOT load_brief fields.** They are author *intent* expressed in `interfaces` prose and/or a `# Required plan shape` body section that the planner reads when shaping the plan. The planner assigns the actual task `meta_task_type` from the [taxonomy](#9-meta_task_type-taxonomy). In particular **`meta_task_type: implementation` is not a valid taxonomy value** — it appears in some external briefs purely as a hint; the planner coerces the real type. Always describe the intended type and constraints in the body so the planner shapes the plan correctly.

### 4.2 When `harness_self_fix` is mandatory

Any task that **writes** a path under the sensitive globs
`harness/**`, `config/**`, `scripts/**`, `services/**` (`_SENSITIVE_APPLY_GLOBS`) **must** be planned as
`meta_task_type: harness_self_fix`. The plan validator rejects a non-`harness_self_fix` task that lists a sensitive path in `files_touched` (`sensitive_files_touched`), because the accept-time apply-scope gate would refuse the write. So a brief that edits the harness must state `harness_self_fix` intent in its `# Required plan shape`.

A short **irreducible** set can NEVER auto-approve, regardless of any flag (`_NEVER_AUTO_APPROVE`): `harness/agent_jail.py`, `harness/dbus_proxy.py`, `harness/paths.py`, `harness/git_integration.py`, `harness/orchestrator.py`, `harness/interceptors.py`, `harness/selfheal.py`, `harness/autowork_daemon.py`, `services/**`. These paths require explicit owner/operator approval through `state/control/decisions/<task_id>.json`; without that decision they fail closed.

> **Editing an irreducible core file (or any `config/**`, `scripts/**`, `services/**` path)? Pre-author the
> decision file.** Such a commit **fail-closes at auto-commit** unless `state/control/decisions/<task_id>.json`
> exists with `{"decision":"approve"}` — and under unattended operation nothing writes it, so the plan **stalls at
> the first such commit**. The `task_id` is only known *after* planning, so **pin it**: set
> `required_task_ids: [<your-task-id>]` in frontmatter, force that exact id in `# Required plan shape`, then write
> the decision file **before** the run:
> ```bash
> echo '{"decision":"approve","by":"operator","reason":"<why>"}' > state/control/decisions/<your-task-id>.json
> ```
> One decision file per gated task. (`auto_approve_sensitive_harness` covers only *eligible, non-deny* `harness/**`
> paths — never the irreducible set, and never `config/scripts/services`.)

### 4.3 Place it and allowlist it

```bash
# 1. Write the brief at the REPO ROOT (filename stem == slug):
#    /home/xnihil0zer0/JanusMaskJR/brief_hooks_my_feature.md

# 2. Allowlist the slug (one per line; '#' comments and blanks ignored; DENY-ALL if empty).
echo "my_feature" >> state/control/autowork/auto_promote.allowlist
```
The daemon plans the **newest-mtime, allowlisted** unplanned brief younger than `brief_max_age_seconds` (7 days) — `compute_brief_status` returns records sorted newest-first and the plan-kickoff loop stops at the **first** eligible unplanned brief — kicking off the planner for **at most one** unplanned brief per iteration (size must be `< brief_max_size_bytes` = 50000). (Task *dispatch*, by contrast, prioritizes **oldest**-mtime tasks via `prioritize()`; don't conflate the two orderings.) Task extraction from already-planned briefs is unbounded per iteration.

### 4.4 Sequencing & epics

- `epic: true` (with `hierarchical_planning.enabled: true`) makes the planner draft a **child-brief set**, write each as its own `brief_hooks_<child>.md` at the root, and persist `plan_hooks_<slug>.json` (`plan_kind: "epic"`, `child_slugs:[...]`). Because the parent epic slug is allowlisted, children are admitted **transitively** — you do not allowlist each child. Nesting caps at `max_planner_depth` (4).
- **Cross-brief ordering is brief-level, not task-level.** A child's frontmatter `dependencies: [sibling-slug]` is a *slug*, stripped at normalization; the daemon's brief-dependency gate holds a child's tasks until every depended-on sibling brief is fully **accepted**. Sequence siblings by holding briefs back (don't write/allowlist a child until its prerequisites land), not by intra-plan task deps.

### 4.5 Copy-pasteable minimal valid brief (passes `load_brief`)

A SINGLE-file internal harness fix. This is the smallest brief that loads cleanly and shapes a one-task plan:

```markdown
---
working_dir: "/home/xnihil0zer0/JanusMaskJR"
required_task_ids:
  - fix-my-defect
interfaces: "harness/foo.py::do_thing — EDIT existing. Replace ONLY the function do_thing so it returns sorted output. Additive/fail-soft: signature unchanged."
---

# Title
Fix do_thing to return sorted output

# Scope
EDIT the EXISTING file `harness/foo.py` (READ it first). SINGLE FILE — emit a
`__JANUSMASK_PATCHES__` SYMBOL patch replacing ONLY `do_thing`. Touch NO other
function or file. This is a sensitive-path edit, so the task is `harness_self_fix`.

# Inputs
READ `harness/foo.py`. VERIFIED current code: <quote the exact function body / point
at a pre-committed RED oracle as the source of truth>.

# Non-Goals
Integration is out of scope (the word `integration` MUST appear here to excuse the
integration-test requirement). Do NOT change any other symbol or file. Do NOT
author tests beyond the one oracle.

# Deliverables
`harness/foo.py` with `do_thing` returning sorted output, GREEN under the scoped
verification_command, with no regression.

# Required plan shape
Emit EXACTLY ONE task.
- task_id MUST be exactly `fix-my-defect`.
- meta_task_type: harness_self_fix
- files_touched: ["harness/foo.py"]
- Emit a `__JANUSMASK_PATCHES__` SYMBOL patch (do NOT emit `__JANUSMASK_MANIFEST__`).
- OMIT mutation_target. spec_author: null if the oracle is pre-committed.
- verification_command: `python -m pytest tests/harness/test_foo_do_thing.py -q`
- non_goals MUST contain the literal word `integration`; regression_tests >= 2.
```

Notes:
- The **`integration` excuse**: the plan validator requires an integration test for a `.py`-editing task **unless** the literal word `integration` appears in the task's `non_goals`. Put it in the brief's `# Non-Goals` and restate it in `# Required plan shape`.
- A **new module/file** cannot use `__JANUSMASK_PATCHES__` (patches only *replace* existing symbols). Emit it **whole-file** via `__JANUSMASK_MANIFEST__`, keep the task to **one file**, and ensure a `*_wired` oracle (named in `verification_command`) or a paired `test_authoring` sibling exists so the wire-up gate passes (see [§10](#10-submission-formats-what-the-agent-emits)).
- If your patch emits `"""` docstrings via the blind partial-edit, add a `# NESTED-QUOTE HAZARD` note instructing the agent to emit `"""` (not `'''`) and never backslash-escape quotes.
- **A `verification_command` must select ≥1 REAL test and be non-vacuous.** It runs RED-before / GREEN-after; a vcmd
  that **collects zero tests** (pytest exit code **5** — wrong path, bad `-k`, no matching `test_*`) fails *identically*
  to a real failure (`verification_failed`), and a trivially-green vcmd like `python -c "import mymod"` lets unverified
  code **land** (a "clobber"). Before dispatch, run the EXACT vcmd yourself, confirm it reports `N passed` with N ≥ 1,
  and confirm it actually exercises the changed symbols.

---

## 5. External projects (`working_dir`)

A brief with `working_dir: "/home/xnihil0zer0/NobleGreedv2"` builds into **that** repo instead of JanusMask.

How it routes and self-protects:
1. **External-roots allowlist (bootstrap deny-all):** `working_dir` must resolve to (or under) a prefix in
   `state/control/autowork/external_roots.allow` (one absolute prefix per line; `#`-comments ignored; **missing/empty ⇒ external bootstrap denied**). Currently approved: `/home/xnihil0zer0/NobleGreedv2`.
2. **Bootstrap before staging** (`harness/target_bootstrap.py::bootstrap_target`, idempotent, best-effort):
   - A brand-new external dir is `git init`-ed and gets a JanusMask ownership marker `.janusmask/bootstrap.json` plus a JM-owned `janusmask/work` branch (your checked-out branch is untouched).
   - **`BootstrapRefused` when:** the path is not under an approved root; **the tree is dirty** (uncommitted changes — JM never auto-stashes a user repo); or it is a git repo with **no JM ownership marker** (treated as foreign). Current auto-promote logs this as a `silent_skip`/bootstrap failure and may still stage extracted tasks; the later accept path independently refuses dirty external trees, missing external `.venv`, and disabled jail, but does **not** re-check `external_roots.allow`.
3. **Worker staging** (`orchestrator._auto_commit_accepted`): JM edits the foreign repo only through a **throwaway staging worktree** under `<agent_workroot>/external_staging/`, runs the gates there, then ff-merges into the live external tree. An **EXTERNAL_DIRTY_GATE** re-checks `git status --porcelain` on the live external tree before staging and raises if it is dirty.
4. **External verify in the target's own venv (`G3_VENV`):** external verification/fuzz must run under the target's `.venv/bin/python`; a missing `.venv` is refused.
5. **Jail-mandatory (`FLAG2`):** every external candidate spawn (embedded tests, narrow fuzz, verify, baseline, mutant) **requires** the bubblewrap jail; if `agent_sandbox.bwrap` is off, the external task is refused (never run un-jailed against a foreign repo).
6. The daemon never pushes/rebases the JanusMask repo for external work (`external_noop`), and external commits skip untracked-file auto-detection so JM never commits stray files into the foreign repo.

To approve a new external root:
```bash
echo "/abs/path/to/target_repo" >> state/control/autowork/external_roots.allow
```

---

## 6. Pause / resume / stop

**The dispatch gate is the EXISTENCE of a file, not a string.** (`harness/autowork_daemon.py::_decide`):

```python
paused = _pause_flag_path(state_dir).exists() or _full_stop_path(state_dir).exists()
```

| Action | Command | Effect |
|---|---|---|
| **Pause dispatch** | `touch state/control/autowork/pause` | Daemon keeps polling/promoting but dispatches **no new workers**. In-flight workers finish. Auto-clears nothing — remove the file to resume. |
| **Resume dispatch** | `rm -f state/control/autowork/pause` | Dispatch re-enabled on the next poll (emits a `resume` row). |
| **Hard stop (persistent)** | `touch state/control/autowork/full_stop` | Halts promotion AND dispatch, **breaks the daemon loop** (`daemon_stop`), and **stops the supervisor's respawn**. Operator-persistent: never auto-cleared. |
| **Resume from hard stop** | `rm -f state/control/autowork/full_stop` then start the supervisor again | — |
| **Stop supervisor** | `touch state/control/autowork/supervisor.stop` | WebUI/supervisor stop sentinel. `scripts/run-autowork.sh` clears stale `supervisor.stop` on fresh start; unlike `full_stop`, it is not operator-persistent. |
| **Restart the daemon child** | `kill -TERM "$(cat state/control/autowork.pid)"` | Graceful drain; supervisor respawns (needed to pick up harness code changes — see [§12](#12-gaps--steps-still-requiring-a-human)). |
| **Disable auto-promotion only** | `touch state/control/autowork/auto_promote.disabled` | Stops staging/planning; dispatch of already-staged tasks still runs. |

> **`state/control/orchestrator.flag` does NOT gate the daemon.** It is referenced in `config.yaml` (`control.pause_flag_path`) and consumed by `harness/control_gate.py` / the WebUI, but `autowork_daemon._decide` never reads it. Use the `pause` / `full_stop` **files** above to control the daemon. (Earlier docs that say "set `orchestrator.flag` to `resume`/`pause`" are wrong for the daemon.)

---

## 7. Monitoring (autonomous)

### The real ledger
**`state/impl_progress.jsonl`** is the master append-only telemetry ledger. (There is **no** `state/ledger` — that path does not exist.) Each row: `{"ts","phase","task_id","event","detail",...}`.

```bash
tail -F state/impl_progress.jsonl \
  | grep -E '"event": "(plan_kickoff|extract|launch|launch_sequential|auto_commit|task_blocked|retry_exhausted|verification_failed|planner_hallucination_discarded|planner_validation_rejected|plan_timeout|dependency_failed|orphan_unwired|inactivity_watchdog_triggered)"'
```

Key events:
| Event | Meaning |
|---|---|
| `plan_kickoff` | planner started on an unplanned brief (clean). |
| `planner_hallucination_discarded` | planner output rejected (empty/too-fast/single-agent/**invalid brief**); `detail` carries the reason + a `stderr_tail`. **Also fires for a malformed brief** — see [§12](#12-gaps--steps-still-requiring-a-human). |
| `planner_validation_rejected` | a deterministic plan-validation refusal (the planner printed `failed validation`, e.g. a `missing_required_child` / `missing_required_task` violation) — distinct from `planner_hallucination_discarded`; the slug is parked with a `deterministic` plan-attempt marker. |
| `plan_timeout` | planner exceeded `planner_timeout_sec`; plan park bumped. |
| `extract` | a plan task was staged into `state/tasks/`. |
| `launch` / `launch_sequential` | a worker was dispatched. |
| `auto_commit` (`phase: accepted`) | a task LANDED; `commit_sha` + `files` included. The authoritative "done" signal. |
| `verification_failed` | the oracle (`verification_command`) failed in staging → rolled back. |
| `task_blocked` | a non-accept terminal routed to `blocked/`; `outcome` field carries the reason. |
| `retry_exhausted` | blocked-retry budget spent; `.exhausted` marker written; self-heal escalation fired. |
| `dependency_failed` | a task terminally blocked because a dependency died. |
| `brief_dep_unresolvable` | a task's `dependencies:` slug resolves to **no brief** (under any spelling) or to a sibling whose every task is exhausted; the gate **releases the task with a warning** and lets it dispatch against the unmet dependency. Verify a depended-on sibling brief actually exists/lands. |
| `orphan_unwired` | a new module was unreachable from a live root → rolled back fail-closed. |
| `inactivity_watchdog_triggered` | >20 min with unfinished allowlisted work and no worker event → a diagnosis-only self-heal agent was spawned. |

`outcome` strings on a `task_blocked` row (also written to the retry sidecar's `last_outcome`):
`synthesis_or_ast_failed`, `embedded_tests_failed`, `narrow_fuzz_failed`, `stateful_fuzz_divergence`,
`smoke_failed`, `fuzz_error_r{n}`, `auto_commit_failed[_r{n}]`, `worker_crash_orphan`,
`dependency_failed`, `orphan_unwired`. The deterministic ones
(`synthesis_or_ast_failed`, `embedded_tests_failed`, `narrow_fuzz_failed`) get a retry budget of **1** (re-trying a deterministic failure is futile); others get **3**.

### Other observability
- **`state/planning/planner_progress.jsonl`** — per-stage planner lifecycle (blind draft / diff / reconcile / validate / normalize).
- **`scripts/brief_status.py`** — ground-truth sweep classifying every brief/plan as `unplanned`/`planned`/`queued`/`in_flight`/`blocked`/`zombie`/`complete` by running each oracle against the current tree.
- **`logs/autowork.log`** — daemon poll/promote/dispatch decisions. **`logs/harness.log`** — orchestrator phases.
- **`state/tasks/`** (queued `<id>.json`), **`.json.processing`** (claimed), **`blocked/`** (failed + `.retry.json` / `.exhausted` sidecars), **`processed/`** (accepted / no_diff).
- **`state/output/<id>.{py,files.json,patches.json,no_diff}`** — the worker's emission.

### Drive backup hooks
`tools/drive_backup/` installs detached git `pre-push` hooks for push-time backups. The hook captures the actual pushed repo in `JM_PUSH_REPO`, launches `python -m tools.drive_backup.hook_runner` in a detached `setsid` subprocess, and always returns `0`, so a backup/upload failure never blocks the push.

Production state lives outside any repo under `~/.janusmask/drive_backup/`: archive output, queued uploads, and `ledger.ndjson`. Upload failures are copied into `queue/` with `*.queued.json` sidecars and can be retried by the drain path. Install/update hooks with:

```bash
python -m tools.drive_backup.install_hooks
```

---

## 8. Configuration reference

`harness/config.yaml` is the master knob file. Current operationally-relevant values:

```yaml
agent_sandbox:
  bwrap: true                 # bubblewrap jail for agent spawns (fail-closed)

agents:
  claude:
    command: ${PROJECT_ROOT}/.agents/claude-code/node_modules/.bin/claude
    args: [-p, --model, opus, --output-format, stream-json, --verbose,
           --include-partial-messages, --settings, ${CONFIG_DIR}/claude_worker.json,
           --mcp-config, ${CONFIG_DIR}/claude_mcp.json, --strict-mcp-config,
           --setting-sources, '', --tools, Read,Glob,Grep,Write,
           --disallowedTools, Bash,Edit,Task,NotebookEdit,WebFetch,WebSearch,Skill,ToolSearch]
  gemini:      { command: ${PROJECT_ROOT}/.agents/agy/agy, args: [-p, --dangerously-skip-permissions] }
  antigravity: { command: ${PROJECT_ROOT}/.agents/agy/agy, args: [-p, --dangerously-skip-permissions] }
  claude_fallback: { command: ${PROJECT_ROOT}/.agents/agy/agy, args: [-p, --dangerously-skip-permissions] }
  codex: { command: /home/xnihil0zer0/.nvm/versions/node/v22.17.0/bin/codex,
           args: [exec, --dangerously-bypass-approvals-and-sandbox,
                  --skip-git-repo-check, --color, never, -p, ""] }

autowork:
  enabled: true
  parallel_cap: 5             # max concurrent workers (clamped 1–16)
  poll_interval_sec: 5        # poll cadence when active
  heartbeat_sec: 1800         # idle sleep (wakes early on allowlist/brief change)
  planner_timeout_sec: 1800   # planner wall-clock budget (rc=124 → plan_timeout)
  planner_min_wall_sec: 10.0  # a sub-10s planner run is treated as a hallucination
  brief_max_age_seconds: 604800   # 7 days; older briefs are not auto-promoted
  brief_max_size_bytes: 50000     # briefs at/above this are not planned (brief_too_large)
  wire_up_gate: true              # new modules must reach a live root at accept
  selfheal_auto_promote: false    # self-heal briefs do NOT auto-promote (operator decision)
  archive_spent_briefs: true      # green integrate auto-archives the brief+plan
  auto_approve_sensitive_harness: true  # eligible non-deny harness/** harness_self_fix commits may auto-approve
  auto_approve_ro_gate: true            # RO-checkout rollback protector on that path
  conservative_missing_files: true
  state_reconcile: true           # stale-state reconciler: reaps orphaned workdirs / stale tasks
  # NOTE: max_total_selfheal_escalations is NOT in this file; the self-heal runaway
  #       ceiling defaults to 50 (persisted in state/control/autowork/runaway_ceiling.json).

synthesis:
  active_agents: [claude, gemini]
  max_ast_retries: 3
  accept_single_agent_leaf_plans: true
  enable_single_agent_promotion: true
  single_agent_promotion_ceiling: 3
  timeout_seconds: 1800
  verification_timeout_seconds: 1200

workers:
  claude_backend: tmux        # jailed interactive claude over a PTY (subscription-billed); 'headless' = -p API
  agy_pool: { enabled: false, size: 8 }   # if enabled, size MUST be >= autowork.parallel_cap

hierarchical_planning:
  enabled: true
  max_planner_depth: 4
  failure_propagation: true
  symbol_ledger: true

control:
  autobrief_default_agent: claude
  decisions_dir: state/control/decisions
  pause_flag_path: state/control/orchestrator.flag   # NOT consulted by the daemon (see §6)

sandbox:        { cpu_time_limit_seconds: 10, memory_limit_mb: 256, network: false, filesystem_root: /tmp/janusmask_sandbox }
fuzzing:        { engine: hypothesis, seed: 42, function_level_inputs: 2000, program_level_inputs: 1000, timeout_per_input_ms: 5000, float_tolerance: 1.0e-09 }

autocompiler:   # MIRROR of the runtime gate; the file actually read is config/autocompiler.yaml
  enabled: true
  population: true   # near-miss memory at the fuzz seam
  determinism: true  # value-entropy virtualization in the sandbox child env
  decode: true       # post-decode schema-validation telemetry
  js: true           # JS differential dispatch (only fires for language: js tasks)
```

> The autocompiler hooks read **`config/autocompiler.yaml`** (`<cwd>/config/autocompiler.yaml`) at runtime, fail-closed — the `autocompiler:` subtree above only mirrors it. Edit `config/autocompiler.yaml` to change runtime behavior; keep both in sync. `scripts/run-autowork.sh` cd's to the repo root before launching; direct `python -m harness.autowork_daemon` invocations must also start from the repo root.

> **`workers.agy_pool` caveat:** the `size >= autowork.parallel_cap` rule is **comment-only — NOT runtime-enforced**.
> If the pool is enabled and exhausted (`size < parallel_cap` under load), slot allocation returns empty and workers
> fall back to the **shared `~/.gemini` HOME**, racing each other's credentials/session state. Keep `size >= parallel_cap`
> whenever you flip `enabled: true` (the default pool is `enabled: false`).

---

## 9. `meta_task_type` taxonomy

Every task carries a `meta_task_type` (`harness/planner/taxonomies.py::META_TASK_POLICY`) selecting its verification policy. Policy flags: `bypass_fuzzer` (skip differential fuzzing), `skip_structural_decomp` (don't auto-split on divergence), `skip_smoke_gates` (skip import/narrow pre-gates), `stateful_fuzz` (sequence-based fuzzing).

| meta_task_type | bypass_fuzzer | notable | typical use |
|---|---|---|---|
| `data_model` | yes | skip decomp | dataclasses / pure structures |
| `config_schema` | yes | skip smoke | config readers / schema |
| `validation` | yes | — | pure gate/validator functions |
| `planner_tooling` | yes | skip decomp | planner-side helpers |
| `orchestration` | yes | skip decomp | coordination over injected seams |
| `harness_plumbing` | yes | skip decomp+smoke | internal harness glue |
| `mcp_plumbing` | yes | skip decomp | MCP glue |
| `mcp_server_change` | yes | skip smoke | MCP server edits |
| `hooks_integration` | yes | skip smoke | hook wiring |
| `docs_writing` | yes | skip smoke | docs |
| `epic_planning` | yes | skip decomp+smoke | decomposition only, no code |
| `cli_tooling` | no | — | standard fuzzed CLI code |
| `refactor` | no | — | pure-edit refactor |
| `logging_observability` | no | — | logging/metrics |
| `io_adapter` | no | skip decomp | side-effecting I/O |
| `state_machine` | no | skip decomp, stateful_fuzz | stateful logic |
| `sandbox_infra` | yes | skip decomp | sandbox infra |
| `test_unit`/`test_integration`/`test_e2e`/`test_acceptance` | yes | skip smoke | test code (self-verifying) |
| `test_authoring` | no | skip decomp, skip interface fuzz | authors an oracle for a `mutation_target` module |
| **`harness_self_fix`** | yes | skip decomp+smoke | **REQUIRED** for any write under `harness/**` `config/**` `scripts/**` `services/**` |

`BYPASS_FUZZER_TYPES`, `SIDE_EFFECT_META_TYPES`, `SKIP_SMOKE_GATE_TYPES` are derived from this table. **`implementation` is not a member** — if a brief hints it, the planner coerces a real type.

---

## 10. Submission formats (what the agent emits)

Agents write an outbox artifact (`submission.py` in synthesis); hooks also persist canonical JSON records with `code` and `explanation` under `state/sessions/`. The code payload may be `__JANUSMASK_PATCHES__`, `__JANUSMASK_MANIFEST__`, ordinary Python for single-file/test-authoring tasks, or literal non-`.py` content. Multi-file tasks require a manifest.

### `__JANUSMASK_PATCHES__` — partial-edit / R-anchor symbol patches
```python
__JANUSMASK_PATCHES__ = [
  {'file': 'harness/foo.py', 'kind': 'symbol', 'name': 'do_thing', 'code': r'''def do_thing(...): ...'''},
]
```
- `kind: 'symbol'` replaces exactly one EXISTING top-level `def`/`async def`/`class` (or dotted `Outer.method`). `kind: 'region'` replaces only the lines between a `# JANUSMASK_REGION:<S>` … `# JANUSMASK_ENDREGION:<S>` sentinel pair.
- Used for an EDIT to an existing file (`partial_edit`, or a `bypass_fuzzer` type), single-file, target already on disk.
- **Cannot create a file or a brand-new top-level symbol** — `_apply_symbol_patch` raises `KeyError` if `name` is absent. To **add** a symbol, use the **R-ANCHOR additive** pattern: one `symbol` entry whose `name` is an existing anchor and whose `code` reproduces that anchor verbatim **plus** the new symbol(s); the harness inserts the extras before the anchor.
  - **R-ANCHOR additive constraints (each raises `ValueError` in `git_integration.py`; this is the #1 `auto_commit_failed` cause):** extras are allowed **only for a 1-part top-level anchor** (never a dotted `Outer.method`); the `code` block must contain **exactly one** `def`/`class` (or assignment) named the anchor; every **extra** node must be in the `allowed_extra` whitelist — an `import` / `from`-import / module-level assignment **or an additional `def`/`class`** (`git_integration.py`: `ast.Import, ImportFrom, FunctionDef, AsyncFunctionDef, ClassDef, Assign, AnnAssign`); any other top-level node kind is rejected; and an extra must **not collide** with a name already in the source. With no extras the result is byte-identical to a plain symbol replace.

### `__JANUSMASK_MANIFEST__` — whole-file / multi-file
```python
__JANUSMASK_MANIFEST__ = {
  'harness/newmod.py': r'''<entire file source>''',
  'tests/harness/test_newmod_wired.py': r'''<entire file source>''',
}
```
- Each value is VERBATIM whole-file source (no diffs). Used for **new modules** and any multi-file task (`len(files_touched) > 1`). Every `files_touched` entry must be a manifest key (`manifest_incomplete` otherwise).
- Wrap with raw triple-single-quote `r'''...'''` so backslashes/quotes survive.

A `test_authoring` task submits the test file source directly as ordinary Python (neither marker). Existing-module red-pair flows are accepted when the RED `test_authoring` task is paired with a sibling implementation task whose `verification_command` uses that authored test; new-module work still needs the wired-oracle/reachability path described above.

> **Every task — including a `test_authoring` oracle — must carry a non-empty `verification_command`.** `validate_plan` rejects a task missing it (`missing_field` on `tasks[N].verification_command`), so a `# Required plan shape` must give the oracle task one too — point it at the test file it authors (`python -m pytest tests/.../test_<x>.py -q`). The RED oracle is still accepted because the impl sibling's `verification_command` substring-contains that authored file and the impl is the oracle's dependency-edge sibling (fix-forward red-pair); the oracle is not required to be green at oracle time.

### Acceptance gates a submission must clear (worker lifecycle)
claim → synthesis (configured active agents; default Claude+Gemini) → AST validation (`max_ast_retries`) → differential/stateful fuzz → bypass-fuzzer smoke/embedded/narrow gates (for `bypass_fuzzer` types) → oracle (`verification_command`, RED-before baseline / GREEN-after in staging) → mutation non-vacuity gate (for `test_authoring`) → wire-up (reachable from a live root) → auto-commit (staging worktree → RO-parent verify → ff-merge). Any non-accept rolls back the live tree **scoped strictly to `files_touched`** and routes to `blocked/`.

---

## 11. Troubleshooting

| Symptom | Cause / recovery |
|---|---|
| **Daemon does nothing.** | Check: no `state/control/autowork/full_stop`, no `state/control/autowork/pause`, slug is in `auto_promote.allowlist` (deny-all when empty/comment-only), brief younger than 7 days, no `auto_promote.disabled`. The supervised child PID is in `state/control/autowork.pid`. |
| **Brief rejected / `planner_hallucination_discarded`.** | Often a malformed brief. Ensure the five headings are **bare**, each non-empty; an EDIT task's `non_goals` contains the literal word `integration`; a module-creating task names a `*_wired` oracle in `verification_command`. A `stderr_tail` containing `validation failed`/`missing required field` ⇒ deterministic brief defect (see [§12](#12-gaps--steps-still-requiring-a-human)). |
| **`plan_timeout`.** | Planner exceeded `planner_timeout_sec` (1800s); the partial plan is deleted and the slug parked with escalating backoff (300s → 3600s → 86400s). Re-saving the brief (newer mtime) clears a non-deterministic park. |
| **`empty_plan` / single-agent discard.** | Planner produced no tasks or only un-reconciled Gemini tasks. Tighten the `# Required plan shape`; ensure a real RED oracle exists for a standalone test. |
| **Task keeps failing identically.** | A deterministic outcome (`synthesis_or_ast_failed`/`embedded_tests_failed`/`narrow_fuzz_failed`) retries only **once**. A stale `state/output/<id>.{patches,files}.json` sidecar can mis-route the accept path; the worker purges them on non-accept, but if you re-stage by hand, clear them too. |
| **`auto_commit_failed` on a new file.** | The patches path cannot CREATE files — emit a new module **whole-file** (`__JANUSMASK_MANIFEST__`), keep the task to ONE file, and don't list non-target files in `files_touched`. |
| **`orphan_unwired`.** | A new module is unreachable from a live root. Import it from a live root or register its dotted path under `config/**`; or include a `*_wired` oracle. |
| **`verification_failed`.** | The oracle failed in staging. The vcmd runs RED-before (baseline) and must pass GREEN-after; check `stdout_tail`/`stderr_tail` on the ledger row. |
| **`verification_failed` but the code looks correct.** | The `verification_command` likely **collected no tests** (pytest exit **5**: wrong path / bad `-k` / no `test_*` match) — which fails *identically* to a real failure. Run the exact vcmd by hand and confirm `N passed`, N ≥ 1. The opposite footgun: a trivially-green vcmd (`python -c "import X"`) lets unverified code land. |
| **`whole_file_drift`.** | A whole-file (`__JANUSMASK_MANIFEST__`) submission modified **existing** top-level symbols beyond the intended scope. Legacy whole-file edits must not silently rewrite other symbols — use a `__JANUSMASK_PATCHES__` partial-edit to change one symbol, or split into a declared multi-file manifest. |
| **External build refused.** | `BootstrapRefused`/`EXTERNAL_DIRTY_GATE` — the external tree is dirty (commit/clean it; JM never auto-stashes), or the root is not in `external_roots.allow`, or it's a foreign git repo with no JM marker, or `bwrap` is off (FLAG2). |
| **Stale `git_commit.lock`.** | A daemon that died mid-commit can leave `state/control/autowork/git_commit.lock`. The worker acquisition is a bounded PID-stamped `LOCK_NB` retry (a dead holder fails cleanly → `auto_commit_failed`), but removing a stale lock by hand before restart is safe and fastest. |
| **A harness change isn't taking effect.** | The daemon caches its code at startup — **restart the child** (see [§12](#12-gaps--steps-still-requiring-a-human)). Workers/planner are fresh subprocesses and pick up changes immediately. |

---

## 12. Gaps / steps still requiring a human

These are points where the system does **not** fully self-recover and an operator must intervene. They are real defects/footguns, documented honestly:

1. **A malformed brief is silently parked as a deterministic plan failure — indistinguishable from a planner hallucination.**
   When `load_brief` rejects a brief (missing/empty/decorated heading, bad frontmatter), the planner subprocess exits non-zero with `failed validation`/`missing required field`/`PlanValidationError` in stderr — the cli actually prints the trigger phrase as `failed validation` (not `validation failed`). A plan-validation refusal now surfaces as the distinct `planner_validation_rejected` event rather than being mislabeled an LLM `planner_hallucination_discarded`; `_auto_promote` writes a **`deterministic` park marker** (`state/control/autowork/plan_attempts/<slug>.json` with `deterministic: true`), which suppresses re-planning for **86400s (24h)** after the first attempt. **Manual action:** grep the `planner_validation_rejected` (or legacy `planner_hallucination_discarded`) row's `stderr_tail`; if it names a validation error, fix the brief headings/frontmatter. Re-saving the brief (newer mtime than the marker) clears the park; otherwise delete `state/control/autowork/plan_attempts/<slug>.json`.
   - **Note:** B1 (`brief_status`) and B8 (`autowork_daemon`) changes require a daemon child restart (`kill -TERM "$(cat state/control/autowork.pid)"`) to take effect — the daemon caches those symbols at startup.

2. **A blocked task's retry budget is a time-bomb decoupled from the allowlist.**
   `_retry_blocked_tasks` re-stages everything in `state/tasks/blocked/*.json` whose backoff window has elapsed, up to budget 3 (1 for deterministic outcomes) — operating **purely on the blocked sidecars, with no allowlist or brief-eligibility check.** So if you **withdraw a brief's slug from the allowlist** (or archive the brief) while one of its tasks is parked in `blocked/`, the daemon will **still re-fire that task** on the next backoff tick and may re-dispatch a worker for withdrawn work. **Manual action:** to truly stop a withdrawn task, also remove `state/tasks/blocked/<tid>.json` (and its `.retry.json`/`.exhausted` sidecars). Withdrawing from the allowlist alone is insufficient.

3. **The daemon caches its own code at startup — a harness change is not live until a supervisor-respawn restart.**
   `autowork_daemon` binds its harness dependencies (`compute_brief_status`, `stage_task`, `can_run_parallel`, the self-heal primitives, and any lazily-imported module after first use) at process start and reuses them from `sys.modules`. A change to the **daemon's own loop / promotion / dispatch / staging / watchdog logic** does NOT take effect in the running process. **Manual action:** after landing such a change, restart the child: `kill -TERM "$(cat state/control/autowork.pid)"` (the supervisor respawns it). Worker/planner/orchestrator code is fresh per subprocess and needs no restart.

4. **Sensitive-path commits to the irreducible set never auto-approve.**
   The `_NEVER_AUTO_APPROVE` files (`agent_jail.py`, `dbus_proxy.py`, `paths.py`, `git_integration.py`, `orchestrator.py`, `interceptors.py`, `selfheal.py`, `autowork_daemon.py`, `services/**`) never auto-approve — no flag overrides this. **Manual action:** create an explicit owner/operator decision file `state/control/decisions/<task_id>.json` for the planned task, or the apply gate fails closed.

5. **Sensitive paths outside eligible auto-approve scope.**
   The hands-off posture has `auto_approve_sensitive_harness: true`, but it only widens eligible non-deny `harness/**` paths after content safety, RO-parent verification, and TOCTOU pinning. `config/**`, `scripts/**`, `services/**`, denylisted core files, a false flag, or a failed safety gate require `state/control/decisions/<task_id>.json` with `{"decision":"approve",...}` — and the `task_id` is only known **after** the brief is planned (read it from `plan_hooks_<slug>.json`). This is a manual, per-task step.

6. **Self-heal is diagnosis-only.**
   The inactivity watchdog and retry-exhaustion escalation spawn a jailed agent that writes a *corrected-spec diagnosis to its outbox* and is forbidden from touching the live repo or the allowlist. **Promotion of any corrective brief is an operator decision** (`selfheal_auto_promote: false`). The system surfaces a fix; it does not apply one.

7. **A planner that genuinely needs `> brief_max_size_bytes` (50000) or `> planner_timeout_sec` (1800s)** will be parked (`brief_too_large` / `plan_timeout`). Split the brief into an epic, or raise the limits in `harness/config.yaml` and restart the daemon.

---

## 13. State directory layout

```
state/
├── impl_progress.jsonl                 # MASTER telemetry ledger (the real one; NOT state/ledger)
├── control/
│   ├── autowork.pid                    # supervised daemon child PID
│   ├── orchestrator.flag               # WebUI/control_gate flag — NOT read by the daemon
│   ├── decisions/<task_id>.json        # operator approvals (harness_self_fix when auto-approve off)
│   └── autowork/
│       ├── auto_promote.allowlist      # slugs the daemon may promote (DENY-ALL if empty)
│       ├── external_roots.allow        # approved external bootstrap roots (empty/comment-only denies bootstrap)
│       ├── pause                       # EXISTENCE pauses dispatch
│       ├── full_stop                   # EXISTENCE = persistent hard stop (breaks loop + respawn)
│       ├── supervisor.stop             # WebUI/supervisor stop sentinel; cleared on fresh supervisor start
│       ├── auto_promote.disabled       # EXISTENCE disables promotion only
│       ├── plan_attempts/<slug>.json   # plan-park markers (attempts, last_ts, deterministic)
│       ├── runaway_ceiling.json        # persisted self-heal escalation counter (operator-clear)
│       ├── auto_approve_count.json     # persisted widened-approve counter
│       ├── git_commit.lock             # bounded commit lock
│       └── running/<task_id>.pid       # live worker pidfiles
├── tasks/
│   ├── <task_id>.json                  # staged / pending
│   ├── <task_id>.json.processing       # claimed by a worker
│   ├── blocked/<task_id>.json          # failed (+ .retry.json, .exhausted sidecars)
│   └── processed/<task_id>.json        # accepted / no_diff
├── output/<task_id>.{py,files.json,patches.json,no_diff}
├── planning/
│   ├── merged_plan.json                # final plan
│   ├── planner_progress.jsonl          # planner stage lifecycle
│   └── sessions/                       # per-agent blind drafts
└── autocompiler/<task_id>/             # population near-miss memory (if population: true)
```

`brief_hooks_<slug>.md` and `plan_hooks_<slug>.json` live at the **repo root** while active and are
auto-archived to `_autowork_archive/<date>_<label>/` on green integrate.

---

## 14. Glossary

- **Brief** — `brief_hooks_<slug>.md`; the only hand-authored artifact.
- **Slug** — the brief filename stem; what goes in the allowlist.
- **Plan** — the planner's `plan_hooks_<slug>.json`: a list of tasks, each with an oracle.
- **Task** — one atomic build unit (one file / one symbol), claimed and built by a worker.
- **Epic** — a brief (`epic: true`) that decomposes into child briefs.
- **Oracle** — a pre-committed pytest file (the task's `verification_command`); RED before, GREEN after.
- **Differential equivalence** — two candidates returning identical outputs across all fuzz inputs; the acceptance signal.
- **Live root** — an entry-point module (`orchestrator.py`, `orchestrator_worker.py`, `autowork_daemon.py`, `planner/cli.py`) the wire-up gate seeds reachability from.
- **Staging worktree / RO-parent gate** — isolated git worktree where the candidate is verified against a read-only snapshot of the parent commit before it touches the live tree.
- **Decision file** — `state/control/decisions/<task_id>.json`; operator approval for a sensitive-path commit.
- **Allowlist / external-roots allowlist** — deny-all safety boundaries (`auto_promote.allowlist`, `external_roots.allow`).

---

*JanusMask builds its own tooling through this same pipeline. The discipline is the product: propose
with LLMs, decide with verifiers, and never let the author grade its own exam.*
'''}
