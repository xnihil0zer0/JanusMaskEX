---
name: cleanup-state-apply-archives-root-briefs
description: cleanup_state(mode=apply) mis-archives ALL root brief_hooks_*.md as CORRUPT — never run it with pending briefs; use reap_stale_disk instead
metadata: 
  node_type: memory
  type: project
  originSessionId: a85a11bc-422b-4bdb-95ac-113027c51023
---

⚠️ `cleanup_state(mode='apply')` (harness/state_reconciler.py:333) is NOT a safe "stale cleanup" when pending briefs exist. Its product loop scans root `brief_hooks_*.md` AND `state/plans/*`, classifies each via `classify_product`, and **moves anything classified PLANNED/UNPLANNED/CORRUPT into `_autowork_archive/`**. Every `brief_hooks_*.md` classifies **CORRUPT** because `classify_product` (line 580) tries to `json.loads` the markdown as a plan and fails → so apply mode would **archive EVERY pending root brief** (proven 2026-06-20: report mode showed 31/31 would-archive). LIVE (running pidfile / within 60s write-settle) and FOREIGN (symlink) products are the only ones spared.

**For a shutdown "stale cleanup that preserves pending work":**
- `cleanup_state(mode='report')` is a PURE READ (safe; `_autowork_archive/` never created) — use it to SEE what apply would touch.
- Run `reap_stale_disk('.')` instead — reaps orphaned workdirs (`../<repo>_agentwork/`), compacts `impl_progress.jsonl` (never wipes), ages out logs, prunes old archive. Touches NO `brief_hooks_*.md` and NO `state/tasks/blocked/*`.
- Manually `rm` a verified-stale `state/control/autowork/git_commit.lock` (holder PID dead).
Graceful shutdown = `touch full_stop` then SIGTERM the supervisor (its trap drains the daemon child ≤35s); see [[daemon-supervisor-respawn]] / [[stale-state-cleanup-design]].
