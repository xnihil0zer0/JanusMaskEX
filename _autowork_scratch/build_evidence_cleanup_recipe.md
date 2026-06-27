# build_evidence honest re-dispatch — EXECUTE AFTER briefstatus_accept_staleness lands + daemon restart

Forensics (agent a91d4236, 2026-06-21): brief PROSE is CORRECT (no edit needed for correctness).
Root cause = stale boolean oracle. The CORRECT artifacts-only impl 61e1098e (dangling/orphaned) was
REJECTED by the boolean oracle at 14:41:22Z (blocked_by ['triage_result']); the dead-else impl 1f2d6ef
PASSED it and committed false-green at 16:52:23Z. Reset to a970fc7 = clean (diff = exactly the 2 paths).

## A. NGv2 — drop both false-green commits (clean, surgical)
cd /home/xnihil0zer0/NobleGreedv2
git status --short                 # confirm clean tree
git reset --hard a970fc7           # drops 1f2d6ef(impl)+8144d72(oracle); deletes stale boolean test; restores pre-perphase build_evidence
git branch -f janusmask/work a970fc7  # ★CRITICAL (learned the hard way): the worker accept-push is `git push . <sha>:refs/heads/janusmask/work` (git_integration.py:1912, NO --force, LOCAL). Reset of master ALONE leaves janusmask/work at 1f2d6ef -> every new commit is non-FF-rejected -> oracle auto_commit_failed THRASH. Align janusmask/work too (a970fc7 is an ancestor of 1f2d6ef, safe). GitHub origin is NOT the push target; ignore origin divergence.
git log --oneline -3               # expect a970fc7 at HEAD

## B. JM — purge stale sidecars/sessions/processed/caches (all verified to exist; regenerate on re-dispatch)
cd /home/xnihil0zer0/JanusMaskJR
rm -f state/output/p11-build-evidence-perphase-impl.py \
      state/output/p11-build-evidence-perphase-impl.fallback.py \
      state/output/p11-build-evidence-perphase-impl.fallback.patches.json
rm -f state/sessions/claude_fallback_round1_p11-build-evidence-perphase-impl_submission.json \
      state/sessions/gemini_round1_p11-build-evidence-perphase-impl_submission.json \
      state/sessions/pty_claude_p11-build-evidence-perphase-impl.snapshot.txt
rm -f state/tasks/processed/p11-build-evidence-perphase-impl.json   # CRITICAL: embeds stale boolean ORACLE CONTRACT
rm -f state/tasks/test_results/p11-build-evidence-perphase-impl_baseline.json
rm -f logs/fuzz_results/p11-build-evidence-perphase-impl_stateful.json
rm -f state/control/autowork/running/p11-build-evidence-perphase-impl.slot  # ONLY this task's slot; leave others

## C. JM — remove stale plan (both copies carry the boolean oracle)
rm -f plan_hooks_p11_build_evidence_perphase.json
rm -f _autowork_archive/plan_hooks_p11_build_evidence_perphase.json

## D. Content-edit the brief (bumps SHA -> SHA-reaper archives stale plan -> re-plan at new mtime ->
##    brief_status(FIXED) re-opens both accepted tasks since acceptance_ts < plan_mtime). NOT a no-op touch.
##    Append a dated RE-DISPATCH note to brief_hooks_p11_build_evidence_perphase.md. VALIDATE plan after.

## E. Wake daemon (allowlist touch / restart child). DO NOT rewrite state/impl_progress.jsonl (append-only;
##    brief_status fix handles stale-accept re-open via plan_mtime).

## Post-cleanup sanity
- New plan_hooks_*.json embedded oracle must carry an `artifacts` list discriminated by data.phase
  (NOT 'triage_result': True), and both task ids show re-opened (not accepted).
- WORKS proof required beyond unit green: live run_hunt traversal reaching triage/verify/novelty/report
  on production state['artifacts'].
