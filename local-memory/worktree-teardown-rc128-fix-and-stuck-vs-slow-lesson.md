---
name: worktree-teardown-rc128-fix-and-stuck-vs-slow-lesson
description: Staging-worktree teardown rc=128 root-cause fix LANDED (4e21f39) + the gap-2 operational lesson (focused allowlist does NOT stop stale blocked tasks; stuck = needs intervention)
metadata: 
  node_type: memory
  type: project
  originSessionId: 616f554d-443f-40fc-8bb7-280ce6b027c0
---

✅ **WORKTREE-TEARDOWN rc=128 FIX LANDED+VERIFIED 2026-06-20 (`4e21f39`, impl) +
`0aaadf5` (pre-committed RED oracle).** Root cause (diagnosed with /tmp byte-for-byte
repro): `git_integration.remove_staging_worktree` ran `git worktree prune`
UNCONDITIONALLY FIRST, then `git worktree remove -f`. When a staging worktree's
working dir is gone but its admin entry (`.git/worktrees/<name>`) is still
registered (dangling), the leading prune DELETES that entry → the following
`remove -f` exits **128 `fatal: '<path>' is not a working tree`** → all 3 retries
re-prune → `rmtree(ignore_errors=True)` fallback silently MASKS it. `-f` was never
relevant (this is "no such working tree", not "dirty"). Fix = (1) drop the leading
prune so remove runs on the LIVE entry first; (2) treat stderr "is not a working
tree"/"no such working tree" as success; (3) log `e.stderr` (was discarded → blind
diagnosis). Oracle 4/4 GREEN on live HEAD. **WORKS not just BUILT** (diff read +
oracle re-run). ★NO daemon restart needed: `remove_staging_worktree` is called ONLY
from `harness/orchestrator.py` (worker subprocess, fresh per dispatch) — NOT from
autowork_daemon/state_reconciler, so the fix is live for all future tasks without a
restart. This was the prerequisite blocking the claudecap ORACLE's auto_commit
teardown. [[absent-peer-promotion-landed-and-orphan-agy-starves-planner]]

⚠️ **OPERATIONAL LESSON (owner-taught 2026-06-20): "slow" = will finish WITHOUT
intervention; "stuck" = REQUIRES intervention. If you had to intervene, it was
STUCK — don't report it as "slow, working properly."** I twice signed off as "slow"
when it was stuck. Two concrete root causes, both my misses:
1. **README §12 Gap #2 — a focused allowlist does NOT stop stale blocked/staged
   tasks from dispatching.** `_retry_blocked_tasks` re-stages `state/tasks/blocked/*.json`
   purely on backoff, with NO allowlist/eligibility check (allowlist gates PROMOTION,
   pause gates DISPATCH). Removing the global `pause` while a de-allowlisted brief
   still had `blocked/<tid>.json` (no `.exhausted`) → the daemon re-fired that stale
   task (claudecap-impl) ahead of my target, burning OAuth/agy quota. **FIX/DISCIPLINE:
   before unfreezing for a focused brief, MOVE ASIDE all stale `state/tasks/blocked/*`
   (+ `.retry.json`/`.exhausted`), queued sidecars, sessions, and test_results for any
   task you don't want dispatched.** A blocked task with `.exhausted` is inert (budget
   spent); a lone `.retry.json` (no `<tid>.json`) is inert; a bare `<tid>.json` WITHOUT
   `.exhausted` WILL re-fire.
2. **Check WHICH task is running, not just "a worker is alive."** A live worker on the
   WRONG task looks identical to progress. The live `inactivity_watchdog`
   (autowork_daemon.py:3152, fires `inactivity_watchdog_triggered` at >20min) keys on
   ANY agent-level event, NOT per-allowlisted-brief progress — so it does NOT flag
   "wrong task running, my brief starved" (that's the gap the queued default-OFF
   per-task watchdog was meant to close). Build a monitor that tracks the SPECIFIC
   task_id lifecycle + a wrong-task-dispatch guard + a real stall test (ledger idle
   >Nmin AND no worker), and only sign off on a concrete terminal/landed/stall signal.
[[turn-recurring-failures-into-pipeline-fixes]] [[dont-conflate-built-with-works]]
