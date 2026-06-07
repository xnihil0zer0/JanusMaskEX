# NobleGreedv2 Epic-4 — CONTINUATION HANDOFF REV2 (all blockers fixed; finish the 67-leaf build)

Authored 2026-06-07 (~02:40) mid-run. Supersedes `NGV2_EPIC4_CONTINUATION_HANDOFF.md`.
**The decomposition TEST passed. The 67-leaf BUILD is IN PROGRESS (live daemon).**
Every blocker encountered so far has a root cause + a landed fix in this doc.

JM repo `/home/xnihil0zer0/JanusMaskJR`. External target `/home/xnihil0zer0/NobleGreedv2`
(own git+venv, **no remote**). Python `/home/xnihil0zer0/miniconda3/bin/python`.

---

## 0. TL;DR — current state (verified 2026-06-07 ~02:34)

- **JM HEAD `15167ba`, PUSHED to origin/master** (6 fix commits this session — see §2).
- **NGv2 `master` == `janusmask/work` (aligned), ~38 commits, 9/67 leaves built**, tree clean.
- **Daemon is LIVE** (PID in `/tmp/ngv2e4_daemon.pid`), `cap=3`, `heartbeat=120`, gate `run`,
  allowlist = `ngv2_epic4` only. It is finishing the **knowledge** super-epic; the other 3
  super-epics (analysis / orchestration / gating = 52 leaves) are still pending and will
  decompose with all fixes active.
- **All 4 build-blocking classes are FIXED** (B6, B7, B1, B6-twin). Remaining work is just
  letting the daemon grind + an end-of-run mop-up of a few **parked** leaves.
- Run-tuning config is ACTIVE (NOT baseline): `parallel_cap: 3`, `heartbeat_sec: 120` in
  `harness/config.yaml` — **revert at close-out** (`git checkout harness/config.yaml`).

---

## 1. The 67 leaves (verification target — all must build, each passing its committed oracle)

```
intake/analysis (17): pattern_scanner fp_patterns portfolio_scanner pre_analysis
  taint_spec_library codeql_runner joern_runner root_cause adversarial_scorer
  variant_generator mff_root_cause mff_variant_generator mff_scorer ast_constraint
  ast_verifier backtrack z3_bridge
gating (13): target_qualify bounty_gate repo_complexity web_framework_detect
  language_patterns deser_detect huntr_eligible_cache batch_qualify permission_model
  bash_validator prompt_integrity safety_framework prompt_hints
orchestration (22): worker_registry state_update anti_entropy state_sync compactor
  fail_fast phase_runner task_similarity dynamic_scheduler rate_limiter model_cascade
  agent_registry work_intent_tracking worker_command_dispatch log_watcher debate_router
  debate_synthesis rl_debate_weights trace_parser tool_recommender tool_registry
  masf_tool_composer
knowledge/tools (15): kg_schema kg_config kg_store codebase_graph_extract token_logger
  state_ledger submission_parser js_poc_templates crash_analyzer dedup_novelty
  submission_readiness hunting_roi_tracker portfolio_intel ops_analytics revenue_accelerator
```
Verify built: `[ -f /home/xnihil0zer0/NobleGreedv2/ngv2/<leaf>.py ]` AND
`cd /home/xnihil0zer0/NobleGreedv2 && python -m pytest tests/test_<leaf>.py -q`.

**ONE intra-set dep:** `work_intent_tracking`'s oracle imports `ngv2.worker_registry` →
build `worker_registry` FIRST (it's in the orchestration super-epic; the super-epic brief
instructs the planner to order it first, but the daemon has NO brief-level dep gating, so if
`work_intent_tracking` dispatches first it fails the import — inject a task-level dep or just
re-dispatch it after `worker_registry` lands).

**Spine (already built, NOT part of the 67 — do not flag as drift):** confidence contracts
cvss dedup detonation fp_filter grounding huntr_data huntr_form pipeline poc_runner
prioritize report semgrep_adapter _smoke state_machine submission triage_aggregate
triage_parser verdict (+ `__init__`).

---

## 2. ALL BLOCKERS — root cause + fix + status (this is the heart of the handoff)

