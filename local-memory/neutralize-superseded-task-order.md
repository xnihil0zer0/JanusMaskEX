---
name: neutralize-superseded-task-order
description: "Correct ORDER to neutralize a superseded/blocked pipeline task: remove its slug + move its plan out of root BEFORE clearing its blocked/ sidecar — else the daemon re-extracts the now-unstaged plan task and re-dispatches the buggy candidate."
metadata:
  node_type: memory
  type: feedback
  originSessionId: ac57c0e0-1dc8-4930-b4ef-f690107be1f4
---

🪝 FOOTGUN (hit 2026-06-21 superseding the reap_spent_briefs parity impl). README §12 gap-2 says "to stop a withdrawn task, remove `state/tasks/blocked/<tid>.json` + sidecars" — but that is only HALF. If the task's `plan_hooks_<slug>.json` is still at root AND its slug is still allowlisted, removing the blocked sidecar makes the task look like an UNSTAGED plan task → the daemon's auto-promote RE-EXTRACTS it (`extract` row) and re-dispatches the same buggy candidate (proven: rm'd `blocked/reap-spent-briefs-parity-impl.json` → daemon re-extracted + launched a worker on it within one poll).

**Why:** auto-promote stages every unstaged plan task of an allowlisted brief each iteration; a task counts as "handled" only while it sits in `blocked/` or `processed/`. Clearing `blocked/` without removing the plan/slug returns it to "unstaged" → re-staged.

**How to apply — correct neutralization order (supersede a task cleanly):**
1. `touch state/control/autowork/pause` (stop dispatch atomically; reaper still runs).
2. Remove the slug from `auto_promote.allowlist` AND move `brief_hooks_<slug>.md` + `plan_hooks_<slug>.json` OUT of root (e.g. `_autowork_scratch/superseded_*/`) — so there is no plan to re-extract from.
3. THEN remove ALL task sidecars: `state/tasks/<tid>.json{,.processing}`, `state/tasks/blocked/<tid>.json`, the retry sidecar **`<tid>.retry.json`** (NOTE: it is `<tid>.retry.json`, NOT `<tid>.json.retry.json` — a `....json.retry.json` glob misses it), `<tid>.exhausted`, `state/control/autowork/running/<tid>.{pid,slot}`, `current_task_<tid>.json`, `state/output/<tid>.*`, old `decisions/<tid>.json`, sessions.
4. If a worker is live on the old task, `kill -TERM` its pid first; the oracle gates its candidate so it can't land bad code regardless, but killing prevents file-overlap churn against the replacement.
5. `rm pause` + `touch allowlist` to wake → daemon plans the replacement brief (newest mtime, allowlisted).

★ A blocked `<tid>.retry.json` left behind is the sneaky re-trigger: `_retry_blocked_tasks` scans `blocked/*.json` with NO allowlist check (README §12 gap-2), so it can re-fire purely from the sidecar even after the plan/slug are gone. Sweep blocked/ clean. Related: [[selfheal-skip-stalls-corrected-brief]], [[stale-sidecar-precedence-gotcha]].
