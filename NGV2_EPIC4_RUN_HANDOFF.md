# NobleGreedv2 — Epic-4 RUN handoff (EXECUTION session)

Authored 2026-06-06 (same session that shipped TASK 1, the gate-failure error-capture fix).
**Epic-4 is AUTHORED, not executed.** This file is the run recipe for the EXECUTION session.

## What Epic-4 is

The **maximal, FOUR-LEVEL** epic that rebuilds **every remaining JM-gatable capability** of
legacy NobleGreed into the external NobleGreedv2 repo. Discovered by a 67-agent parallel
research pass (7 cluster mappers + completeness critic) over `/mnt/ai-data/NobleGreed-legacy`
(services/ = 53 .py + orchestrator/ + knowledge/) deduped against the 20-module ngv2 spine.

- **Tree (depth-4):** root `ngv2_epic4` → **4 super-epics** → **12 sub-epics** → **67 leaves**.
  Leaf lineage depth = 3 ≤ `max_planner_depth:4` (verified; deeper than Epic-3's depth-3).
- **67 leaf modules**, each a NEW single-file stdlib-only (or injected-seam) `ngv2/*.py`,
  IMPL-only, pinned by a **committed clean-room oracle** at `tests/test_<leaf>.py`.
- **The live-I/O boundary is deferred** (NOT in Epic-4): real exploit firing, real LLM/model
  calls, GPU/RLCF/GraphMERT training, live huntr.com HTTP/Playwright, live MCP servers. Every
  non-determinism that CAN be injected (subprocess runner, SMT solver, HTTP transport, clock,
  model client) is an **injected seam** tested with a mock/scripted callable (poc_runner pattern).

### The tree
- **A `ngv2-e4-analysis`** (17 leaves): A1 `ngv2-e4-grounding-pkg` (7: pattern_scanner, fp_patterns,
  portfolio_scanner, pre_analysis, taint_spec_library, codeql_runner, joern_runner) · A2
  `ngv2-e4-adversarial-pkg` (6: root_cause, adversarial_scorer, variant_generator, mff_root_cause,
  mff_variant_generator, mff_scorer) · A3 `ngv2-e4-neurosymbolic-pkg` (4: ast_constraint,
  ast_verifier, backtrack, z3_bridge).
- **B `ngv2-e4-gating`** (13 leaves): B1 `ngv2-e4-eligibility-pkg` (8: target_qualify, bounty_gate,
  repo_complexity, web_framework_detect, language_patterns, deser_detect, huntr_eligible_cache,
  batch_qualify) · B2 `ngv2-e4-safety-pkg` (5: permission_model, bash_validator, prompt_integrity,
  safety_framework, prompt_hints).
- **C `ngv2-e4-orchestration`** (22 leaves): C1 `ngv2-e4-state-pkg` (8: worker_registry, state_update,
  anti_entropy, state_sync, compactor, fail_fast, phase_runner, task_similarity) · C2
  `ngv2-e4-scheduling-pkg` (3: dynamic_scheduler, rate_limiter, model_cascade) · C3
  `ngv2-e4-workers-pkg` (4: agent_registry, work_intent_tracking, worker_command_dispatch,
  log_watcher) · C4 `ngv2-e4-debate-pkg` (7: debate_router, debate_synthesis, rl_debate_weights,
  trace_parser, tool_recommender, tool_registry, masf_tool_composer).
- **D `ngv2-e4-knowledge-tools`** (15 leaves): D1 `ngv2-e4-knowledge-pkg` (6: kg_schema, kg_config,
  kg_store, codebase_graph_extract, token_logger, state_ledger) · D2 `ngv2-e4-submission-tools-pkg`
  (5: submission_parser, js_poc_templates, crash_analyzer, dedup_novelty, submission_readiness) ·
  D3 `ngv2-e4-analytics-pkg` (4: hunting_roi_tracker, portfolio_intel, ops_analytics,
  revenue_accelerator).

## STATE at handoff (verified)

- **JM** `master`: TASK-1 shipped — RED oracle `2fdc68f`, pipeline fix `4b8ec8c`
  (`orchestrator_worker._emit_gate_failure` + 3 wirings; gate failures now log the actual
  error/traceback as a `gate_failed` ledger row). Full sweep **7031 passed, 1 failed** (the
  failure is the PRE-EXISTING `test_brief_loader.py::test_sha256_line_ending_invariant`
  Hypothesis bug — 0 new regressions). Epic-4 brief artifacts committed (see below).
  Gate `paused`, allowlist deny-all, `parallel_cap:5`, `hierarchical_planning.enabled:true`,
  `max_planner_depth:4`, no daemon, ngv2 NOT in JM venv.
- **NGv2** `master`==`janusmask/work`: **67 Epic-4 oracles committed `45f5790`** (87 tracked
  oracle files = 20 spine + 67). Tree clean, no git remote. The 67 ngv2 leaf modules do NOT
  exist yet (oracles are RED).
- **Epic-4 briefs** (JM repo): `brief_hooks_ngv2_epic4.md` (root) + 4 super-epic +
  12 sub-epic briefs (`brief_hooks_ngv2-e4-*.md`). All 17 load cleanly via `load_brief`; slugs
  resolve; each sub-epic brief carries the EXACT per-leaf exported symbols + contract.

## RUN RECIPE (execution session)

Same proven loop as Epic-3 (fully hands-off now, with oracle-injection `e399c33` feeding each
committed oracle into the blind worker's spec):

1. **Pre-flight:** confirm NGv2 clean (`git -C /home/xnihil0zer0/NobleGreedv2 status`), JM gate
   `paused`, no daemon. The 67 oracles are already committed (`45f5790`).
2. **Allowlist ONLY the root:** `printf 'ngv2_epic4\n' >> state/control/autowork/auto_promote.allowlist`
   (transitive admission BFS-grows root → 4 super → 12 sub → 67 leaves as each epic plan lands).
3. `printf run > state/control/orchestrator.flag`; set `harness/config.yaml` `parallel_cap:1`
   for the run (planner kickoffs overlap a worker; cap 1 avoids gemini code-2).
4. **Launch the daemon by EXPLICIT PID:**
   `nohup /home/xnihil0zer0/miniconda3/bin/python -m harness.autowork_daemon --state-dir state
   > /tmp/ngv2e4_daemon.log 2>&1 & echo $! > /tmp/ngv2e4_daemon.pid`
5. **Monitor** (this is the LONGEST run yet — ~3 levels of plan-kickoffs + 67 builds; budget
   hours, NO cost stop). Builds: `git -C /home/xnihil0zer0/NobleGreedv2 log --oneline master`.
   Kickoffs/blocks/**gate_failed** (now captured by TASK 1!): `tail -f state/impl_progress.jsonl`.
   Use a Monitor re-armed hourly + event-driven, NOT 15-min polls.
6. **Close out:** NGv2 suite green (`python -m pytest -q` in NGv2 venv → expect 87+ files green),
   JM sweep 0-new-reg, gate `paused`, allowlist deny-all, `parallel_cap` back to 5, kill daemon
   by PID (`kill -TERM $(cat /tmp/ngv2e4_daemon.pid)` — NEVER `pkill -f`), ngv2 not in JM venv,
   push with owner sign-off, update memory.

## CRITICAL run notes (carry forward)

1. **ONE intra-epic dependency:** `work_intent_tracking` imports `worker_registry` (both in C3
   `ngv2-e4-workers-pkg`; its oracle `from ngv2.worker_registry import WorkerRegistry`). BUG#3
   (no brief-level dep gating) is still OPEN, so EITHER build `worker_registry` first and inject
   a task-level `dependencies:['<worker_registry task_id>']` into the work_intent_tracking child
   plan, OR dispatch worker_registry, let it accept (ff-advances master), then dispatch the rest.
   **Every other leaf is dep-free w.r.t. Epic-4 siblings** (only the committed spine is imported;
   one leaf uses `ngv2.state_machine`). Verified by scanning all 67 oracle imports.
2. **meta_task_type / gap#2b:** the diff-fuzzer still can't resolve external `ngv2.*` imports, so
   leaves MUST be smoke-gated or stateful_fuzz (NOT io_adapter/algorithm). The leaf planner
   assigns meta_task_type during decomposition; the sub-epic briefs request, per leaf:
   `data_model`/`orchestration` (bypass_fuzzer, smoke-gated) for pure/seam leaves and
   `stateful_fuzz` for state-bearing leaves (worker_registry, model_cascade, kg_store,
   token_logger, state_ledger, hunting_roi_tracker, anti_entropy, backtrack, safety_framework,
   agent_registry, work_intent_tracking, worker_command_dispatch, log_watcher, rl_debate_weights).
   If a leaf plan comes back with a fuzz meta-type, OVERRIDE it before dispatch (Epic-2 lesson).
3. **Oracle-injection is live** (`e399c33`): each committed oracle's source is embedded into the
   leaf spec, so even precise/seam leaves build from the contract. Briefs carry precise prose for
   the DECOMPOSITION; the oracle covers the BUILD.
4. **smoke_failed is a re-synthesis flake** (budget 3); with TASK 1 you will now SEE the actual
   import error in the `gate_failed` ledger rows — use it to tell genuine bugs from flakes.
5. **Kill the daemon before any manual re-dispatch** (a paused-but-alive daemon races a manual
   worker → "not_found"). "not_found" from a manual worker is a benign fork artifact; verify via
   ledger `auto_commit`, not stdout.
6. **Depth-4 is at-but-under the limit** (leaf ancestor-depth 3 ≤ max 4). If the planner ever
   refuses on depth, FALLBACK = allowlist the 12 sub-epic slugs directly (skip the super-epic
   level) → a depth-3 run, same 67 leaves.
7. **Expected build count: 67.** Watch token spend manually (budgets are depth guardrails, not
   cost-aware; a wide epic burns unbounded tokens).

## How Epic-4 was authored (provenance)
- Research: workflow `ngv2-epic4-research` (8 agents, ~627k tok) → 84 capabilities mapped + 13
  missed cataloged → ~67 rebuildable deduped.
- Oracles: workflow `ngv2-epic4-oracles` (67 agents, ~2.8M tok) — one clean-room stdlib oracle
  per leaf, each reading the legacy source + ngv2 conventions. All 67 validated (parse,
  stdlib-only, import target, ≥1 test) and committed `45f5790`.
