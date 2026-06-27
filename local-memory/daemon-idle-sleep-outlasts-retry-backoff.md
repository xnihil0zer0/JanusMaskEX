---
name: daemon-idle-sleep-outlasts-retry-backoff
description: Daemon idle heartbeat sleep (1800s) is longer than the shortest blocked-task retry backoff (300s) → a freshly-blocked task waits up to ~30min for its next retry-scan instead of ~5min; touch allowlist to wake early; root-cause fix = cap idle sleep by nearest pending retry deadline
metadata: 
  node_type: memory
  type: project
  originSessionId: abc9547b-8d8a-4bd6-b44d-ee0591b3fcfc
---

OBSERVED 2026-06-23 (overseeing wire-up brief #6): a blocked task that is RETRY-ELIGIBLE
can still sit unretried for up to the full idle cycle.

MECHANISM: `_retry_blocked_tasks` (autowork_daemon.py:911) re-stages a blocked task once
its backoff elapses — for `attempts<=1` the backoff is **300s** (line 980-981). But after the
daemon routes an orphan to blocked/ and finds nothing else dispatchable, it goes IDLE with a
**1800s** heartbeat sleep (`event:idle detail:heartbeat=1800.0`). The retry-scan only runs at
the TOP of each daemon iteration, so the next scan is ~1800s away — NOT 300s. Net: a task
blocked right before an idle sleep waits up to ~30min (the idle cycle), not its ~5min backoff.
This is a LATENCY gap, not a correctness bug — the task DOES eventually retry (at the next
iteration). `orphaned` is non-deterministic ⇒ `effective_max=3` (deterministic outcomes get 1).

CONCRETE INSTANCE: wireup-detonation-prompt-oracle hung (Claude/Opus PTY stall, 30min) →
watchdog_kill → task_blocked at 13:03:50 → daemon idle 1800s. Backoff elapsed at 13:08:48 but
no re-stage; daemon would not have rescanned until 13:33:50.

WORKAROUND (operator, documented): `touch state/control/autowork/auto_promote.allowlist` →
`idle_wake (allowlist/brief change detected)` → immediate iteration → `extract retry_blocked`
→ relaunch. Verified: woke + re-staged + relaunched within ~2s. (A content-free touch does NOT
re-plan an existing plan.) See [[selfheal-skip-stalls-corrected-brief]],
[[absent-peer-promotion-landed-and-orphan-agy-starves-planner]] which also cite this wake.

ROOT-CAUSE FIX: cap the idle sleep by the nearest pending blocked-retry deadline —
`sleep = min(idle_heartbeat, max(grace, min_over_blocked(last_ts + backoff(attempts)) - now))`.
Then a freshly-blocked task auto-retries on ITS backoff, no manual wake.
([[turn-recurring-failures-into-pipeline-fixes]], [[fixes-are-permanent-and-reusable]]).

✅ OWNER GREENLIT 2026-06-23 — route BOTH this AND the spent-brief auto-archive-miss as pipeline
briefs. ORDERING (owner directive): **IF brief #7's BUILD hits this idle-sleep stall** (watchdog_kill
→ blocked/ → ~30min idle-before-retry), fix THIS idle-sleep gap FIRST (jump the queue) so #7 stops
stalling, then resume #7. **IF #7 builds clean**, finish #7 (verify observed-working) THEN do BOTH
hygiene fixes. (Stall risk applies only to FACTORY-WORKER builds under the watchdog, not to my own
oversight sub-agents.)

✅ FIX #1 (IDLE-SLEEP CAP) LANDED + VERIFIED observed-working 2026-06-23 — oracle 932c12b + impl 06833ea
(brief_hooks_daemon_idle_sleep_cap.md, slug daemon_idle_sleep_cap, NO stall during its own build).
New pure helper `_soonest_blocked_retry_deadline(state_dir)` (autowork_daemon.py:911+) mirrors
`_retry_blocked_tasks`'s enumeration/backoff (deterministic-outcome tuple INLINED, not the function-local
name) + a one-line idle-branch cap in run_daemon (:2989+): `if is_idle: _dl=...; if _dl is not None:
sleep_target=min(sleep_target, max(5.0, _dl-time.time()))`. INDEPENDENT adversary drove the REAL committed
helper AND `_retry_blocked_tasks` at HEAD (18/18): nearest-deadline wins + tier-2; cap shrinks below
heartbeat (200s vs 1800) with 5.0s grace floor (no busy-spin); ★ELIGIBILITY PARITY — helper's contributing
set EXACTLY == what `_retry_blocked_tasks` re-stages (diff=∅, the cap wakes the daemon at precisely the
instant a task is re-stageable); fail-soft + zero state mutation. Adversarial review pre-dispatch caught a
`priority: P1` invalid_priority_encoding plan-reject trap + the function-local `_DETERMINISTIC_OUTCOMES`
NameError risk (both fixed in the brief). ⚠️ LIVE ACTIVATION pends the daemon's next idle self-reload
(autowork_daemon.py is own-source → clean-exit→respawn picks it up). FIX #2 (auto-archive) dispatched next.

