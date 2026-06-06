# NobleGreedv2 — Epic-4 RUN handoff (EXECUTION session)

Authored 2026-06-06. **Epic-4 is AUTHORED, not executed.** This session is a DECOMPOSITION
TEST: feed JanusMask **one big root brief** and let its planner **decide the whole multi-level
tree itself** (root → ... → leaf, depth ≤ 4), then build all 67 leaves hands-off.

## The setup (what makes this a decomposition test)

- **ONE input brief:** `brief_hooks_ngv2_epic4.md` (slug `ngv2_epic4`, ~24KB, `epic:true`,
  `child_epics:true`). It describes the mission + the **67 capabilities to rebuild** (the body
  of work) and **hands the decomposition decision to JM** — JM chooses the super-epics,
  sub-epics, depth, and grouping. It offers a non-binding suggested grouping (4 domains) but
  does NOT prescribe the tree. Verified: loads via `load_brief`, `_should_run_epic == True`.
- **The leaf SET is anchored, the HIERARCHY is free.** The 67 leaf MODULE NAMES are fixed
  because each is pinned by a committed oracle (`tests/test_<name>.py` does
  `from ngv2.<name> import …`). JM must reproduce those module names exactly; what JM *decides*
  is how to group them into the epic hierarchy.
- **67 committed oracles** at NGv2 `master 45f5790` (87 tracked oracle files = 20 spine + 67).
  Clean-room, stdlib-only, injected seams (clock/solver/runner/transport) for all
  non-determinism. Oracle-injection (`e399c33`) feeds each into its leaf's build spec.
