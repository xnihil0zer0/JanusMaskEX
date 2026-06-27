# Cleanup-system brief family — STAGED 2026-06-21, dispatch AFTER P1.1/build_evidence lands

Origin: owner asked to automate the manual operator re-dispatch ritual so cleanup can't be messed up.
Adversarial audit (agent a1118b689c33f1941) verified the design claims; ONE claim corrected:
- CORRECTED: `cleanup_state`/`reap_orphaned_workdirs` ARE liveness-guarded (os.kill(pid,0), fail-closed EPERM).
  The real gap is NOT a missing live-check — it is the ABSENCE of any by-task purge primitive for
  output/sessions/processed/test_results/fuzz/blocked sidecars (clearing is scattered across ~8 partial sites:
  _purge_stale_sidecars_safe orchestrator_worker.py:73 = patches+files ONLY; _clear_stale_submissions
  orchestrator.py:1263 = sessions only; blocked-trio copy-pasted selfheal.py:379/407 + planner/staging.py:88).
- VERIFIED TRUE: janusmask/work = local no-`--force` push target git_integration.py:1912, no reset helper;
  cleanup_state(apply) archives brief_hooks_*.md (JSONDecodeError→CORRUPT→archivable :580-409);
  compute_brief_status re-opens tasks (brief_status.py:97-128) but never purges their stale sidecars.

## Briefs (repo root, plan-validated rc=0, NOT allowlisted, NOT dispatched)
1. brief_hooks_purge_task_state_primitive.md
   - core: manifest-driven `purge_task_state(root, task_id, ...)` in harness/state_reconciler.py
   - refuses-when-live (reuse task_id_has_live_pidfile); NEVER touches brief_hooks_*.md; exact-template
     manifest (no broad *<tid>* globs); idempotent; default-OFF flag `autowork.purge_task_state.enabled`
   - operator/callable path only — NOT auto-wired into a live sweep (cannot perturb a live run)
   - state_reconciler.py NOT in _NEVER_AUTO_APPROVE -> NO decision file needed
   - tasks: purge-task-state-primitive-oracle + -impl
2. brief_hooks_purge_on_reopen_autofire.md
   - guarded auto-fire wrapper: fire ONLY when (NOT live) AND (brief/plan SHA actually changed, prev!=new)
   - default-OFF `autowork.purge_task_state.autofire_on_reopen`; HARD-DEPENDS on #1 symbol existing
   - tasks: purge-on-reopen-autofire-oracle + -impl
3. brief_hooks_reset_external_engine_ref_invariant.md
   - manual-recovery `reset_external_engine` in TRUST-CORE harness/git_integration.py
   - re-points EVERY worker push ref (janusmask/work) + ancestry assert + post-assert master==janusmask/work
   - uses git update-ref (NOT force-push); default-OFF; lowest priority
   - git_integration.py IS in _NEVER_AUTO_APPROVE -> REQUIRES decision file:
     state/control/decisions/reset-external-engine-ref-invariant-impl.json {"decision":"approve"}  (NOT yet staged)
   - tasks: reset-external-engine-ref-invariant-oracle + -impl

## DISPATCH SEQUENCE (do at the appropriate time, after build_evidence/P1.1 lands; avoids agy contention)
1) allowlist `purge_task_state_primitive` slug -> add to oversight_monitor WATCHED_SLUGS/TASKS -> land+verify.
2) THEN allowlist `purge_on_reopen_autofire` (dep on #1 landed).
3) Stage the git_integration.py decision file, THEN allowlist `reset_external_engine_ref_invariant` (lowest pri).
Each: confirm non-vacuous RED->GREEN, default-OFF (no prod behavior change until proven), no reliability/efficiency regression.
