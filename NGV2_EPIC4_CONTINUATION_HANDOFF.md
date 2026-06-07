# NobleGreedv2 Epic-4 — CONTINUATION HANDOFF (fix all blockers, finish the 67-leaf build)

Authored 2026-06-06 (~22:10) after a ~5h session. **The decomposition TEST passed.
The 67-leaf BUILD is unfinished (0 leaves currently in NGv2).** This document is the
authoritative recipe to fix every encountered blocker and drive the build to green.

JM repo `/home/xnihil0zer0/JanusMaskJR`. External target `/home/xnihil0zer0/NobleGreedv2`
(own git+venv, **no remote**). Python `/home/xnihil0zer0/miniconda3/bin/python`.

---

## 0. TL;DR — start here

1. Two harness fixes already landed+pushed (grace-budget backoff, gap#2b smoke-gate hook).
   They are the durable wins; do NOT redo them.
2. **Fix the two OPEN blockers FIRST, before any long run:** (B7) external
   `auto_commit_failed`/`merge_failed` — leaves synthesize + pass gates but never land in
   NGv2; (B6) the AST-security `'key'` false-positive. Both are detailed in §4.
3. Then run the build from the **already-pruned 4-super-epic tree** (committed; do NOT
   re-run the raw decomposition — that re-introduces the duplication, see §3/B1).
4. Raise throughput (`parallel_cap`) — at 1 the full run is ~10h (§4 B8).
5. Goal: all **67** leaf modules built into `ngv2/`, each passing its committed oracle.

---

## 1. STATE at handoff (verified)

- **JM HEAD** = `43927f5` (+ an artifact/handoff commit on top — this doc). **PUSHED to
  origin/master.** Four fix commits: `d9830bf` (TASK-A oracle), `5829c2c` (TASK-A fix),
  `41a82f5` (TASK-B oracle), `43927f5` (TASK-B fix).
- **JM config restored to baseline**: `autowork.parallel_cap: 5`, `heartbeat_sec: 1800`,
  `hierarchical_planning.enabled: true`, `max_planner_depth: 4`. Gate `paused`,
  allowlist deny-all, **no daemon**, ngv2 NOT in JM venv.
- **JM sweep**: 380 passed in the touched suites (planner + autowork); **0 new
  regressions**. The only red is the *pre-existing* `test_brief_loader.py::
  test_sha256_line_ending_invariant` Hypothesis flake (`'0\r\r'`), untouched this session.
- **NGv2** `master` == `45f5790` (the Epic-4 RED-oracle commit; 28 commits), tree clean,
  **0 of 67 leaf modules built** (oracles RED). 67 committed oracles `tests/test_<leaf>.py`.
- Pre-existing uncommitted edits to 4 unrelated `brief_hooks_*.md` (failure_propagation_
  status / planner_depth_and_recursion / planner_normalize_plan / staging_resolve_
  interfaces) were present at session start — leave them alone, not ours.

---

## 2. The decomposition TEST result (PRIMARY GOAL — PASSED)

Fed JM the single root brief `brief_hooks_ngv2_epic4.md` (slug `ngv2_epic4`). Its planner
decomposed root → super-epics → sub-epics → leaves (**depth-4**) with **exact module
names, zero name-drift** at the leaf level. The test is a success. Two *defects* were
found (see B1/B2). So the "can JM decompose one big brief into a correct deep tree"
question is answered YES, modulo the dedup defect.

---

## 3. The 67 leaves (verification target — all must build, each passing its oracle)

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
Verify a leaf built: `[ -f /home/xnihil0zer0/NobleGreedv2/ngv2/<leaf>.py ]` AND
`cd /home/xnihil0zer0/NobleGreedv2 && python -m pytest tests/test_<leaf>.py -q`.

**ONE intra-set dependency:** `work_intent_tracking`'s oracle imports
`ngv2.worker_registry` → build/admit `worker_registry` FIRST, or inject a task-level
`dependencies:['<worker_registry tid>']` into work_intent_tracking's leaf plan. All other
66 leaves are dep-free vs Epic-4 siblings (only the committed spine; one uses
`ngv2.state_machine`).

---

## 4. ALL ENCOUNTERED BLOCKERS — root cause + status + fix

| # | Blocker | Root cause | Status |
|---|---------|-----------|--------|
| B1 | **Decomposition duplication** | At every level JM emits BOTH the brief's suggested grouping AND its own re-derived grouping (e.g. root→8 super-epics = 4 domains ×2; analysis sub-epics: `grounding-static-scanners` + `grounding-and-static-scanners`). The dual-agent reconciler dedups by *exact slug* only, so near-synonym slugs both survive. | **Worked around** by pruning to 4 clean super-epics (§5). Self-dedups at the leaf level (same module → same slug → one build). NOT fixed in code. *Future fix:* semantic (not exact-slug) dedup in `reconciliation`. |
| B2 | **Leaf-name drift on prose briefs** | The suggested-grouping super-epics (`ngv2-e4-*`) describe leaves in prose; their sub-epics lost the exact module names → planner would invent names → no oracle injection → blind build. | **Avoided** by choosing the *descriptive* super-epics, which carry explicit `ngv2/<leaf>.py` names (verified: cover exactly the 67). The pruned tree (§5) uses these. |
| B3 | **gap#2b: external builds fail the fuzzer** | Leaf plans got fuzz-routed meta_task_types (`io_adapter`/`refactor` → diff-fuzz can't resolve external `ngv2.*` imports; `state_machine` → stateful_fuzz diverges). | **FIXED via pipeline (TASK B, `43927f5`).** New `plan_normalizer._force_smoke_gated_leaf_impl` collapses each external leaf plan to ONE `data_model` (bypass_fuzzer + smoke-gated) IMPL task and rewires deps. Strict no-op for repo_root None/PROJECT_ROOT/epic. Verified firing (a leaf plan was retyped to data_model). |
| B4 | **30-min throughput stall** | After a discarded kickoff the daemon iteration counts as idle → sleeps the full `heartbeat_sec: 1800`. | **Root cause addressed by TASK A** (fewer discards). Run-tuning: lower `heartbeat_sec` to ~120–180 for the build (NOT committed; baseline is 1800). |
| B5 | **Stochastic kickoff discards** (`all_gemini_no_reconciled`) | Dual-agent reconciliation flakes; the OLD backoff escalated from failure #1 (300s→1h→1day), so unlucky leaves got day-locked. | **FIXED via pipeline (TASK A, `5829c2c`).** `_recently_failed_to_plan` now has a grace budget of 2: attempts≤2→0s, 3→300s, 4→3600s, 5+→86400s. |
| **B6** | **AST-security false-positive** | `validate_code` flags a variable named `key`/`token`/`secret`/`password` assigned a string literal as "Hardcoded credential" — STRICT even for external targets. `submission_readiness` bound field-label literals to a var named `key` → 5 findings → `synthesis_or_ast_failed`, retry budget 1 exhausted → terminal. Deterministic (re-synth reproduced it). | **OPEN.** See fix options below. The self-heal agent already auto-diagnosed it and wrote a corrected brief to the outbox (rename `key`→neutral). |
| **B7** | **External `auto_commit_failed` / `merge_failed`** | Leaves synthesize and PASS gates (`auto_commit` row, phase=accepted) but the commit into NGv2 master fails: ledger shows `merge_failed` then `non-accept terminal (auto_commit_failed)` → routed to blocked, budget exhausted. **NGv2 never advanced past 28.** Clustered partly around the auth-logout window but `merge_failed` indicates a real external-commit/merge path issue, not just auth. | **OPEN — root-cause this FIRST.** See below. |
| B8 | **Throughput at `parallel_cap:1`** | One kickoff/build at a time; ~85 kickoffs (4 super + ~12–24 sub w/ duplication + 67 leaves) + 67 builds ≈ ~10h. | **Config lever.** Raise `parallel_cap` to 3–4. Watch for agy/gemini "code 2" registry conflicts (Epic-3 used 1 for safety); back off to 1 if they appear. |
| B9 | **Process: clean restarts reset NGv2** | I `git reset --hard 45f5790`'d NGv2 twice for clean re-plans, dropping the one leaf (`z3_bridge`) that had built. | **Lesson:** do NOT reset NGv2 between attempts. Let leaves accumulate; only clean JM-side stale plans/markers. |

### B6 fix options (pick one)
- **(a) Brief/spec constraint (lowest-risk, recommended):** make the leaf synthesis never
  bind string literals to credential-named vars. Cleanest hands-off route mirrors the
  oracle-injection precedent: extend `plan_normalizer` (or the brief-generator) to append
  an implementation_notes constraint for external leaves: *"Never assign a string literal
  to a variable named key/token/secret/password/credential/api_key/auth; use a neutral name
  (field_name, check_id, label) or iterate a collection literal."* Pipe it through
  `planner_tooling` (non-deny, auto-commit), oracle-first.
- **(b) Relax the heuristic for external clean-room targets** in `validate_code`
  (deny-listed `harness/orchestrator.py` path → harness_self_fix + decision file). Higher
  risk (loosens a security gate); only the *credential-name + literal* heuristic, and only
  when `relax_external_for(task)` is true. Keep real-secret detection.
- The self-heal already emitted a corrected `submission_readiness` brief to the outbox;
  promoting it fixes that ONE leaf but not the class — prefer (a).

### B7 root-cause checklist (do FIRST — without this the build can't land anything)
- Reproduce: dispatch ONE simple already-failing leaf and watch
  `state/impl_progress.jsonl` for `merge_failed` → `auto_commit_failed`.
- Inspect the external-commit path in `harness/git_integration.py` (the
  `_commit_accepted_output_*` / external worktree merge into NGv2 master). Suspects:
  (i) NGv2 left in a detached/odd state by the prior `reset --hard`; (ii) a stale
  `git_commit.lock` in NGv2 or JM state; (iii) the worktree-merge step failing to ff NGv2
  `master`; (iv) `JANUSMASK_WORKING_DIR`/extra_paths env not set so the commit targets the
  wrong repo. Check `git -C /home/xnihil0zer0/NobleGreedv2 status`,
  `git -C … worktree list`, and any `*.lock`.
- Confirm it is NOT auth (auth is healthy now — `claude_stream.jsonl` shows clean
  `tool_use`, no 401). The `merge_failed` strongly implies a git-state issue.
- This is the #1 risk to the whole build; fix + verify ONE leaf lands in NGv2 before the
  long run.

---

## 5. The pruned tree (build starts HERE — do NOT re-run raw decomposition)

Committed for continuity (so the next run skips B1's duplication and B2's drift):
- `plan_hooks_ngv2_epic4.json` — root epic plan, **pruned to 4 child_slugs** (the
  descriptive super-epics only).
- The 4 descriptive super-epic briefs (each `epic:true`, `child_epics:true`, explicit
  `ngv2/<leaf>.py` names, working_dir NGv2):
  `brief_hooks_analysis-grounding-adversarial-neurosymbolic.md` (17 leaves),
  `brief_hooks_deterministic-hunt-orchestration.md` (22),
  `brief_hooks_eligibility-qualification-safety-gating.md` (13),
  `brief_hooks_knowledge-persistence-submission-analytics.md` (15). Union = exactly 67.

Because the root plan already exists with 4 child_slugs, the daemon will NOT re-decompose
root — it admits these 4 and decomposes them into sub-epics→leaves (the smoke-gate hook +
grace budget now apply). NOTE: each super-epic will still emit duplicate sub-epics (B1);
that's tolerated (self-dedups at leaves) but wastes kickoffs — optionally prune each
super-epic's plan child_slugs to the unique set as it lands.

If you ever need the prescriptive fallback: `epic4_handauthored_reference/` holds a
known-good 12-sub-epic tree (same 67 leaves, explicit). Copy back to top-level
`brief_hooks_*.md` and allowlist the 12 sub-epic slugs for a depth-3 run.

---

## 6. RUN recipe (after B6+B7 are fixed)

1. **Pre-flight:** NGv2 clean (`git -C /home/xnihil0zer0/NobleGreedv2 status`), no daemon,
   gate paused. Set `autowork.parallel_cap` (3–4 for speed; 1 if agy "code 2" appears) and
   lower `heartbeat_sec` to ~120 in `harness/config.yaml` (run-tuning; revert at close-out).
   Do NOT reset NGv2.
2. **Allowlist ONLY the root:** `printf 'ngv2_epic4\n' >> state/control/autowork/auto_promote.allowlist`
   (transitive BFS admits the 4 super-epics → their sub-epics → leaves as plans land).
3. `printf run > state/control/orchestrator.flag`.
4. **Launch daemon by explicit PID:** `nohup /home/xnihil0zer0/miniconda3/bin/python -m
   harness.autowork_daemon --state-dir state > /tmp/ngv2e4_daemon.log 2>&1 & echo $! >
   /tmp/ngv2e4_daemon.pid`.
5. **Monitor with escalating backoff** (§7). The reusable watcher is `/tmp/ngv2e4_watch.sh`
   (args: cap-minutes, commit-batch); recreate it if gone (it tracks NGv2 commits,
   `gate_failed`, `planner_hallucination_discarded`, daemon liveness, leaves_built/67, and
   drift vs the 67 canonical names).
6. **Close out:** NGv2 suite green (`cd /home/xnihil0zer0/NobleGreedv2 && python -m pytest
   -q`), all 67 modules present, JM sweep 0-new-reg, **restore config** (`git checkout
   harness/config.yaml`), gate paused, allowlist deny-all, kill daemon by PID
   (`kill -TERM $(cat /tmp/ngv2e4_daemon.pid)`; NEVER `pkill -f`), ngv2 not in JM venv,
   update memory, report for push sign-off.

### meta_task_type / gating reminder
The smoke-gate hook now forces external leaves to `data_model`. If you see a leaf still
fuzz-routed, the hook didn't fire — check `repo_root` is the NGv2 path (external) and the
leaf's vcmd points at an existing `tests/test_<leaf>.py` under NGv2.

---

## 7. Monitoring (escalating backoff — optimize context)

One until-loop watching: new NGv2 commits
(`git -C /home/xnihil0zer0/NobleGreedv2 log --oneline master | wc -l`), new terminal ledger
rows (`auto_commit`/`gate_failed`/`task_terminal` in `state/impl_progress.jsonl`), daemon
PID alive, and drift (any built `ngv2/*.py` not in the 67 + spine). Start ~20 min; lengthen
20→30→45→60 (cap 60) while progress advances + no error; on any error signal
(`auto_commit_failed`/`merge_failed` cluster, `gate_failed` cluster, dead/stuck daemon,
leaf-name drift, no commit >2 intervals) drop to ~10 min and investigate. Each wake-up:
ONE compact status line. Budget hours; NO cost stop — watch token spend manually. Prefer
harness-tracked background waits over short fixed polling. **Kill the daemon by PID before
any manual re-dispatch** (a paused-but-alive daemon races a manual worker → benign
"not_found"; verify via ledger `auto_commit`, not stdout).

---

## 8. Provenance / key files
- Fixes: TASK-A `_recently_failed_to_plan` (`harness/autowork_daemon.py`), oracle
  `tests/adversarial/test_escalating_backoff_recently_failed_to_plan.py`. TASK-B
  `_force_smoke_gated_leaf_impl` + wiring in `harness/planner/plan_normalizer.py`, oracle
  `tests/planner/test_force_smoke_gated_leaf_impl.py`.
- Decision-file path for deny-listed self-fixes: `state/control/decisions/<tid>.json`
  `{"task_id","decision":"approve","approved_by":"operator","reason","scope"}`.
- Drive a fix through the pipeline: hand-author RED oracle → commit → write brief
  `brief_hooks_<slug>.md` (with "# Required plan shape") → `python -m harness.planner.cli
  <brief> --output-plan <plan>` → `stage_task` (harness.planner.staging) → (decision file
  if deny-listed) → `python -m harness.orchestrator_worker --state-dir state --task-id
  <tid>` (auto-commits; "not_found" is a benign fork artifact). `planner_tooling`/
  `harness_self_fix` synthesis is single-agent (bypasses reconciliation flakiness).
- NEVER hand-edit production `harness/**` outside the pipeline (owner directive). Oracles/
  tests MAY be hand-authored.