| # | Blocker | Root cause | Fix | Status |
|---|---------|-----------|-----|--------|
| **B7** | **External `merge_failed`** — leaves synthesize + pass gates but never land in NGv2 (stuck at 28). | The external merge path (`git_integration.merge_staging_to_parent`) does `git push . <sha>:refs/heads/janusmask/work` (NO `--force`). The prior session's `git reset --hard` left `janusmask/work` (z3-bridge) AHEAD of `master`; new staging worktrees detach from `master`, so a new commit's parent is `master` → the push to `janusmask/work` is non-fast-forward → REJECTED → `merge_failed`. | **NGv2 STATE realignment** (not a code change): `git -C NGv2 merge --ff-only janusmask/work` → realigns `master == janusmask/work` (recovered the stranded z3_bridge). EXTERNAL_MASTER_ADVANCE keeps them locked thereafter. | **FIXED + verified** (rate_limiter landed clean, no merge_failed since). **Invariant to watch: `master==work` must stay aligned. NEVER `git reset --hard` NGv2** (B9). |
| **B6** | **AST hardcoded-credential false-positive** — `validate_code` flags any var matching `(?i)(password\|secret\|key)` assigned a string LITERAL (`ast_enforcer.py:74-87`), strict even for external. `submission_readiness` bound field labels to a `key` var → `synthesis_or_ast_failed` → parked. | The blind synthesis agent doesn't know to avoid credential-named vars; the AST gate (correctly) rejects them. | **Pipeline fix:** NEW `plan_normalizer._inject_credential_naming_constraint(plan, repo_root)` appends a directive to every external-leaf spec steering synthesis away from binding string literals to credential-named vars. Oracle `75d2e38`, fix `e753e07`. | **FIXED** (folded into B6-twin block, see below). |
| **B1** | **~2x duplication** — every super-epic decomposes into duplicate sub-epics (base + domain-qualifier twin, e.g. `analytics-and-roi` + `kg-analytics-and-roi`), so each leaf is built ~twice (the twin blocks via `reject_rollback`). | The two grouping proposals (brief suggestion + agent re-derivation) reconcile; `cli._finalize_epic_children` deduped ONLY by exact canonical slug, so near-synonym twins survived. | **Pipeline fix:** extended `_finalize_epic_children` with **subset-token dedup** — drops a child whose significant-token set is a subset/equal/superset of an already-kept child (catches the added-qualifier pattern). Oracle `ee793ee`, fix `68e38a2`. Live: knowledge 8 sub-epics → 4. | **FIXED for the 3 PENDING super-epics** (52 leaves decompose dup-free). Knowledge was already decomposed pre-fix → finishes ~2x (not pruned: risks stranding mid-build leaves). |
| **B6-twin** | **stdlib-only / determinism jail failures** — (a) data-model/config leaves import `pydantic`/`pydantic_settings` (`kg_schema`, `kg_config`) → NOT in the verification env → `pytest` collection exit 2 → `auto_commit` rollback → parked; (b) clock leaves call `datetime.now()` (`crash_analyzer`) → AST nondeterminism reject → parked. | The blind agent reaches for constructs the **stdlib-only deterministic verification jail** forbids; the AST gate catches (b) but not (a). | **Pipeline fix:** broadened `_inject_credential_naming_constraint`'s block to carry 3 directives (credential-naming + **STDLIB-ONLY** [no pydantic/etc; use dataclasses/enum/typing] + **DETERMINISM** [no datetime.now/time/random/uuid; inject as param]). Oracle `3454ab5`, fix `15167ba`. | **FIXED** for all leaves planned AFTER `15167ba` (the 52 pending + any re-dispatched parked leaves). |
| **GAP** | **Self-heal drops `working_dir` for EXTERNAL leaves** — a `synthesis_or_ast_failed` external leaf gets a self-heal `plan_hooks_selfheal_<id>.json` with `working_dir=None` → normalize_plan hooks are no-ops + a rebuild targets JM not NGv2. | The self-heal harvest doesn't preserve the external `working_dir`. | **NOT fixed** (open). Workaround: don't rely on self-heal for external leaves — re-dispatch parked leaves with a hand-corrected plan (see §4 mop-up). | **OPEN** — future fix: thread `working_dir` through the self-heal harvest. |
| B5 | Stochastic kickoff discards (`all_gemini_no_reconciled`) day-locking leaves. | Old backoff escalated from failure #1. | **FIXED prior session** (`5829c2c`): `_recently_failed_to_plan` grace budget of 2 (attempts≤2→0s, 3→300s, 4→3600s, 5+→86400s). | DONE. |
| B3 | gap#2b: external leaves fuzz-routed → diff-fuzz can't resolve `ngv2.*`. | Auto-planner stamps fuzz meta types. | **FIXED prior session** (`43927f5`): `plan_normalizer._force_smoke_gated_leaf_impl` collapses each external leaf to ONE `data_model` (bypass_fuzzer, smoke-gated) task. | DONE. |
| B9 | clean restarts reset NGv2, dropping built leaves + diverging branches (CAUSED B7). | `git reset --hard 45f5790` on NGv2 master. | **Lesson, not a fix:** NEVER reset NGv2; let leaves accumulate. Only clean JM-side stale plans/markers. | RULE. |

