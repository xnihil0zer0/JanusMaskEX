# Adversarial Test Plans — 24h Change Audit (generated 2026-05-29)

Four exploration agents each mapped a distinct functional area of JanusMaskJR
with codebase-memory-mcp and wrote an adversarial test plan targeting **the
changes made in the last 24 hours** and **features that look incompletely
implemented**. Each plan is meant to be executed next session by a tester
sub-agent that writes + runs the adversarial tests.

## Coverage split (no overlap; together = all functionality)
- `01_synthesis_pipeline.md` — orchestrator synthesis pipeline, dual-agent agreement, ast_retry, reconciliation/cross-exam, timeout budgets, worker exit codes, prompt construction.
- `02_apply_commit_validation_fuzzing.md` — git_integration commit/AST-merge/rollback + §1b apply-path scoping, ast_enforcer/validate_code, depth_validator, fuzzing engine, BYPASS_* paths, sandbox/embedded_test_runner.
- `03_daemon_control_isolation_hooks.md` — autowork_daemon (self-heal, degenerate-escalation guard, inactivity watchdog, retry/blocked), control_gate (approval/pause), agent isolation (paths.agent_work_dir, cwd relocation), hooks (_env, gemini/pre_tool _SHELL_ALLOW).
- `04_planning_webui_interceptors_state.md` — planner (blind_draft, adversarial_review, reconciliation, plan_validator, cli), webui_control (autobrief, interpolation, _agents_override), interceptors, state.py, impl_outbox_watcher, bootstrap, vendoring/setup-agents.

## 24h change window (commits f1a746b..9e0fc64 and the day's earlier integrations)
HEAD `9e0fc64` AGENT_ISOLATION (apply-path scoping + CWD relocation); `f1a746b`
RB_check_true_depth (depth_validator.py); `1a30972` GUARD_DEGENERATE_ESCALATION;
`8dac6e1` RECONCILE_TIMEOUT_BUDGETS; plus earlier same-day: BYPASS_WHOLE_FILE,
SANDBOX_PATH_FIX, WATCHDOG_TIMEOUT_INCREASE, ORCHESTRATOR_TIMEOUT_FIXES,
SYNTHESIS_TIMEOUT_UPGRADE, AUTOWORK_DAEMON_SAFEGUARDS.

## NEXT-SESSION INSTRUCTIONS (for the parent agent)
1. Spawn 4 tester sub-agents, one per plan. Each writes + RUNS adversarial tests
   (pytest via `.venv/bin/python -m pytest`) per its plan, hunting for
   incompletely-implemented features, unfilled gaps, and planned-but-absent work.
2. **Hard safety rails (carry to every tester):** do NOT run any agy-invoking
   pipeline (no escape hatch, no daemon, no `run_both_agents` with real spawns —
   mock the spawns); keep `state/control/autowork/full_stop` = halted and
   `autowork.enabled` = false; never weaken the dual-agent agreement invariant
   (`synthesis_success = bool(... and ...)`) or the BYPASS_FUZZER_TYPES bypass;
   do NOT add anything to the auto_promote allowlist. After any run that DID
   spawn an agent, `git status` + grep `_is_single_candidate|@(lambda|exec(`.
3. **Known PRE-EXISTING test failures — do NOT re-flag as regressions** (they
   fail on clean HEAD f1a746b, unrelated to recent work): the 5×
   `test_escalate_to_autobrief_*` (test_autowork_self_healing.py /
   test_autowork_escalation.py — broken by the degenerate-escalation guard +
   their mock_open) and 2× `test_orchestrator_timeout_fixes.py::test_*_exits_with_status_2_use_retry_module`.
4. Collate every tester's "Incompleteness & gap candidates" plus your own sweep
   into a single file (e.g. `INCOMPLETE_FEATURES_AND_GAPS.md`): incompletely
   implemented features, gaps not filled, and features planned but not yet built.
   Cross-reference JanusMaskJR_restoration_plan.md (§3.7 backlog, remaining
   briefs 4/6a/6b/6c/7) and AGENT_ISOLATION_fix_plan.md open items (§5 agy
   config probe, §6.3 live no-regression run not yet done). This feeds
   correction of errors and adjustment of the remainder of the rebuild plan.
