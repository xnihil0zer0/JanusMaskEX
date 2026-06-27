---
name: backup-detach-fixes-systemic-autocommit
description: Synchronous drive-backup parked the 60s commit lock → epidemic auto_commit_failed; detached via render_shim (setsid) — landed JM 9f35a34
metadata: 
  node_type: memory
  type: project
  originSessionId: ae16acba-9ad9-45c6-989f-a8c880d79cef
---

🔧 SYSTEMIC `auto_commit_failed` ROOT-CAUSED + FIXED (2026-06-15, JM `9f35a34`).

**Root cause (non-obvious):** the auto-commit push (`git push . <sha>:refs/heads/janusmask/work`, git_integration.py:1726) runs SYNCHRONOUSLY *while holding* the 60s-bounded `git_commit.lock` (`_GIT_COMMIT_LOCK_DEADLINE_SEC = 60.0`, orchestrator.py:2251). The drive-backup pre-push hook tar+rclones the WHOLE repo per push (NGv2 = 150–340 MB → ~15 min). So every push parks the lock for ~15 min; any second worker fails to acquire in 60s → `auto_commit_failed` (orchestrator.py:2679 `git_commit_lock_timeout`); a worker that dies mid-push orphans its commit and leaves a STALE lock. This poisoned dozens of leaves in the log — it was the dominant "looks stuck" failure, NOT model/planner issues.

**Fix (permanent, reusable):** `tools/drive_backup/install_hooks.py` `render_shim` now emits a FULLY DETACHED backup: `JM_STDIN=... setsid bash -c '...hook_runner...' bash "$@" </dev/null >/dev/null 2>&1 &` then `exit 0`. setsid (new session) + all-three-std-fds→/dev/null + `&` means git inherits no open pipe/FD → push returns in **0.027s** (measured), backup still runs async. Chained original hook stays synchronous (gates the push). Oracle: `tests/drive_backup/test_install_hooks.py` (string-shape: setsid/`</dev/null`/`>/dev/null 2>&1`/trailing `&`; chained NOT backgrounded). Landed via pipeline (RED oracle `4e7c377` → brief → daemon build `9f35a34`).

**★ Live hooks only change on `python -m tools.drive_backup.install_hooks` RERUN** (sanctioned by the hook's own "rerun the installer" note) — landing render_shim does NOT rewrite `.git/hooks/pre-push`. After landing: rerun installer (updated both repos ok=True), then verify with a timed throwaway push.

**★ A prior-session HAND-EDIT of `.git/hooks/pre-push` (nohup &) did NOT work** — git still parked in `do_wait` because the child kept git's FDs; only setsid + full fd-redirect detaches. Owner feedback: stop hand-editing externally, fix via pipeline. See [[fixes-are-permanent-and-reusable]].

🔧 SECOND systemic fix SAME SESSION (JM `ae83cf6`): `compute_brief_status` (brief_status.py) built `accepted_map` from `accepted/auto_commit` rows WITHOUT honoring later `reject_rollback`/`task_blocked`. The worker logs `accepted/auto_commit` at COMMIT time; if the push/merge then fails, the commit is orphaned and the task routed to blocked — but the stale accept kept `unstaged_task_ids` empty so the daemon NEVER re-staged it (phantom-done). Fix: process the append-only ledger CHRONOLOGICALLY, `accepted_map.pop(tid)` on a later reject_rollback/task_blocked — last terminal event wins. RED oracle JM `49d6109`. ★`compute_brief_status` runs IN the daemon process (not a subprocess) → the running daemon must be RESTARTED (kill child, supervisor `scripts/run-autowork.sh` respawns) to load the fix; planner/worker spawns pick up harness changes immediately but the daemon loop does not. After restart the fresh daemon re-staged leaf-4a and landed it unattended (NGv2 `b1167ce`, 13/13) — first clean end-to-end auto-drive after the bugs. See [[daemon-supervisor-respawn]].

**★ Stale commit-lock is NOT the real blocker** — workers leave `state/control/autowork/git_commit.lock` holding a dead PID even on SUCCESSFUL landings, but the daemon reclaims dead-holder locks on next use (`_acquire_commit_lock_or_reclaim`); clearing it is cosmetic. The real blockers were backup-blocking + phantom-done, both root-fixed.

**Recovery recipe when a worker dies mid-push:** validated code survives as a DANGLING commit (`git cat-file -t <sha>`); clear the stale `state/control/autowork/git_commit.lock` (verify holder PID dead first), clean `state/output/<id>.py` + `state/tasks/blocked/<id>.{json,retry.json}`, restore brief + uncomment slug, `touch` brief to idle-wake → fresh re-drive. Context: [[factory-clobber-fix-and-ngv2-resume-2026-06-13]], source-driving epic [[source-driving-poc-epic-authored]].