RELATED HYGIENE FIX (also greenlit): SPENT BRIEFS DON'T AUTO-ARCHIVE — `reap_spent_briefs` did NOT
fire for brief #5 OR #6 even on a fresh daemon iteration (woke via idle_wake, iterated, brief stayed
in root); hand-archived both. 2× recurring. Both fixes are the watchdog/retry/reap self-management layer.

✅✅ BOTH FIXES COMPLETE + VERIFIED + LIVE-PROVEN 2026-06-23 (no stalls during either build):
- FIX #1 IDLE-SLEEP CAP: oracle 932c12b + impl 06833ea (see detail above). 18/18 independent verify incl
  eligibility-parity diff=∅.
- FIX #2 AUTO-ARCHIVE: oracle 089c5d0 + impl 5a922a1. ★ROOT CAUSE (authoring agent DISPROVED the de-slug
  hypothesis — reap is allowlist-INDEPENDENT): a FIRE-ONCE-NO-CATCH-UP gap. The only automatic reaper was
  the worker hot path `_reap_spent_briefs_safe`→`reap_for_task(task_id)` (runs once per task-accept, that
  task only); the full-scan `reap_spent_briefs` was wired ONLY into MANUAL `cleanup_state(mode=apply)`; and
  the per-iter daemon sweep `_reclaim_zombie_briefs` explicitly SKIPS fully-landed pairs (`if fully_landed:
  continue`, autowork_daemon.py:2302). So any pair whose accept-moment was disturbed was never revisited
  (47 un-reaped pairs). FIX = additive `try: reap_spent_briefs(root) except: pass` final step in
  `reap_orphaned_workdirs` (state_reconciler.py:806-812, called every daemon iter), mirroring the
  detect_and_heal_stalls step. 43/43 independent verify (drove the REAL committed reap_orphaned_workdirs):
  archives via the wiring, partial/epic kept, de-slugged regression archived, RETURN VALUE UNCHANGED,
  NO DEADLOCK under the held reentrant `state_reconcile_lock`. LIVE PROOF: after daemon restart the new
  daemon's first-iteration reap swept the backlog — brief_hooks 69→21, plan_hooks 52→4, 96 files (48 pairs
  incl #2's OWN brief) MOVED to _autowork_archive/2026-06-23/reconciled/. Pushed 96559fa..5a922a1.

⚠️ FINDING (NOT yet fixed — pre-existing, surfaced during #2 activation): the long-lived daemon (pid 533029,
15h uptime) did NOT self-reload after autowork_daemon.py changed (#1), even at idle with no rebuild job /
no running .pid. Most likely an EMPTY `startup_sha` (the watch-set modules {autowork_daemon, autowork_parallelism,
brief_status, planner.staging, selfheal} weren't all in sys.modules when run_daemon captured startup_sha at
boot → `_should_reload_daemon`'s `if current and startup_sha` guard fails → reload permanently disabled for
that instance). ALSO: `state_reconciler.py` is NOT in the watch set, so #2 needed a manual restart regardless.
RESOLVED THIS TIME via `kill -TERM $(cat state/control/autowork.pid)` → supervisor (run-autowork.sh) respawn
(both fixes loaded fresh from disk; new pid 680922 reached idle cleanly = both new code paths ran live w/o
crash). Possible future brief: (a) make startup_sha capture robust (import the watch-set modules before hashing,
or fall back to file-path hashing), (b) add state_reconciler to the watch set. Owner-gate before authoring —
do NOT invent. See [[daemon-self-reload-landed]], [[daemon-supervisor-respawn]].