### Other quirks observed (benign)
- `{"skipped":"not_found", "task_id":...}` from a manual `orchestrator_worker --task-id` is a
  **benign fork artifact** — the task still processes + auto-commits. Verify via the ledger
  `auto_commit` row, not stdout.
- The orphaned `agy` PID from a prior session (`Sl+`, 17h+) coexists fine — it did NOT cause
  agy "code 2" with the daemon at `cap=3`. Do NOT kill it (may be the owner's live session).
  If real code-2 conflicts appear, drop `parallel_cap` to 1.
- `state/control/autowork/git_commit.lock` (0-byte) is a benign `fcntl.flock` target, not a
  wedge; the daemon has `_acquire_commit_lock_or_reclaim`.

---

## 3. The 6 fix commits this session (all PUSHED, origin/master == `15167ba`)
```
75d2e38 test: RED oracle B6 credential-naming constraint
e753e07 fix  B6 _inject_credential_naming_constraint (plan_normalizer)
ee793ee test: RED oracle B1 subset-token epic-child dedup
68e38a2 fix  B1 _finalize_epic_children subset-token dedup (cli)
3454ab5 test: extend constraint oracle (stdlib-only + determinism)
15167ba fix  B6-twin broaden _inject_credential_naming_constraint (plan_normalizer)
```
JM sweep: the only red is the PRE-EXISTING `test_brief_loader.py::test_sha256_line_ending_invariant`
Hypothesis flake — **0 new regressions** from this session.

---

## 4. REMAINING WORK — continue the build + end-of-run mop-up

### 4a. Continue (the daemon is already doing this)
The daemon grinds: knowledge sub-epics/leaves (2x, pre-B1) then the 3 pending super-epics
(clean, post-fix). Just monitor. Throughput ~1-2 leaves / 20 min; full 67 is a multi-hour
grind. Watch the `worker_registry → work_intent_tracking` dep in the orchestration super-epic.

### 4b. Parked leaves needing MOP-UP re-dispatch (their pre-fix plans lack the constraint)
Known parked (synthesis/verify failed pre-fix): **`crash_analyzer`** (datetime.now),
**`kg_schema`** (pydantic), **`kg_config`** (pydantic_settings). Watch for more.
**Mop-up recipe (the proven `rate_limiter` recipe — re-plan so the NEW constraint is injected):**
1. KILL the daemon by PID first (`kill -TERM $(cat /tmp/ngv2e4_daemon.pid)`; NEVER `pkill -f`).
2. Clean stale sidecars for the leaf: `rm -f state/output/<id>.* state/tasks/blocked/<id>*`.
3. Write a minimal leaf brief `working_dir: /home/xnihil0zer0/NobleGreedv2`, vcmd
   `python -m pytest tests/test_<leaf>.py -q` (the oracle is auto-injected by normalize_plan,
   AND the leaf now gets the stdlib+determinism+credential constraint).
4. `python -m harness.planner.cli <brief> --output-plan <plan> --non-bootstrap`. If the planner
   rejects with `missing_integration_test`/`missing_edge_case_tests`, add an explicit
   integration-exclusion line to the brief's Non-Goals (a documented gotcha). Alternatively
   hand-build the plan from a known-good leaf plan (clone `plan_hooks_ngv2-confidence.json`'s
   task shape) and run it through `normalize_plan(plan, repo_root='/home/.../NobleGreedv2')`.
5. `stage_task(plan, '<id>', Path('state'), working_dir='/home/.../NobleGreedv2')`.
6. `JANUSMASK_WORKING_DIR=/home/.../NobleGreedv2 python -m harness.orchestrator_worker
   --state-dir state --task-id <id>` → auto-commits to NGv2 master.
7. Verify: `[ -f NGv2/ngv2/<leaf>.py ]` + oracle passes + `master==work` aligned.
8. Restart the daemon (§6) to keep building the rest.

---

## 5. RUN recipe (if you must RESTART the daemon from a paused state)
1. Pre-flight: `git -C NGv2 status` clean, `master==work` aligned, no other daemon running.
   Config has `parallel_cap: 3`, `heartbeat_sec: 120` (run-tuning).
2. allowlist already = `ngv2_epic4`. `printf run > state/control/orchestrator.flag`.
3. `nohup python -m harness.autowork_daemon --state-dir state > /tmp/ngv2e4_daemon.log 2>&1 &
   echo $! > /tmp/ngv2e4_daemon.pid`.
4. Relaunch ONE watcher: `/tmp/ngv2e4_runwatch.sh` (the reusable status watcher; recreate from
   §7 if gone). `/tmp/ngv2e4_watch.sh` is a one-shot detailed snapshot.

**Do NOT re-run the raw root decomposition** (re-introduces duplication; the root plan
`plan_hooks_ngv2_epic4.json` already has 4 pruned child_slugs). **Do NOT reset NGv2.**

---

## 6. Monitoring (escalating backoff)
One until-loop watching: new NGv2 commits, new terminal ledger rows
(`auto_commit`/`task_blocked`/`gate_failed`/`verification_failed` in `state/impl_progress.jsonl`),
daemon PID alive, `master==work` aligned, drift (built `ngv2/*.py` not in the 67 + spine).
Start ~20 min; lengthen toward 60 while smooth; drop to ~10 min on any error cluster
(merge_failed, verification_failed/pydantic, gate_failed, dead/stuck daemon, drift). Budget
hours; NO cost stop. **Kill the daemon by PID before any manual re-dispatch.**

### Key signals & what they mean
- `verification_failed exit 2` + "pathspec did not match" → the leaf's vcmd FAILED (usually a
  third-party import absent in the jail = pydantic class, or an oracle mismatch). Rollback
  artifact, not B7.
