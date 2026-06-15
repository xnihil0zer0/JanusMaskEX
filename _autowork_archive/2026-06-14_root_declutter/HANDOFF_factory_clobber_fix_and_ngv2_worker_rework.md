# HANDOFF — Factory reliability fix (planner clobber engine + dep-gate wedge) + NGv2 worker-epic rework

**Date authored:** 2026-06-13 (PM)
**Repos:** `/home/xnihil0zer0/JanusMaskJR` (the factory, branch `master`) and `/home/xnihil0zer0/NobleGreedv2` (the build target, branch `master`)
**Author context:** Adversarial-audit session. Diagnosis was produced, then **re-verified by a 4-agent parallel ground-truth sweep** (findings below are post-verification, not first-pass guesses).
**Owner-approved scope:** *Everything incl. NGv2 worker rework* + *Quarantine queued clobbers, flag `report.py` for owner*.

---

## 0. CURRENT LIVE STATE (read this first)

- **Daemon is PAUSED by the audit session.** Pause flag exists at `state/control/autowork/pause` (persistent; the daemon only reads its *existence*, never auto-clears it — `harness/autowork_daemon.py:288-289`, checked at `:1712`). No new dispatch occurs while it exists.
- **Daemon process:** `python -m harness.autowork_daemon` (was pid 3034903, started 13:21) is **supervised by `scripts/run-autowork.sh`** (was pid 3014741). To load new harness code you must **kill the daemon child only** — the supervisor respawns it with capped backoff. **Never `nohup` a second daemon** (memory: `daemon-supervisor-respawn`).
- **Pidfile:** `state/control/autowork.pid`. **Hard stop** (halts dispatch + promotion + breaks the loop + stops supervisor respawn) = `state/control/autowork/full_stop` (`:291-299`).
- **Nothing has been written/committed by the audit session** except the pause flag. No briefs, no oracles, no queue surgery yet.
- **An in-flight worker** (`verify-worker-oracle`, dispatched ~18:13 before the pause) may still be draining or have exhausted — check `ps` and `state/tasks/blocked/` before acting.
- **Uncommitted working-tree change:** `harness/config.yaml` has `selfheal_auto_promote: false → true` (mtime ~16:12, appeared mid-epic, **uncommitted**). **Owner decision needed** — commit it intentionally or revert it. It added self-heal retry churn during the 06-13 PM epic (second-order amplifier, not a root cause).

**Pre-flight before any action:** confirm no `orchestrator_worker` is mid-commit (`ps aux | grep orchestrator_worker`) and that `state/control/autowork/git_commit.lock` is not held by a live pid — running manual git while a worker commits causes the `git_commit.lock` reset-race (memory: `stale git_commit.lock WEDGES daemon`).

---

## 1. VERIFIED GROUND TRUTH (4-agent sweep)

The owner's intuition ("self-inflicted damage, less reliable yesterday") is **directionally correct, but the culprit is NOT what the first-pass diagnosis claimed** (the dep-gate). Reconciled facts:

### 1a. The reliability drop is real but localized (Agent 4)
From `state/impl_progress.jsonl` (~104k rows), commit-rate = auto_commit / (auto_commit + reject_rollback):

| metric | 06-10 | 06-11 | 06-12 | **06-13** |
|---|---|---|---|---|
| auto_commit (success) | 30 | 47 | 60 | 32 |
| reject_rollback | 24 | 31 | 42 | 40 |
| retry_exhausted | 1 | 6 | 7 | **11** |
| dependency_failed | 0 | 0 | 2 | **12** |
| **commit_rate** | 56% | 60% | 59% | **44%** |

