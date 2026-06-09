# JanusMaskJR

**An autonomous code-generation factory.** JanusMaskJR compiles a high-level brief into *verified* working code by running two independent LLM agents (Claude + Gemini), accepting a result only when the two are proven **differentially equivalent** under a property-based fuzzer, AST-valid, and reachable from a live entry point — then committing it through an isolated git worktree behind a read-only-parent verification gate. A self-driving daemon decomposes briefs into plans, plans into tasks, dispatches workers, and retries or self-heals on failure, all behind an explicit operator control surface.

The design principle throughout: **correctness is enforced by *withholding and checking*, never by prompting.** Agents are jailed, blinded to each other, and gated by pure deterministic verifiers. The LLMs only *propose*; the harness *decides*.

> **Status (2026-06):** Core pipeline, autowork daemon, hierarchical (epic) planning, and the dual-sandbox safety model are live and in daily use. The `autocompiler/` package (population-based evolutionary compilation) is **Phase A** — pure, hermetic, default-OFF, not yet wired into the worker. ~650 test modules.

---

## Table of contents

- [The idea in one diagram](#the-idea-in-one-diagram)
- [Why it's built this way](#why-its-built-this-way)
- [Repository layout](#repository-layout)
- [Quick start](#quick-start)
- [The brief → working-code pipeline](#the-brief--working-code-pipeline)
- [The autowork daemon](#the-autowork-daemon)
- [Epic / hierarchical planning](#epic--hierarchical-planning)
- [The safety model](#the-safety-model)
- [`meta_task_type` taxonomy](#meta_task_type-taxonomy)
- [Configuration](#configuration)
- [Operating it: a complete runbook](#operating-it-a-complete-runbook)
- [Observability](#observability)
- [State directory layout](#state-directory-layout)
- [Testing](#testing)
- [The autocompiler subproject](#the-autocompiler-subproject)
- [Glossary](#glossary)
- [Troubleshooting & known gotchas](#troubleshooting--known-gotchas)

---

## The idea in one diagram

```
   brief_hooks_<slug>.md                         (a markdown+YAML spec you write)
            │
            ▼
   ┌──────────────────┐   blind dual-agent draft → diff → reconcile → adversarial
   │     PLANNER      │   review → auto-amend → validate → normalize
   │ harness/planner  │
   └──────────────────┘
            │  emits a PLAN: a list of tasks (each with its own oracle)
            ▼
   ┌──────────────────┐   one task at a time, claimed atomically
   │ ORCHESTRATOR     │
   │   _WORKER        │   ┌─ Claude  ─┐
   └──────────────────┘   │            ├─► two candidate implementations
            │             └─ Gemini  ─┘
            ▼
      ╔═══════════════ ACCEPTANCE GATES (pure, deterministic) ═══════════════╗
      ║ AST validity (ast_enforcer)  ·  differential fuzz equivalence        ║
      ║ (diff_fuzzer)  ·  the pre-committed oracle  ·  wired-ness            ║
      ║ (wire_up)  ·  apply-scope + RO-parent (git_integration)             ║
      ╚════════════════════════════════════════════════════════════════════╝
            │ pass → AST-merge into a staging worktree → ff-merge to live → commit
            │ fail → roll back the live tree, route to blocked/, retry or self-heal
            ▼
   a real commit on your branch
```

A **daemon** (`harness/autowork_daemon.py`) drives this loop unattended: it discovers briefs, kicks off the planner, stages tasks, and dispatches up to `parallel_cap` workers — but only for slugs you have explicitly placed on an allowlist, and only while the orchestrator flag is `resume`.

---

## Why it's built this way

A single LLM that writes code and also judges its own code is unreliable: it rationalizes its mistakes. JanusMaskJR removes that conflict of interest structurally.

- **Two authors, one judge that is neither.** Claude and Gemini each produce a candidate *blind to the other*. Agreement is not textual — it is **behavioral**: the two candidates must return identical outputs across hundreds-to-thousands of fuzzer-generated inputs (Popperian: one counterexample is a hard disproof; *N* clean rounds is a soft proof). A clean near-miss is still rejected — the verifier is load-bearing.
- **The test author is not the implementer.** Oracle tests run in a separate session (`harness/test_author.py`), and an oracle is only trusted if it **fails** a stripped `NotImplementedError` stub (non-vacuity) — so an agent cannot launder a stub past its own test.
- **The agent cannot reach what it isn't allowed to change.** Synthesis happens inside a bubblewrap jail (`harness/agent_jail.py`) that bind-mounts the repo read-only; fuzz execution happens inside a seccomp sandbox (`harness/sandbox.py`) that blocks `execve`/`fork`/`socket`. Containment is kernel-enforced, not hook-enforced.
- **Sensitive code is gated in tiers.** Free packages auto-commit; `harness/**`, `config/**`, `scripts/**`, `services/**` require an explicit operator decision file; a short irreducible list of files is owner-hand-edit only.

---

## Repository layout

| Path | Purpose |
|------|---------|
| `harness/` | The core engine (~22k LOC): orchestrator, worker, fuzzer, AST enforcer, git-integration, sandboxes, daemon, wire-up gate. |
| `harness/planner/` | Brief loading, blind dual-agent drafting, diff/reconciliation, plan validation + normalization, epic decomposition. |
| `harness/hooks/` | Claude/Gemini PreToolUse/PostToolUse hook implementations that confine agent tool use. |
| `overseer/` | Multi-turn supervisory agent scaffolding, procedure state machines, pure gate idioms (`GateResult`), web API. |
| `autocompiler/` | **Phase A** evolutionary-compilation package (population/Elo/selection/crossover/fitness/containment/vacuity/loop). Pure, default-OFF. |
| `tools/` | Small CLI utilities (e.g. brief reaper). |
| `scripts/` | Operator entry points: `run-autowork.sh`, `run-webui.sh`, `bootstrap.sh`, `brief_status.py`, maintenance tools. |
| `services/` | Long-running service processes (irreducible-trust tier). |
| `config/` | `harness/config.yaml` plus agent worker configs (`claude_*.json`, `gemini_*.toml`), and `autocompiler.yaml`. |
| `webui/` | Browser dashboard for status/approvals (loopback-only, token-authed). |
| `tests/` | ~650 test modules: `harness/`, `planner/`, `overseer/`, `autocompiler/`, `integration/`, `e2e/`, `adversarial/`. |
| `state/` | All runtime state (tasks, control flags, output, planning, telemetry). Not source — see [State directory layout](#state-directory-layout). |

---

## Quick start

```bash
# 1. Environment
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. One-time bootstrap (creates the state tree, allowlist, telemetry ledger, agent settings)
scripts/bootstrap.sh

# 3. System dependencies (for the sandboxes):
#    - bubblewrap (bwrap) + libseccomp   — agent jail and fuzz sandbox
#    - git                                — commit/apply
#    - the `claude` and `gemini` CLIs     — the two synthesis agents (configured under config/)

# 4. Sanity-check the test suite
make test-changed        # fast, impact-selected

# 5. Drive one brief (see the runbook below for the full hands-off flow)
```

**Prerequisites in detail**

- **Python 3.10+** (modern type hints, walrus, `from __future__ import annotations`).
- **`requirements.txt`**: `hypothesis`, `pyyaml`, `pytest` + `pytest-xdist` + `pytest-testmon` + `pytest-timeout`, `psutil`, `Pygments`.
- **External agent CLIs**: the harness shells out to `claude` and `gemini` as subprocesses (there is **no in-process model SDK** — every model call is a CLI subprocess consumed as NDJSON). Their flags, MCP config, and hook settings live under `config/` (`claude_worker.json`, `claude_mcp.json`, `claude_worker_*hooks.json`, `gemini_settings.json`, `gemini_worker_policy*.toml`).
- **System**: `bwrap` (bubblewrap) and `libseccomp` for isolation; `git`; optionally `xdg-dbus-proxy` for D-Bus filtering inside the jail; `node`/`nvm` only for the (future) JS target path.

---

## The brief → working-code pipeline

### 1. The brief

A brief is a markdown file named `brief_hooks_<slug>.md` at the repo root, with YAML frontmatter and five **required sections** (parsed by `harness/planner/brief_loader.py`):

```markdown
---
epic: false            # optional: true triggers hierarchical decomposition
interfaces: "..."      # optional: an API contract hint
working_dir: "..."     # optional: build into an external repo
dependencies: [...]    # optional
---

# Title
One-paragraph statement of what to build.

# Scope
What is in bounds.

# Non-Goals
What is explicitly out of bounds. (For an EDIT task, include the literal word
"integration" here to excuse the integration-test requirement.)

# Inputs
Fixed inputs to reuse — do NOT rebuild these.

# Deliverables
The concrete artifacts and the behavior that proves them done.
```

> **Heading gotcha:** the loader matches the bare section names (`# Inputs`, `# Scope`, …). A *decorated* heading like `# Inputs (do not rebuild)` is **not** recognized and the brief fails validation (`BriefValidationError`, surfaced as a discarded "hallucinated" plan). Keep the five headings bare.

### 2. The planner (`harness/planner/cli.py`)

The planner turns a brief into a **plan** (a JSON list of tasks) through an ordered pipeline:

1. **`load_brief`** — validate sections, compute a content SHA-256 for provenance.
2. **blind drafts** (`blind_draft.py`) — Claude and Gemini each draft a plan *independently*; neither sees the other.
3. **diff** (`diff_extractor.py`) — structurally compare the two drafts.
4. **reconcile** (`reconciliation.py`) — merge into one plan, resolving conflicts.
5. **adversarial review** (`adversarial_review.py`) — a critique pass flags infeasible or unsafe decompositions.
6. **auto-amend** (`auto_amend.py`) — optionally rewrite per the critique.
7. **validate** (`plan_validator.py`) — enforce plan shape (see below).
8. **normalize** (`plan_normalizer.py`) — dedupe oracles, enforce module-first ordering, inject committed oracle sources, **strip dependencies that name no in-plan task** (so cross-brief slug references can't wedge dispatch).

**Plan-shape rules the validator enforces** (`plan_validator.py`): unique `task_id`s; a valid `meta_task_type` from the taxonomy; ≥2 `edge_cases` mirrored in regression/property tests; for any task that **edits a non-test `.py` file**, a wiring oracle (a `*_wired` test named in its `verification_command`) *or* a paired `test_authoring` sibling; integration tests required **unless** the literal word `integration` appears in the task's `non_goals`.

### 3. Synthesis & acceptance (`harness/orchestrator_worker.py`, `harness/orchestrator.py`)

A worker claims one task (atomic rename to `<id>.json.processing`) and runs:

1. **Dual-agent synthesis** — `run_both_agents()` spawns Claude and Gemini in parallel; each emits a candidate. (`claude_fallback` covers a Claude failure.)
2. **AST validation** — `ast_enforcer.validate_code()` rejects syntax errors, nondeterminism (`random`, wall-clock), and dangerous calls (`eval`/`exec`); up to `max_ast_retries` retries.
3. **Differential fuzzing** — `diff_fuzzer.differential_fuzz()` generates type-aware inputs (Hypothesis), runs both candidates in the seccomp sandbox, and compares outputs. `FuzzResult.equivalent == True` is the gate. A single divergent input fails the candidate; the cap is 20 recorded failures.
4. **The oracle** — the task's pre-committed `verification_command` (a pytest file) must pass.
5. **Wired-ness** — `wire_up.check_wired()` confirms the new module is reachable from a **live root** (`orchestrator.py`, `orchestrator_worker.py`, `autowork_daemon.py`, `planner/cli.py`) — or referenced from `config/**` (dynamic wiring), which is how a new package registers before it is imported. (Configurable via `autowork.wire_up_gate`, currently **on**.)
6. **Commit** — `git_integration.commit_accepted_output()` AST-merges the winner into a **staging worktree**, verifies it against a read-only archive of the parent commit (the **RO-parent gate**), enforces the apply-scope policy, then fast-forward-merges to the live tree and commits.

On any **non-accept** outcome the worker rolls the live tree back (`_rollback_live_tree()`, scoped strictly to the task's declared files) and routes the task to `blocked/`.

---

## The autowork daemon

`harness/autowork_daemon.py` is the unattended driver. Each iteration:

1. **Reaps** finished worker pidfiles and reclaims orphaned `*.processing` tasks.
2. **Retries** blocked tasks whose backoff has elapsed; **terminally blocks** tasks whose dependencies failed.
3. **Harvests** self-heal briefs (if `selfheal_auto_promote` is on).
4. **Auto-promotes** (`_auto_promote` → `_auto_promote_brief_eligible`): for each brief, if its slug is **allowlisted** and it is younger than `brief_max_age_seconds`, the daemon stages any unstaged plan tasks and — for at most one unplanned brief per iteration — kicks off the planner.
5. **Decides** (`collect_dispatchable_tasks`): ranks tasks whose dependencies are all *accepted* and that don't conflict on files, then dispatches up to `parallel_cap` workers.

**The allowlist is the safety boundary.** `state/control/autowork/auto_promote.allowlist` is one slug per line; an empty/comment-only file is **deny-all** (the daemon dispatches nothing). For an epic, allowlisting the epic slug transitively admits its children (via `hierarchical_planning`).

**Control surface:**

| File | Effect |
|------|--------|
| `state/control/orchestrator.flag` | `resume` / `pause` the whole loop. |
| `state/control/autowork/auto_promote.allowlist` | Which brief slugs the daemon may act on. Deny-all by default. |
| `state/control/autowork/full_stop` | Operator-persistent hard stop (never auto-cleared). |
| `state/control/decisions/<task_id>.json` | `{"decision":"approve"}` — required to commit a `harness_self_fix` task into a sensitive path. |

---

## Epic / hierarchical planning

A brief with `epic: true` (and `hierarchical_planning.enabled: true`, currently on) is decomposed instead of built directly. `_run_epic_pipeline` (`planner/cli.py`) has both agents draft a **child-brief set**, reconciles it, writes each child as its own `brief_hooks_<child-slug>.md` at the repo root, and persists an epic record `plan_hooks_<slug>.json` (`plan_kind: "epic"`, `child_slugs: [...]`). On the next daemon iterations the children are discovered, planned, and built like any leaf — and because the parent epic slug is allowlisted, the children are admitted transitively. Nesting is capped at `max_planner_depth` (4).

**You (the planner) decide the tree.** The epic brief *suggests* a decomposition; the agents produce the actual child set. Sequencing between children is a **brief-level** concern (build order, held briefs) — not intra-plan task dependencies. (A child whose frontmatter lists sibling *slugs* as dependencies will have those stripped at normalization, since a slug is not an in-plan `task_id`; ordering siblings is done by holding briefs back until their dependencies have landed.)

---

## The safety model

### Write-policy tiers (`harness/git_integration.py`, `harness/orchestrator.py`)

| Tier | Paths | What's required to commit |
|------|-------|---------------------------|
| **Free** | anything *not* under the sensitive globs | RO-parent gate only — auto-commits. A new top-level package (e.g. `autocompiler/`, `overseer/`) is free. |
| **Sensitive** | `harness/**`, `config/**`, `scripts/**`, `services/**` (`_SENSITIVE_APPLY_GLOBS`) | `meta_task_type: harness_self_fix` **and** an operator decision file `state/control/decisions/<task_id>.json`. |
| **Irreducible** | `agent_jail.py`, `dbus_proxy.py`, `paths.py`, `git_integration.py`, `orchestrator.py`, `interceptors.py`, `selfheal.py`, `autowork_daemon.py`, `services/**` (`_NEVER_AUTO_APPROVE`) | **Owner hand-edit only.** No gate overrides this. |

The cardinal rule: **never hand-edit production outside the pipeline.** Free and sensitive code is built by the pipeline; only oracles/tests are hand-authored; the irreducible set is cleared with the owner first.

### The two sandboxes (do not conflate them)

1. **Agent-synthesis jail** — `agent_jail.py::build_jail_argv` — bubblewrap. The repo is bind-mounted **read-only**; only the agent's work dir and session dirs are writable; `--unshare-net --unshare-ipc` on the execute path; D-Bus is filtered through `xdg-dbus-proxy`. The agent *cannot* write `harness/*.py` — the kernel forbids it.
2. **Fuzz execution sandbox** — `sandbox.py::Sandbox.execute` — `Popen` under rlimits + a libseccomp filter that **blocks `execve`, `fork`, `socket`**, with per-input `os.fork()` isolation. (Consequence: a Node process needs `execve`+`fork`, which this sandbox forbids — JS execution would have to route through the bwrap jail, which is why the JS target is a *later* phase.)

### Author ≠ implementer

`test_author.py` runs the oracle author in its own session dir (`author_session_dir`) with `JANUSMASK_*` env scrubbed, and accepts an oracle only if it is **non-vacuous** (`oracle_is_non_vacuous`: it must fail a `NotImplementedError` stub). The author sees the reference source but is structurally not the blind implementer.

---

## `meta_task_type` taxonomy

Every task declares a `meta_task_type` (`harness/planner/taxonomies.py`) that selects its verification policy. Key flags: `bypass_fuzzer` (skip differential fuzzing — for data/config/orchestration where it's ineffective), `skip_structural_decomp` (don't auto-split on divergence), `skip_smoke_gates` (skip the import/narrow pre-gates), `stateful_fuzz` (sequence-based fuzzing).

| Type | Typical use |
|------|-------------|
| `data_model` | Pure data structures / dataclasses (bypass fuzzer). |
| `config_schema` | Config readers / schema (bypass fuzzer, skip smoke). |
| `validation` | Pure gate/validator functions. |
| `planner_tooling` | Planner-side pure helpers. |
| `orchestration` | Coordination logic over injected seams. |
| `harness_plumbing` | Internal harness glue (bypass fuzzer). |
| `io_adapter` / `state_machine` | Side-effecting / stateful (stateful fuzz). |
| `cli_tooling`, `refactor`, `logging_observability` | Standard fuzzed code. |
| `test_authoring` | Authors an oracle for a module-under-test (`mutation_target`). |
| `test_unit/integration/e2e/acceptance` | Test code (self-verifying). |
| `harness_self_fix` | A gated repair to a sensitive harness path (needs a decision file). |
| `epic_planning` | Decomposition only, no code. |
| `docs_writing`, `hooks_integration`, `mcp_*`, `sandbox_infra` | As named. |

---

## Configuration

`harness/config.yaml` is the master knob file. Current values of the load-bearing keys:

```yaml
autowork:
  enabled: true
  parallel_cap: 5             # max workers dispatched at once (clamped 1–16)
  poll_interval_sec: 5        # task-queue poll cadence when active
  heartbeat_sec: 1800         # idle sleep
  planner_timeout_sec: 1800   # planner wall-clock budget
  brief_max_age_seconds: 604800   # 7 days; older briefs are not auto-promoted
  wire_up_gate: true          # enforce reachability on new modules at accept
  selfheal_auto_promote: false
  archive_spent_briefs: false # archive a brief's paperwork once its task is accepted

hierarchical_planning:
  enabled: true               # epic decomposition on
  max_planner_depth: 4
  failure_propagation: true

synthesis:
  active_agents: [claude, gemini]
  max_ast_retries: 3
```

(Agent commands, sandbox limits, fuzzing budgets, hook mode, and the overseer live in the same file; see comments inline.)

---

## Operating it: a complete runbook

### Hands-off: dispatch one brief via the daemon

```bash
cd /path/to/JanusMaskJR

# 1. Place your brief at the repo root.
#    brief_hooks_my_feature.md   (epic: true for a decomposed build)

# 2. Allowlist its slug (the brief_hooks_<slug>.md stem). Deny-all otherwise.
echo "my_feature" >> state/control/autowork/auto_promote.allowlist

# 3. Make sure the loop is resumed and not full-stopped.
echo "resume" > state/control/orchestrator.flag
rm -f state/control/autowork/full_stop

# 4. (If a prior run died) clear any stale lock.
rm -f state/control/autowork/git_commit.lock

# 5. Start the daemon (auto-respawning supervisor).
scripts/run-autowork.sh --state-dir state --logs-dir logs --config harness/config.yaml
```

The daemon plans the brief, stages its tasks, and dispatches workers. Watch progress in `state/impl_progress.jsonl` (see [Observability](#observability)).

**Daemon flags:** `--state-dir`, `--logs-dir`, `--config`, `--once` (single iteration, no respawn), `--max-backoff`. PID → `state/control/autowork.pid`; logs → `logs/autowork.log`.

**Stop it:**
```bash
echo "pause" > state/control/orchestrator.flag     # drain then idle
touch state/control/autowork/full_stop              # operator-persistent hard stop
kill -TERM "$(cat state/control/autowork.pid)"      # supervised shutdown (≤30s drain)
```

### Building into a sensitive path (`harness_self_fix`)

A task that edits `harness/**`/`config/**`/`scripts/**`/`services/**` needs a decision file. The `task_id` is only known after the brief is planned, so:

1. Allowlist the fix brief's slug; let the daemon plan it.
2. Read the staged `task_id` from `plan_hooks_<slug>.json`.
3. Write `state/control/decisions/<task_id>.json`:
   ```json
   {"decision": "approve", "task_id": "<task_id>", "reason": "...", "operator": "you"}
   ```
4. The worker commits on the next dispatch.

### Manual drive (no daemon)

```bash
# Plan
python -m harness.planner.cli brief_hooks_my_feature.md \
  --output-plan plan_hooks_my_feature.json --config harness/config.yaml

# Stage one task (in-process API), then run the worker on it
python -m harness.orchestrator_worker --state-dir state --task-id <task_id> --config harness/config.yaml
```

### Web dashboard

```bash
scripts/run-webui.sh                  # starts WebUI (+ orchestrator); loopback only
# prints: WebUI ready at http://127.0.0.1:8765/?token=<token>
```
Flags: `--webui-only`, `--orchestrator-only`, `--port`, `--host`, `--foreground`. The auth token is written to `state/control/operator_token`.

---

## Observability

Monitor a run **cheaply** by tailing the telemetry ledger rather than the agent logs:

- **`state/impl_progress.jsonl`** — append-only JSONL. Each row: `{"ts", "phase", "task_id", "event", "detail", ...}`. The events you care about:
  - `plan_kickoff` — the planner started on a brief.
  - `planner_hallucination_discarded` — a draft was rejected (empty/too-fast/invalid); `detail` carries the reason.
  - `launch` / `launch_sequential` — a worker was dispatched.
  - `auto_commit` (`phase: accepted`) — a task landed; `commit_sha` + `files` included.
  - `task_blocked` / `retry_exhausted` / `dependency_failed` — failure paths.

  A tight watch:
  ```bash
  tail -F state/impl_progress.jsonl \
    | grep -E '"event": "(plan_kickoff|auto_commit|task_blocked|planner_hallucination_discarded|retry_exhausted)"'
  ```
- **`scripts/brief_status.py`** — ground-truth sweep classifying every brief/plan as EPIC / DONE / PENDING / NEEDS-PLAN / ORPHAN by running each oracle against the current tree. `--archive <stamp>` moves completed paperwork to `_autowork_archive/`.
- **`logs/autowork.log`** — daemon poll/promote/dispatch decisions. **`logs/harness.log`** — orchestrator phases (synthesis/fuzz/commit).
- **`state/output/<task_id>.*`** — the worker's emission: `.py` (single file), `.files.json` (whole-file map), `.patches.json` (symbol patches), `.no_diff` (already-satisfied marker).
- **`state/tasks/`, `state/tasks/blocked/`, `state/tasks/processed/`** — queue, failures (+ `.retry.json` sidecars), and completed tasks.

---

## State directory layout

```
state/
├── impl_progress.jsonl              # master telemetry ledger (JSONL)
├── STATE.json                       # flock-protected orchestrator working state
├── control/
│   ├── orchestrator.flag            # "resume" / "pause"
│   ├── autowork.pid                 # supervised daemon PID
│   ├── autowork/
│   │   ├── auto_promote.allowlist   # slugs the daemon may act on (deny-all if empty)
│   │   ├── full_stop                # operator-persistent hard stop
│   │   └── running/<task_id>.pid    # live worker pidfiles
│   └── decisions/<task_id>.json     # operator approvals for harness_self_fix
├── tasks/
│   ├── <task_id>.json               # staged (pending)
│   ├── <task_id>.json.processing    # claimed by a worker
│   ├── blocked/<task_id>.json       # failed (+ .retry.json, .exhausted sidecars)
│   └── processed/<task_id>.json     # accepted / no_diff
├── output/<task_id>.{py,files.json,patches.json,no_diff}
├── planning/
│   ├── merged_plan.json             # final plan from the planner
│   ├── planner_progress.jsonl       # planner stage lifecycle
│   └── sessions/                    # per-agent blind drafts
└── sessions/                        # canonical per-task submission records
```

---

## Testing

```bash
make test-changed   # impact-selected (testmon), hermetic inner loop — fastest
make test-fast      # parallel screen (xdist, ~4–8 workers). NOT a gate: a class of
                    #   non-hermetic tests (shared on-disk state) flakes under -n auto.
make test-full      # serial authoritative gate — zero flake, slower
```

Layout: `tests/harness/`, `tests/planner/`, `tests/overseer/`, `tests/autocompiler/`, `tests/integration/`, `tests/e2e/`, `tests/adversarial/`, plus top-level module tests (~650 modules total). `make test-fast` is a **screen**, not a gate — reconfirm anything it flags with `make test-full` before trusting it.

> **Known pre-existing failure:** `tests/planner/test_brief_loader.py::test_sha256_line_ending_invariant` is a Hypothesis property test that finds a lone-`\r` input where the brief loader normalizes `\r\n`→`\n` but not bare `\r`, so the content hash differs. It is latent (unrelated to the pipeline's correctness) and a candidate for a `harness_self_fix` follow-up.

---

## The autocompiler subproject

`autocompiler/` is an in-progress reframing of the factory from *single-shot-or-die* into a **memory-bearing evolutionary compiler**: instead of discarding a clean near-miss when one of ≤20 fuzz inputs diverges, candidates accumulate in a rated **population**, near-misses are *scored* (not thrown away), and selection + crossover steer the generation budget toward the promising lineage — while every existing correctness gate stays load-bearing. (Inspired by the AlphaProof "Nexus" design: population DB + Elo + P-UCB selection + AST crossover, translated onto JanusMaskJR's real seams.)

**Status: Phase A — pure, hermetic, default-OFF, not yet wired into the worker.** The nine modules are stdlib-only, drive all I/O through injected seams, and are exercised by pre-committed RED oracles in `tests/autocompiler/` (contract + `*_wired`). They are registered for dynamic wiring in `config/autocompiler.yaml` and are inert until the (owner-gated) Phase-C wiring lands — `ac_enabled()` is fail-closed `False` because the `autocompiler:` config subtree does not exist yet.

| Module | Role |
|--------|------|
| `flags.py` | `ac_enabled(key)` — fail-closed reader for the `autocompiler:` config subtree. |
| `population.py` | `Candidate` + `PopulationDB` — durable JSON candidate store under an injected `state_dir`. |
| `fitness.py` | `compute_fitness(...)` — pure fitness vector; error/hard-disproof/vacuous/failed-gate ⇒ prune-floor; near-miss ⇒ rated, not pruned. |
| `elo.py` | `expected_score`/`update_elo`/`tournament_round` — pairwise Elo via an injected rater seam. |
| `selection.py` | `p_ucb(...)` — P-UCB selection (unseen candidates explored first; deterministic ties). |
| `crossover.py` | `ast_crossover`/`file_crossover` — recombine candidates via an injected `_ast_merge` seam (no real git). |
| `containment.py` | `extract_evolve_ranges` + `check_write_containment` — confine edits to `# JM-EVOLVE-BLOCK` ranges. |
| `vacuity.py` | stub / complexity-floor / exception-swallow gates returning `GateResult`. |
| `loop.py` | `step(db, seams)` — one select→operate→run→fitness→insert→rate transition; never spawns a process or model. |

Design notes and the full epic brief live under `autocompiler_research/`.

---

## Glossary

- **Brief** — a markdown+YAML spec (`brief_hooks_<slug>.md`); the unit of work you author.
- **Plan** — the planner's JSON output: an ordered list of tasks, each with an oracle.
- **Task** — one atomic build unit (one file / one symbol), claimed and built by a worker.
- **Epic** — a brief that decomposes into child briefs (`epic: true`).
- **Oracle** — a pre-committed pytest file that is a task's authoritative contract; RED before the build, GREEN after.
- **Differential equivalence** — two candidates returning identical outputs across all fuzz inputs; the acceptance signal.
- **Live root** — an entrypoint module the wired-ness gate seeds reachability from.
- **Staging worktree / RO-parent gate** — an isolated git worktree where the candidate is verified against a read-only snapshot of the parent commit before it touches the live tree.
- **Decision file** — an operator approval (`state/control/decisions/<task_id>.json`) authorizing a sensitive-path commit.
- **Allowlist** — `auto_promote.allowlist`; the slugs the daemon is permitted to act on. Deny-all by default.

---

## Troubleshooting & known gotchas

- **Daemon does nothing.** Check `state/control/orchestrator.flag` is `resume`, the slug is in `auto_promote.allowlist`, no `full_stop` sentinel exists, and the brief is younger than 7 days. The allowlist is **deny-all** when empty.
- **Brief rejected as a "hallucinated"/empty plan.** Usually a malformed brief: ensure the five section headings are **bare** (`# Inputs`, not `# Inputs (...)`), and that an EDIT task's `non_goals` contains the literal word `integration`, and that a module-creating task names a `*_wired` oracle in its `verification_command`.
- **A retry keeps failing identically.** A stale emission sidecar in `state/output/` can mis-route the accept path; the worker now purges them on non-accept outcomes. If you re-stage manually, also clear `<task_id>.{patches,files}.json`.
- **New module rejected as an orphan** by the wire-up gate. Either import it from a live root, or register its dotted path under `config/**` (the gate's sanctioned dynamic-wiring classification) until real wiring lands.
- **`auto_commit_failed` on a new file.** The patches path cannot *create* files — emit a new module **whole-file**, and keep a task to **one file**. Don't list non-target files (e.g. a config you only register) in `files_touched`.
- **Stale `git_commit.lock`.** A daemon that died mid-commit can leave `state/control/autowork/git_commit.lock`; remove it before restarting.

---

*JanusMaskJR builds its own tooling through this same pipeline. The discipline is the product: propose with LLMs, decide with verifiers, and never let the author grade its own exam.*