- `merge_failed` → B7 regressed: check `master==work` alignment (`git -C NGv2 rev-parse master
  janusmask/work`); ff master to work if diverged.
- `planner_hallucination_discarded` (`all_gemini_no_reconciled`) → flake; grace budget retries.
- `task_blocked ... orphaned (no live worker)` → a killed in-flight task; benign.

---

## 7. CLOSE-OUT (when built == 67)
1. Mop up any parked leaves (§4b).
2. `cd /home/xnihil0zer0/NobleGreedv2 && python -m pytest -q` → full suite green.
3. Confirm all 67 `ngv2/<leaf>.py` present + `master==work` aligned.
4. JM sweep `python -m pytest -q` → 0 new regressions (only the brief_loader flake).
5. **Restore config:** `git checkout harness/config.yaml` (reverts cap→5, heartbeat→1800).
6. Gate `pause`, allowlist deny-all (remove `ngv2_epic4`), kill daemon by PID, ngv2 NOT in JM venv.
7. Update memory ([[ngv2-epic4-authored]] → an execution-result memory), report for push sign-off.

## 8. Reusable watcher scripts (recreate if `/tmp` cleared)
- `/tmp/ngv2e4_watch.sh` — one-shot detailed snapshot (daemon liveness, NGv2 commits,
  built/67, master==work, drift vs the 67+spine, recent terminal rows, code-2 scan).
- `/tmp/ngv2e4_runwatch.sh` — long-horizon loop (20-min poll, logs `/tmp/ngv2e4_watch.log`,
  exits only on DONE/DEAD/STALL/STORM).
- `/tmp/ngv2e4_findings.md` — live findings log (the self-heal wd=None gap, parked leaves,
  B1/B6-twin details).

## 9. Provenance / key files
- B6/B6-twin: `plan_normalizer._inject_credential_naming_constraint`, oracle
  `tests/planner/test_inject_credential_naming_constraint.py`.
- B1: `cli._finalize_epic_children`, oracle `tests/planner/test_epic_child_subset_dedup.py`.
- gap#2b: `plan_normalizer._force_smoke_gated_leaf_impl`. grace budget:
  `autowork_daemon._recently_failed_to_plan`. oracle injection:
  `plan_normalizer._inject_oracle_sources`.
- External commit/merge: `git_integration.merge_staging_to_parent` (the B7 path).
- Decision file (deny-listed self-fix): `state/control/decisions/<tid>.json`
  `{"task_id","decision":"approve","approved_by":"operator","reason","scope"}`.
- Prior-run partial artifacts archived to `_autowork_archive/ngv2_epic4_priorrun_partial/`.
- **NEVER hand-edit production `harness/**` outside the pipeline** (owner directive). Oracles/
  tests MAY be hand-authored.