- **06-13 AM** (drive-backup + webui epics, 00:44–04:41) = **56%, fine.**
- **06-13 PM** (NGv2 bounty-worker epic, 14:00–18:19) = **41%; ALL 12 `dependency_failed` + 11 `retry_exhausted` are here.**
- **All five suspected harness commits are EXONERATED as the regression:** `3715f3f` (dep-gate), `436df86` (vcmd-upgrade — fails-open + skips test-authoring), `d29f60c` (brief dep gate — *reports* failures, doesn't cause them), `1e41ecb` (codex — inert, `active_agents` stays `[claude,gemini]`), and `acc7edb`→`e7b4939` (a literal **0-line** no-op: `git diff acc7edb~1 e7b4939 -- harness/autowork_daemon.py` is empty).

### 1b. PRIMARY ROOT CAUSE — planner has no cross-brief / committed-module dedup (Agents 2 & 4)
The planner decomposes **each brief in isolation** and only dedups `test_authoring` oracles, never impl `files_touched`:
- `harness/planner/cli.py:305` loads only the current brief; `:319` `blind_drafts(...)` agents have **zero** visibility into other briefs or the external repo's already-committed modules; `repo_root` only reaches the pipeline at `:357` `normalize_plan(...)` — *after* decomposition.
- `harness/planner/plan_normalizer.py:755-756` dedups only oracles (`_dedupe_oracles`, `_drop_redundant_precommitted_oracles`). Impl `files_touched` is **never** cross-checked against other tasks or prior commits.
- `harness/planner/staging.py:125-140` reads `impl_progress.jsonl` only to avoid re-staging within the *same* plan, not across briefs.
- Smoking gun: `brief_hooks_conductor-glue.md:~12` literally lists "three **NEW** whole-file modules … `gated_advance.py` … `session_get_task.py`" — both already built hours earlier by the `ng-`prefixed leaves.

**Clobber inventory (complete):**
- **(a) Happened & reverted (2):** `e35d27a` `session_get_task.py` → reverted by `adef389`; `e81f2c8` `gated_advance.py` → reverted by `4beb88b`. Both reverts **sound** (oracles 12 + 31 green against restored canon; no live caller depended on the divergent versions).
- **(b) Happened & UNCAUGHT (1):** **`67dc8d0` overwrote `ngv2/workers/report.py`** (already built by `8c5198c`) with a divergent `run_stage` contract (filename `{phase}.json` → hardcoded `'submission.report.json'`; adds `'stage':'report'`). **Slipped through silently because no `test_report.py` oracle was ever committed.** This is the dangerous class: clobbers of un-oracled modules leave no RED to catch them.
- **(c) Queued clobber risks (≥5 tasks, 2 modules):** `triage-worker-impl` (+`-oracle`,`-tests`) → already-committed `ngv2/workers/triage.py`; `conductor-outer-loop` (+`test-conductor-loop-mutation`) → already-committed `ngv2/conductor_loop.py` with a **divergent return contract** (`{final_state,reason,steps}` vs committed `{steps,final_step}`). **`triage-worker-impl.json` is the newest-mtime pending task = the NEXT thing the daemon dispatches on resume.** Both target modules have **no committed oracle** → would clobber silently.

### 1c. SECONDARY (real, narrow) — dep-gate is actively wedging 4 tasks (Agent 1)
`3715f3f` did flip `_brief_dep_gate_ok` (`harness/autowork_daemon.py:1637-1715`) from DISPATCH→HOLD on absent/blocked/zombie deps (released only on terminal-ACCEPTED), and `4737f6f` inverted two "no-deadlock" tests to require the HOLD. The A.1 bug it fixed (oracle dispatching before its impl lands, dep reads ABSENT at plan time via `harness/brief_status.py:23`) was **real** — its *intent* is sound; its blast radius is the defect.

**Live wedge (confirmed by reconstructing `compute_brief_status` + running the gate read-only):** 4 pending tasks owned by brief `conductor-runtime` are HELD every tick and filtered at `:1709` before dispatch:

| Held task | Blocking frontmatter dep | Dep state |
|---|---|---|
| `conductor-outer-loop` | `fsm_and_task_primitives` | **ABSENT** |
| `conductor-seams-assembler` | `agent_workers` | **ABSENT** |
| `test-conductor-loop-mutation` | (both) | ABSENT |
| `test-conductor-seams-mutation` | (both) | ABSENT |

**Unbreakable because of a brief slug typo:** `brief_hooks_conductor-runtime.md` frontmatter spells deps with **underscores** (`fsm_and_task_primitives`, `agent_workers`), but the real **completed** brief is `brief_hooks_fsm-and-task-primitives.md` (slug `fsm-and-task-primitives`, **hyphens**, 4 task_ids/0 remaining), and `agent_workers` has **no brief under any spelling**. Brief-slug deps are **stripped before task JSON** (`harness/planner/plan_normalizer.py:614 _strip_unresolvable_dependencies`), so the task-level A3 breaker (`harness/autowork_daemon.py:973 _block_dependency_failed_tasks`, wired at `:1385`) can **never** see them, and **there is no brief-level deadlock-breaker**. So absent/un-plannable/misspelled brief-deps wedge forever with no telemetry.

### 1d. NGv2 worker epic is "validated but non-functional" scaffolding (Agent 3)
Confirmed across all checks; ~1,765 LOC across 10 committed modules + 2 phantom, **none reachable on any live path**:

| Module | Exists | Tested by | Wired how | Runnable as spawned (`python -m ngv2.workers.<p>`) |
|---|---|---|---|---|
| `ngv2/workers/hunt.py` | **NO** | — | argv string only | **errors** (`No module named`) |
| `ngv2/workers/poc.py` | **NO** | — | argv string only | **errors** |
| `ngv2/workers/triage.py` (403) | yes (`06b46b9`) | **none** | `run_stage` seam | **exit 0, NO output file** (no `__main__`) |
| `ngv2/workers/verify.py` (181) | yes (`6b57c38`) | **none** | `run_stage` | exit 0, no output |
| `ngv2/workers/detonate.py` (299) | yes (`26eb441`) | **none** | `run_stage` | exit 0, no output |
| `ngv2/workers/report.py` (300) | yes (`67dc8d0`, clobber) | **none** | `run_stage` | exit 0, no output |
| `ngv2/workers/novelty.py` (307) | yes (`5b58fad`) | **none** | `run_stage` | exit 0, no output |
| `ngv2/stage_command_map.py` (39) | yes | pure dict-builder test | imported by `hunt_conductor` | n/a (pure builder; builds `python -m ngv2.workers.<phase> --session-id --repo --target --out`) |
| `ngv2/conductor_loop.py` (40) | yes (`53f967e`) | seam-loop test | **ORPHAN** | n/a |
| `ngv2/hunt_conductor.py` (47) | yes | seam-mock test | **ORPHAN** (calls `seams['spawn']`, bound nowhere) | n/a |
| `ngv2/gated_advance.py` (112) | yes (`4beb88b` restore) | real seam test ✓ | pure seam fn | n/a |
| `ngv2/session_get_task.py` (37) | yes (`adef389` restore) | real seam test ✓ | pure extractor | n/a |

- The spawn contract (`stage_command_map`) is **non-functional for all 7 phases**: hunt/poc → ModuleNotFoundError; the 5 existing workers have **no `__main__`/argparse**, so they exit 0 and write nothing to `--out`.
- **No live spawner** binds `seams['spawn']`; `conductor_loop`/`hunt_conductor` are orphans wired only inside `*_wired` mock tests.
- 7 oracles exhausted (`state/tasks/blocked/*.exhausted`): `exploit-detonate-worker-oracle`, `novelty-worker-oracle`, `report-worker-oracle`, `verify-worker-{oracle,test,impl}`, `ngv2_novelty_gate_red_oracle`.

### 1e. Parallel-agent footprint (Agent 4)
A second agent did manual mid-run surgery on 06-13 PM (all commit under the daemon's `JanusMask Rebuild Engine` identity, so not author-filterable): `state/tasks/_superseded_workers_base/` (15:36) + `_superseded_early_phase/` (15:26) pruning; `auto_promote.allowlist` rewritten 16:52 to a focused 3-slug scope (backup `.full.63cdda4.bak` at 15:49); the two NGv2 reverts at 17:39–17:40. **Coordinate with the parallel agent before resuming** — concurrent surgery on the same queue is itself a destabilizer.

> **Continuable verification agents** (SendMessage to resume with full context): dep-gate `ac2957bbe5b2b73bf`; clobbers `aa108b7f102add194`; NGv2 workers `a758da7f6aeb2554b`; reliability timeline `a99cd0f4c2fc4c26f`.

---

## 2. THE PLAN (phased, owner-approved full scope)

**Guiding rules (do not violate):**
- **harness/**, config/**, scripts/** edits MUST go through the pipeline as `meta_task_type: harness_self_fix` with a pre-placed decision file `state/control/decisions/<task_id>.json` (`harness/orchestrator.py:2880`, gating at `:2240`, decision read at `:2299-2306`). **Never hand-edit production outside the pipeline** (memory: `never-hand-edit-production-outside-pipeline`). Templates: any existing file in `state/control/decisions/`.
- **Brief (`brief_hooks_*.md`) and oracle/test files ARE hand-authorable** — those are inputs, not production. Commit the oracle BEFORE the harness_self_fix worker run (memory: `untracked-test-poisons-patches-commit`).
- **Anti-seesaw:** a fix to a symbol must verify the **UNION of all oracle files touching it.** The dep-gate touches **two**: `tests/harness/test_dep_gate_no_premature_release.py` AND `tests/harness/test_brief_level_dep_gate.py`.
- **New module = single-file whole-file**; R-ANCHOR new symbols (memory). NGv2 builds need `external_roots.allow` (`state/control/autowork/external_roots.allow`) + the external-root build recipe (memory: `ngv2-phase0-external-build-proven`).
- After landing any `autowork_daemon.py`/planner change, **restart the daemon** (kill child → supervisor respawns) so the new code loads — pause/unpause alone does NOT reload Python.

### Phase 0 — Quiesce & coordinate (mostly done)
- Daemon already paused. Confirm the in-flight worker drained. **Coordinate with the parallel agent** (owner to confirm it is stopped/redirected) before queue surgery.
- Resolve the uncommitted `selfheal_auto_promote` flag with the owner.

### Phase 1 — Quarantine queued clobbers (out-of-factory, manual, reversible)
Move the queued clobber tasks out of `state/tasks/` into a quarantine dir (e.g. `state/tasks/_quarantine_clobber_2026-06-13/`) so resume cannot re-clobber:
- `triage-worker-impl.json`, `triage-worker-oracle.json`, `triage-worker-tests.json` (→ committed `ngv2/workers/triage.py`)
- `conductor-outer-loop.json`, `test-conductor-loop-mutation.json` (→ committed `ngv2/conductor_loop.py`, divergent return contract)
- Re-verify each target against `git cat-file -e HEAD:<rel>` in NGv2 before moving (the queue shifts; the parallel agent already created `_superseded_*` dirs).
- **Do NOT** quarantine the genuinely-missing-module tasks (`hunt-worker-*`, `exploit-poc-worker*`, `build-stageworker-base`, `conductor-seams-assembler`) — those are real work, handled in Phase 4.

### Phase 2 — Planner cross-brief/committed-module dedup guard (PRIMARY FIX, in-factory `harness_self_fix`)
**Goal:** the planner must never emit an impl task whose `files_touched` targets a module already committed in the target tree (or owned by another in-flight brief). This is the root cause of every clobber.
- **Where:** add the check in `harness/planner/plan_normalizer.py` at/after `normalize_plan` (where `repo_root` is available — `cli.py:357`), or as a new `plan_validator` rule. For each impl task, for each rel path in `files_touched`, if `git cat-file -e HEAD:<rel>` succeeds in the resolved target root (self or external), **DROP the impl task and its paired oracle** with telemetry `duplicate_module_skipped` (do not re-implement). Optionally also dedup against a cross-brief "already-claimed modules" set.
- **RED oracle:** `tests/planner/test_committed_module_dedup.py` — a plan whose impl `files_touched` names an already-committed external module is normalized to drop that task; a genuinely-new module is kept. **Reconcile with `_dedupe_oracles` existing tests** (anti-seesaw — run the union).
- **Decision file:** `state/control/decisions/<dedup-task-id>.json`.
- **Caveat to honor:** legitimate fix-forward edits to an existing module must still be allowed — gate the drop on "module exists AND this is a NEW-module/whole-file impl from a *different* brief", not on every touch of an existing file. Encode that distinction in the oracle.

### Phase 3 — Dep-gate wedge (two parts)
**3a — Immediate unwedge (brief edit, hand-authorable):** fix `brief_hooks_conductor-runtime.md` frontmatter `dependencies:` — `fsm_and_task_primitives` → `fsm-and-task-primitives`; resolve `agent_workers` (rename to the real brief slug, or remove if the dep is spurious). This frees the 4 wedged `conductor-runtime` tasks.
**3b — Durable brief-level deadlock-breaker (in-factory `harness_self_fix` on `autowork_daemon.py`):**
- Add a brief-level analogue of A3: when a brief-frontmatter dep is **terminally un-resolvable** (no brief under any spelling, OR all its tasks `.exhausted`), surface via telemetry (`brief_dep_unresolvable`) and either terminally-block the dependent or release-with-warning — do **NOT** silently hold forever. Keep A.1's transient HOLD (absent-because-not-yet-planned / queued / in_flight / blocked-but-retryable still HOLD).
- Consider a robustness sub-fix: tolerant slug matching (normalize hyphen/underscore) so a typo degrades to a warning, not a wedge.
- **RED oracle:** new cases asserting terminal/un-plannable dep → escape (not infinite hold), added WITHOUT breaking `test_dep_gate_no_premature_release.py` (the absent/blocked/zombie *transient* HOLDs must stay green). **Verify the union of both dep-gate oracle files.**
- **Decision file** required (touches `harness/`).

### Phase 4 — NGv2 worker-epic rework (in-factory, external root = NobleGreedv2)
Re-brief the worker epic to produce **functional** workers (the current ones are scaffolding):
1. **Entrypoints:** add a `__main__`/argparse entrypoint so `python -m ngv2.workers.<phase> --session-id --repo --target --out` actually calls `run_stage(...)` and writes the `--out` artifact JSON. Prefer a **shared `ngv2/workers/__main__.py`** (or `ngv2/workers/_runner.py`) that dispatches by phase, so all 7 phases share one CLI contract — matches `stage_command_map`'s argv exactly.
2. **Missing workers:** build `ngv2/workers/hunt.py` and `ngv2/workers/poc.py` (the 2 phantom phases).
3. **Real behavioral oracles** (not import-smoke) for every worker: assert `run_stage(context, seams)` returns the expected artifact dicts under mocked seams, AND that the CLI entrypoint writes the `--out` file. These replace the exhausted import-smoke oracles.
4. **Live spawner wiring:** bind `seams['spawn']` in `hunt_conductor.run_conductor_step` to a real subprocess spawner; wire `conductor_loop` → `hunt_conductor`; add a top-level NGv2 entrypoint that runs the loop. Closes the orphan gap (this is the real "IMPLEMENTATION ≠ WIRED" closure for NGv2).
5. Each new module: single-file whole-file; commit RED oracle first; external-root build recipe.

### Phase 5 — `report.py` uncaught clobber (FLAG FOR OWNER — do not auto-decide)
- Decide which `run_stage` contract is canonical: `8c5198c` (filename `{phase}.json`) vs `67dc8d0` (`submission.report.json`). **Note both are currently orphaned from the harvester** — `parse_stage_artifact` accepts only `*_report.json` / `detonation_report.json`, so likely **neither** is right; align the filename with the harvester.
- **Commit a `test_report.py` oracle** so this module can never be silently clobbered again (the root reason it slipped through).

### Phase 6 — Restart, resume, verify
- Land Phases 2 & 3b (harness fixes) → **restart the daemon** (kill child, supervisor respawns with new code).
- Remove `state/control/autowork/pause` to resume dispatch.
- Confirm: the 4 `conductor-runtime` tasks now dispatch (3a); no impl task targeting a committed module gets dispatched (Phase 2 telemetry `duplicate_module_skipped`); NGv2 workers build with real oracles + runnable entrypoints (Phase 4).
- Run the full suites read-only as a gate: JanusMask `tests/` (note: webui/config oracles + `tests/harness/test_*dep_gate*`), NGv2 `ngv2/tests/` + `tests/ngv2/` (note: 34 `test_z3_solver_adapter_wired.py` failures are **environmental** — `z3` not installed; brittle no-skip oracle, pre-dates this work, NOT a regression).

---

## 3. 4× PARALLELISM STRATEGY (in and out of factory)

### Out of factory (executor side — 4 parallel sub-agents)
Fan out **4 agents per stage**, single message, distinct non-overlapping mandates:
- **Authoring stage:** Agent A → Phase 2 planner-dedup RED oracle + brief + decision; Agent B → Phase 3 dep-gate breaker oracle (union of both files) + brief + decision + the 3a brief slug edit; Agent C → Phase 4 NGv2 worker entrypoint + `hunt.py`/`poc.py` oracles + briefs; Agent D → Phase 4 conductor/spawner wiring oracle + brief + `report.py` oracle. (Oracle/brief authoring is hand-work → genuinely parallel, no lock contention.)
- **Verification stage:** after each fix lands, 4 adversarial agents re-verify (reuse the pattern from this session — try to refute, trace blast radius). The 4 continuable agent IDs above can be resumed via SendMessage.
- **Manual-drive stage:** if the daemon stalls on a leaf, drive up to **4 concurrent** `orchestrator_worker --task-id` runs — BUT see the external-root constraint below.

### In factory (daemon/pipeline side)
- Daemon concurrency cap = `min(16, cores−2)`; dep-independent leaves dispatch concurrently. **Author briefs so leaves are dependency-independent** (e.g., the 7 worker entrypoints + hunt/poc are mutually independent → up to 4-wide).
- **Different roots parallelize; same root serializes (T1 isolation).** JanusMask-harness fixes (Phases 2, 3b — JM root) run **in parallel with** NGv2 worker builds (Phase 4 — NGv2 root). Within NGv2, leaves touching the same external root **serialize at the external-root lock** (memory: `concurrency-isolation-and-ngv2-solver-ast-epic`, "T1 external-root serialization live"). So the realistic 4× split is: **2 JM-harness lanes ∥ NGv2 lane ∥ out-of-factory authoring/verify lane**, not 4 simultaneous NGv2 commits.
- Pre-author and commit **all** RED oracles up front (parallel, out-of-factory) so the in-factory build phase is a continuous dependency-ordered drain rather than stop-start.

### Recommended wave structure
1. **Wave 0 (parallel, out-of-factory):** quarantine queued clobbers (Phase 1) + author all oracles/briefs/decisions (4 agents) + 3a slug edit.
2. **Wave 1 (parallel, in-factory):** Phase 2 (planner dedup, JM root) ∥ Phase 4 worker entrypoints + hunt/poc (NGv2 root). Restart daemon after Phase 2 lands.
3. **Wave 2 (parallel, in-factory):** Phase 3b (dep-gate breaker, JM root) ∥ Phase 4 conductor/spawner wiring + report.py oracle (NGv2 root). Restart daemon after 3b lands.
4. **Wave 3 (parallel, out-of-factory):** 4-agent adversarial re-verification of every landed fix; then Phase 6 resume.

---

## 4. KEY FILE / COMMIT REFERENCE

**JanusMask harness (production — pipeline-only edits):**
- `harness/autowork_daemon.py` — `_brief_dep_gate_ok` (1637-1715), `_block_dependency_failed_tasks` A3 (973-1040), `_retry_blocked_tasks` (883), iteration calls (1376, 1385), pause/full_stop (288-299), pause loop (2288-2310).
- `harness/planner/plan_normalizer.py` — `_sanitize_impl_verification_commands` (231, the `436df86` vcmd-upgrade), `_strip_unresolvable_dependencies` (614), oracle dedup (755-756), `normalize_plan` (759).
- `harness/planner/cli.py` — brief load (305), `blind_drafts` (319), `normalize_plan` call w/ repo_root (357).
- `harness/planner/staging.py` — impl_progress read (125-140).
- `harness/wire_up.py` — `check_wired` (317-380), `discover_live_roots` (51), external no-op (378-379), `LIVE_ROOTS` (38), `_grep_config` (286). *Known gap: wire-up gate is a no-op for external/rootless targets and can't see `python -m` spawn wiring — relevant to Phase 4 verification, not auto-caught.*
- `harness/orchestrator.py` — `_run_wire_up_gate` (2050-2100), harness_self_fix gate (2880, 2240), decision read (2299-2306), codex branch (459).
- `harness/brief_status.py` — `compute_brief_status` (19, 23).
- `harness/config.yaml` — `wire_up_gate: true`; **uncommitted** `selfheal_auto_promote: true`.

**Oracles (hand-authorable):** `tests/harness/test_dep_gate_no_premature_release.py`, `tests/harness/test_brief_level_dep_gate.py` (dep-gate UNION); `tests/planner/test_strip_unresolvable_deps_wired.py`; new `tests/planner/test_committed_module_dedup.py` (Phase 2).

**Briefs:** `brief_hooks_conductor-glue.md` (clobber source), `brief_hooks_conductor-runtime.md` (slug typo — Phase 3a), `brief_hooks_*workers*.md` / `brief_hooks_stage-workers.md` / `brief_hooks_*-phase-workers.md` (Phase 4), `brief_hooks_fsm-and-task-primitives.md` (the real completed dep).

**State / control:** `state/tasks/` (queue), `state/tasks/blocked/*.exhausted` (dead), `state/tasks/_superseded_*` (parallel-agent prunes), `state/control/decisions/` (decision files), `state/control/autowork/pause` / `full_stop` / `autowork.pid` / `external_roots.allow` / `auto_promote.allowlist`, `state/impl_progress.jsonl` (telemetry), `state/control/autowork/self_healing_history.jsonl`, `scripts/run-autowork.sh` (supervisor).

**NobleGreedv2:** `ngv2/workers/{triage,verify,detonate,report,novelty}.py` (+ missing `hunt.py`,`poc.py`), `ngv2/conductor_loop.py`, `ngv2/hunt_conductor.py`, `ngv2/stage_command_map.py`, `ngv2/gated_advance.py`, `ngv2/session_get_task.py`; tests in `ngv2/tests/` and `tests/ngv2/`.

**Commits:** JM — `3715f3f` (dep-gate flip), `4737f6f` (inverted oracle), `436df86` (vcmd-upgrade), `d29f60c` (brief dep gate), `acc7edb`/`e7b4939` (no-op saga), `1e41ecb` (codex). NGv2 — `adef389`/`4beb88b` (reverts), `e35d27a`/`e81f2c8` (reverted clobbers), **`67dc8d0`** (uncaught report.py clobber) vs `8c5198c` (original report.py), `06b46b9`/`6b57c38`/`26eb441`/`5b58fad` (workers), `53f967e` (conductor_loop).

---

## 5. DONE CRITERIA
- [ ] Queued clobber tasks quarantined; resume cannot re-clobber a committed module.
- [ ] Planner dedup guard live + green oracle; a plan targeting an already-committed module drops that impl with `duplicate_module_skipped` telemetry (verified by a fresh adversarial agent).
- [ ] 4 `conductor-runtime` tasks dispatch (slug fix); brief-level dep breaker live + green union oracle; no infinite-hold on terminal/un-plannable deps.
- [ ] NGv2 workers runnable as spawned (all 7 phases write `--out`), hunt/poc exist, real behavioral oracles green, conductor→spawner→worker chain wired to a live entrypoint.
- [ ] `report.py` canonical contract chosen by owner + `test_report.py` oracle committed.
- [ ] Daemon restarted on fixed code; pause removed; full suites green (modulo the known environmental z3 skips).
- [ ] `selfheal_auto_promote` flag decision made & committed/reverted.

## 6. OPEN OWNER DECISIONS
1. `report.py` canonical contract (`8c5198c` vs `67dc8d0` vs harvester-aligned).
2. `selfheal_auto_promote: true` — keep (commit) or revert.
3. Confirm the parallel agent is stopped/coordinated before queue surgery + resume.
4. Whether the brief-level dep-breaker should *terminally-block* dependents of dead deps or *release-with-warning* (Phase 3b design choice).

---

## 7. UNFINISHED WORK & MAJOR IN-PROGRESS FEATURES (broader roadmap context)

**This plan will almost certainly NOT complete in one session** (Phase 4 alone — functional NGv2 workers + hunt/poc + real oracles + a live spawner chain, all on one external root that serializes under T1 — is multi-session). More importantly, this plan is a *reliability slice* of a much larger, partly-blocked effort. The next operator should not mistake "this plan done" for "the system done."

> Items marked **[memory]** are drawn from the session memory index and may be stale — **re-confirm against the live tree/git before relying on them** (a named file/flag may have moved or changed).

### 7a. Directly downstream of this plan (in progress, multi-session)
- **NGv2 bug-hunt conductor pipeline is not live end-to-end.** Even after Phase 4, the full chain `conductor_loop → hunt_conductor → seams['spawn'] → ngv2.workers.<phase> → artifact_harvester → verdict/authenticity gates → submission FSM` must be wired to a real entrypoint and proven on a real target. Phase 4 closes the worker/spawner gap; it does **not** by itself deliver a live hunt. Expect several follow-on waves.
- **The worker epic's remaining leaves** (`build-stageworker-base`, `conductor-seams-assembler`, late-phase workers) still need genuine oracles, not the exhausted import-smoke ones. The exhausted oracles (`exploit-detonate-worker-oracle`, `novelty-worker-oracle`, `report-worker-oracle`, `verify-worker-*`) must be re-briefed, not merely un-`.exhausted`-ed.

### 7b. Known STRUCTURAL factory gaps NOT fixed by this plan (need their own epics)
- **Wire-up gate is a no-op for external/clean-room targets** and is blind to `python -m` subprocess-spawn wiring (`harness/wire_up.py:378-379` `external_reconciled` returns `wired=True`; `_grep_config` only scans `config/**`, and the import-graph BFS never sees spawn strings in source). This is *why* the orphaned NGv2 workers passed acceptance. Phase 4 fixes the *symptom* (makes these specific workers real); it does **not** fix the gate, so the **next** external orphan will pass again. Needs: teach `discover_live_roots`/`check_wired` to treat `-m <dotted>` / dotted-string spawn references in source as dynamic-wiring roots, and drop the unconditional external no-op when reconciled roots exist.
- **Vacuous import-smoke verification can still land untested modules.** `436df86` only upgrades `python -c "import X"` → a real pytest gate when a paired committed `tests/**/test_<leaf>.py` exists **and** its filename matches the leaf slug. **[memory] A.2 residual gap:** the upgrade silently misses when oracle filename ≠ leaf slug → impl lands vacuously. Phase 2 (committed-module dedup) and Phase 4 (real oracles) reduce but do not close this; a general "new-module impl must gate on a real paired oracle" enforcement is still owed.
- **Cross-brief module-ownership ledger.** Phase 2 checks "already *committed*" modules. It does **not** prevent two *in-flight* briefs from both claiming an *uncommitted* module (a race-window clobber). A fuller fix is a global claimed-modules ledger spanning all active plans.
- **Brief slug-naming fragility.** The `conductor-runtime` wedge was a hyphen/underscore typo. There are likely **other** latent slug typos in `brief_hooks_*.md` frontmatter `dependencies:`. Worth a one-time sweep + the tolerant-matching robustness fix (Phase 3b) so typos warn instead of wedge.

### 7c. Major features IN PROGRESS / BLOCKED (the actual mission, mostly owner-gated)
- **Real claimable bounty machinery — THE core blocker. [memory]** The financial-viability gap: there is **no attacker-reachable sink among regex-detectable findings** in the eligible repos. Open owner decision: build an **inter-procedural taint engine** vs. **source a richer finding corpus**. Status: ~17 parked jail-confirmed PoCs but only ~6 claimable (per the authoritative `data/ngv2/huntr_eligible_cache.json`), and **NOTHING submitted** — submission is owner-gated per target. This is upstream of everything in Phases 1–6; the worker pipeline is plumbing toward this, not the deliverable.
- **Live bounty sourcing + corpus-learning layer. [memory]** huntr RSC-flight scrape + OSV/GHSA APIs to replace frozen data and break CWE-78 tunnel-vision. In-progress; verify what actually landed.
- **NGv2 autonomous bounty FSM (source→submission). [memory]** Reported FULL_LIFECYCLE_CONFIRMED earlier, but the *live worker-driven hunt loop* is exactly the non-functional scaffolding Phase 4 targets — so the autonomous lifecycle is not actually runnable yet.

### 7d. Built but OWNER-GATED / inert (complete code, not live — do not "finish", just know the gate)
- **Drive-backup-on-push epic — complete (37/37), owner-gated on rclone OAuth for e2e. [memory]** Code in `tools/drive_backup/*`; inert until OAuth. (Also: it is *unwired* on the live path, consistent with the wire-up-gate external no-op above.)
- **WebUI typed-config + model-backends — complete; pending owner hand-edits. [memory]**
- **Autocompiler (evolutionary population compiler) — default-on, all phases built. [memory]** Gate `config/autocompiler.yaml`.
- **Overseer chat agent (13-mode webui) — built, P6 PreToolUse hook live. [memory]**

### 7e. Minor loose ends
- **34 `test_z3_solver_adapter_wired.py` failures are environmental** (z3 not installed; brittle oracle hard-asserts presence instead of skipping). Pre-dates this work. Low-priority: soften to `skipif z3 unavailable`.
- `report.py` canonical contract + `test_report.py` oracle (Phase 5 / §6.1).
- `selfheal_auto_promote: true` uncommitted flag (§6.2).
- The 2 reverted clobbers left `plan_hooks_conductor-glue.json` edited [memory: "Duplicate session-get-task tasks removed"] — verify no stale duplicate leaves remain in any `plan_hooks_*.json`.
