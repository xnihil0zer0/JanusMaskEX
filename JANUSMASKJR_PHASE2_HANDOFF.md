# Phase-2 (Level-2 hierarchical planner) — Resume Handoff (2026-06-05)

## Mission
Build Phase 2 of the hierarchical planner **through the pipeline**, using **epic briefs**, so the
system runs **autonomously for days without human interaction** and **no new switches** the owner must
flip. Claude is the **full delegated operator** (writes all approval decision files). Owner authorized
all approvals. Security posture decision: **auto-approve is gated on the existing `autowork.enabled`
webui toggle** — ON ⇒ fully unattended (any non-deny `harness/**` path); OFF ⇒ strict self-heal floor.
The escape-critical `_NEVER_AUTO_APPROVE` deny-list stays irreducible. **Fix the environment blockers
FIRST, then build the children, then flip the feature flags.**

Full detail is in memory: `phase2-autonomy-security-posture.md` (+ `hierarchical-planner-phase1-exec.md`).

## State at handoff (HEAD `e04bb60`, branch master, pushed through `b12f8fc`)
- **B0 landed** `681394c`: `_auto_approve_sensitive_eligible` (orchestrator.py) branches on `autowork.enabled` — widened when on. Oracle `tests/adversarial/test_autowork_enabled_widens_autoapprove.py`.
- `autowork.enabled: true` (`7ecf429`). Epic decomposed into 5 children (committed `7ecf429`): `symbol_ledger_module`, `staging_resolve_interfaces` (dep: symbol_ledger), `failure_propagation_status`, `planner_depth_and_recursion`, `e2e_acceptance_test` (dep: all). All land OUTSIDE the deny-list. Epic `phase2_hierarchical` allowlisted ⇒ all 5 transitively eligible.
- Blocker-1 partial fix `e04bb60`: removed bogus `-m claude-opus-4.6` from `claude_fallback` agy args.
- **Nothing of Phase-2 has landed.** `symbol_ledger` execution attempt failed (Blockers 2+3). State cleaned. run-gate `paused`; daemon DOWN; 0 pending tasks. `symbol_ledger`'s plan_hooks exists (dup oracle task already removed).
- `hierarchical_planning.symbol_ledger`/`failure_propagation` still `false` (flip in Phase C).

## PHASE A — FIX BLOCKERS FIRST (do these before any planner/daemon run)

**A1 — Claude role needlessly bills Antigravity (highest leverage).** Planner already prefers claude-proper (`run_both_agents`, orchestrator.py:1080-1138), but `poll_for_submission`/`_path_b_outbox_fallback` (orchestrator.py:941-1049 / :880-914, hardcodes `outbox/submission.py`) only recognize the *synthesis* artifact, so claude-proper's `outbox/plan_draft.json`/`reconciliation.json` is reported "died without submitting (code 0)" ⇒ fires `claude_fallback` (agy/Opus-via-Antigravity = Google credits) needlessly.
  - **Fix:** make poll/outbox-fallback detect `plan_draft.json`/`reconciliation.json` when `JANUSMASK_MODE∈{planning,reconciliation}`. orchestrator.py is **DENY-LISTED → operator-land** (oracle-first + `state/control/decisions/<tid>.json` approve, meta_task_type=harness_self_fix). Optional pipeline mitigation: extend `scripts/impl_outbox_watcher.py` (not deny-listed).
  - **Empirical check first:** run ONE planning (`python -m harness.planner.cli <a child brief> --output-plan /tmp/x.json`), then inspect the claude-proper outbox (`JanusMaskJR_agentwork/claude/.../outbox/`) — did it WRITE `plan_draft.json`, or emit prose? If prose, also fix the planning submission path (likely `-p` mode dropping `--settings` hooks — orchestrator.py:181-184 C4 comment). Keep `e04bb60` (last-resort must not crash) but land A1 BEFORE any planner run so the fallback doesn't bill needlessly.

**A2 — `test_authoring` tasks rejected `mutation_gate_missing`.** Gate orchestrator.py:2916-2922 requires meta=test_authoring tasks to carry `mutation_target`/`mutations[]`; no planner emits them.
  - **Fix (pipeline-able, preferred):** planner emits a `mutation_target` (bare dotted module per orchestrator.py:2934-2942 `_valid_mut_module`) for test_authoring tasks — `harness/planner/blind_draft.py` (prompt schema) + `harness/planner/plan_validator.py` (validate). Both NOT deny-listed → run through the pipeline. (Fallback B: relax the gate in orchestrator.py — deny-listed, weakens non-vacuity.)

**A3 — dependent of a terminally-rejected dep hangs forever.** Dep gates (orchestrator.py:1283-1311; autowork_daemon.py:246-255) only treat ACCEPTED deps as met; an `.exhausted` dep leaves the dependent un-runnable + never blocked ⇒ dispatch timeout.
  - **Fix:** build a terminally-failed set (`state/tasks/blocked/*.exhausted` / `retry_exhausted` rows); route a candidate with such a dep via `_mark_blocked(..., 'dependency_failed')`. BOTH files **DENY-LISTED → operator-land** (harness_self_fix + decision file).

Each fix is oracle-first; verification_command = own oracle + HERMETIC regression only (never glob `tests/planner/`, never network/pip/rebuild-dry-run). Baseline = 10 pre-existing failures; bar = no NEW.

## PHASE B — BUILD THE 5 CHILDREN (dep order)
With blockers fixed, prefer the **autonomous daemon**: clear sentinels, run-gate `run`, `bash scripts/run-autowork.sh --state-dir state --logs-dir logs --config harness/config.yaml` (background). It auto-plans (Path B now works: 2-agent reconciled), executes, and commits via B0. Watch the first child's full cycle (plan→synth→`auto_commit`) to confirm, then hand off the long block.
  - If the daemon is still flaky: **hybrid** — `python -m harness.planner.cli brief_hooks_<child>.md --output-plan plan_hooks_<child>.json` (vet plan for dup tasks), then `bash scripts/impl_dispatch_once.sh <tid> state 1500`; B0 auto-commits. Stop the daemon before running planner.cli (agy must be serial — never concurrent with orchestrator).
  - Order: `symbol_ledger_module` → {`failure_propagation_status`, `planner_depth_and_recursion`} → `staging_resolve_interfaces` → `e2e_acceptance_test`.

## PHASE C — FINALIZE
Flip `hierarchical_planning.symbol_ledger: true` + `failure_propagation: true` in harness/config.yaml (operator). Run the e2e acceptance. Restore run-gate `paused` at session end. `git push`.

## Gotchas (proven)
- `pkill -f` self-kills the issuing bash block (exit 144) — kill daemon/supervisor by explicit PID.
- Stale `state/control/autowork/git_commit.lock` (0-byte, prior session) wedges the daemon → self-heal $. Clean it before starting.
- Stale `state/output/<tid>.{patches,files}.json` poison re-dispatch — remove on re-attempt.
- New top-level symbol must R-anchor as a trailing node in an existing symbol's patch (implementation_notes hint), or hand-apply from `state/output/<tid>.patches.json`.
- Recover a spuriously-rejected-but-valid task from `state/output/<tid>.patches.json` (apply via `harness.git_integration._apply_symbol_patch`).