- **16 hand-authored intermediate briefs** from the first authoring pass are PRESERVED under
  `epic4_handauthored_reference/` (NOT used as input; `_run_epic_pipeline` generates child
  briefs from the parent's prose and would overwrite them anyway). They're a reference for what
  a reasonable decomposition looks like, and a fallback (see §Fallback).

## The 67 leaves (the verification target — must all build, in any tree)

intake/analysis: pattern_scanner, fp_patterns, portfolio_scanner, pre_analysis,
taint_spec_library, codeql_runner, joern_runner, root_cause, adversarial_scorer,
variant_generator, mff_root_cause, mff_variant_generator, mff_scorer, ast_constraint,
ast_verifier, backtrack, z3_bridge · gating: target_qualify, bounty_gate, repo_complexity,
web_framework_detect, language_patterns, deser_detect, huntr_eligible_cache, batch_qualify,
permission_model, bash_validator, prompt_integrity, safety_framework, prompt_hints ·
orchestration: worker_registry, state_update, anti_entropy, state_sync, compactor, fail_fast,
phase_runner, task_similarity, dynamic_scheduler, rate_limiter, model_cascade, agent_registry,
work_intent_tracking, worker_command_dispatch, log_watcher, debate_router, debate_synthesis,
rl_debate_weights, trace_parser, tool_recommender, tool_registry, masf_tool_composer ·
knowledge/tools: kg_schema, kg_config, kg_store, codebase_graph_extract, token_logger,
state_ledger, submission_parser, js_poc_templates, crash_analyzer, dedup_novelty,
submission_readiness, hunting_roi_tracker, portfolio_intel, ops_analytics, revenue_accelerator.

## STATE at handoff (verified)

- **JM** `master` HEAD (this session): TASK-1 shipped — RED oracle `2fdc68f`, fix `4b8ec8c`
  (`orchestrator_worker._emit_gate_failure` logs the smoke/embedded/narrow error as a
  `gate_failed` ledger row). Epic-4 single root brief + run handoff + reference briefs committed.
  Full sweep **7031 passed, 1 failed** (pre-existing `test_brief_loader` Hypothesis bug; 0 new
  regressions). Gate `paused`, allowlist deny-all, `parallel_cap:5`,
  `hierarchical_planning.enabled:true`, `max_planner_depth:4`, no daemon, ngv2 NOT in JM venv.
- **NGv2** `master`==`janusmask/work`==`45f5790`, tree clean, no remote. 67 leaf modules NOT
  built yet (oracles RED).

## RUN RECIPE (execution session)

1. **Pre-flight:** NGv2 clean; JM gate `paused`; no daemon. `parallel_cap:1` for the run.
2. **Allowlist ONLY the root:**
   `printf 'ngv2_epic4\n' >> state/control/autowork/auto_promote.allowlist`
   (transitive admission BFS-grows the admitted set as each epic plan lands — root → whatever
   super/sub-epics JM mints → leaves).
3. `printf run > state/control/orchestrator.flag`.
4. **Launch daemon by EXPLICIT PID:**
   `nohup /home/xnihil0zer0/miniconda3/bin/python -m harness.autowork_daemon --state-dir state
   > /tmp/ngv2e4_daemon.log 2>&1 & echo $! > /tmp/ngv2e4_daemon.pid`
5. **Monitor with escalating backoff** (see §Monitoring). This is the LONGEST run yet: a live
   multi-level decomposition (several plan-kickoffs per level) + 67 builds. Budget hours; no cost
   stop.
6. **Close out:** NGv2 suite green (`python -m pytest -q` in NGv2 venv → 87+ files), all 67 leaf
   modules present, JM sweep 0-new-reg, gate `paused`, allowlist deny-all, `parallel_cap` back to
   5, kill daemon by PID (`kill -TERM $(cat /tmp/ngv2e4_daemon.pid)`; NEVER `pkill -f`), ngv2 not
   in JM venv, push with owner sign-off, update memory.

## THE #1 RISK — decomposition fidelity (this is what's under test)

JM now DECIDES the tree from one brief, so the new failure mode is the decomposition itself, not
the build:
- **Leaf-name drift:** if a generated leaf's module name ≠ its committed oracle name, the leaf's
  vcmd points at a missing `tests/test_<name>.py` → no oracle injection → it builds blind/fails.
  **Mitigation/monitor:** as each sub-epic plan lands, diff its leaf slugs/modules against the
  67 above. The brief instructs exact module names; verify JM honored them.
- **Dropped/duplicated leaves:** the blind-draft decomposition may miss or duplicate
  capabilities. **Monitor:** the final leaf set must be exactly the 67. Track coverage as plans
  land (`grep` the generated `plan_hooks_*.json` for each module / `tests/test_<name>.py`).
- **Depth/grouping:** JM may go shallower/deeper than 4 or group oddly — that's allowed and IS
  the experiment. Only hard limit: lineage depth ≤ `max_planner_depth:4` (leaf ancestor-depth
  ≤ 4; the planner refuses beyond). If JM produces a clean tree with all 67 leaves, the test
  passes regardless of exact shape.
- **Recovery:** if a level's decomposition is bad (drift/missing), you can re-kick that epic, or
  fall back (§Fallback) for that branch.

## Other run notes (carry forward)

1. **ONE known intra-set dependency:** `work_intent_tracking`'s oracle imports
   `ngv2.worker_registry`. Build/admit `worker_registry` first (it ff-advances master), then
   `work_intent_tracking`, OR inject a task-level `dependencies:['<worker_registry tid>']` into
   the latter's child plan (BUG#3: no brief-level dep gating). Every other leaf is dep-free vs
   Epic-4 siblings (only the committed spine is imported; one leaf uses `ngv2.state_machine`).
2. **meta_task_type / gap#2b:** the diff-fuzzer can't resolve external `ngv2.*` imports, so each
   leaf must be smoke-gated (`data_model`/`orchestration`) or `stateful_fuzz` — NOT
   io_adapter/algorithm. The leaf planner assigns meta_task_type; if it picks a fuzz type for a
   leaf, OVERRIDE before dispatch (Epic-2 lesson). State-bearing leaves wanting `stateful_fuzz`:
   worker_registry, model_cascade, kg_store, token_logger, state_ledger, hunting_roi_tracker,
   anti_entropy, backtrack, safety_framework, agent_registry, work_intent_tracking,
   worker_command_dispatch, log_watcher, rl_debate_weights.
3. **TASK-1 benefit:** gate failures now write `gate_failed` rows with the real import traceback
   to `state/impl_progress.jsonl` — use them to tell genuine bugs from re-synthesis flakes
   (`smoke_failed` budget is 3; a flake usually passes on a clean re-stage).
4. **Kill the daemon before any manual re-dispatch** (a paused-but-alive daemon races a manual
   worker → "not_found"). "not_found" from a manual worker is a benign fork artifact; verify via
   ledger `auto_commit`, not stdout.

## Fallback (if free decomposition underperforms)

The preserved `epic4_handauthored_reference/` holds a known-good depth-4 tree (4 super → 12 sub).
If JM's free decomposition keeps drifting, you can copy those back to top-level
`brief_hooks_*.md` and allowlist the root (or the 12 sub-epic slugs for a depth-3 run) — same 67
leaves, prescriptive structure. This abandons the decomposition-decision test but guarantees the
build.

## Monitoring with escalating backoff (optimize context)

The owner wants context optimized: **the longer it runs smoothly, the less often you check.**
Concretely, after launch:
- Use a single Monitor/until-loop that watches three signals: new NGv2 commits
  (`git -C /home/xnihil0zer0/NobleGreedv2 log --oneline master | wc -l`), new ledger terminal
  rows (`auto_commit` / `gate_failed` / `task_terminal` in `state/impl_progress.jsonl`), and the
  daemon PID alive.
- **Backoff schedule:** start at ~20 min between checks; after each check where progress advanced
  AND no error signal, lengthen the interval (20 → 30 → 45 → 60 min, cap ~60). On ANY error
  signal (`gate_failed` cluster, a stuck/dead daemon, leaf-name drift, no new commit for >2
  intervals) drop back to ~10 min and investigate. Don't poll on a fixed short tick.
- Each wake-up: ONE compact status line (commits built / 67, last terminal events, drift check),
  not a full transcript dump. Only dig in when a signal says to.

## Provenance
Research: Workflow `ngv2-epic4-research` (8 agents). Oracles: Workflow `ngv2-epic4-oracles`
(67 agents) → committed `45f5790`. First authoring pass hand-built the tree (corrected: the
operator wanted JM to decompose, so the tree files were demoted to reference and the root brief
was rewritten to delegate the decomposition decision).
