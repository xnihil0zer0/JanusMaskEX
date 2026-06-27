---
name: selfheal-skip-stalls-corrected-brief
description: Durable harness gotcha — a stale selfheal_skip marker silently stalls a corrected+re-planned brief at state=blocked (brief_status.py:74 keys on it for ANY slug); remove the marker to re-dispatch
metadata: 
  node_type: memory
  type: project
  originSessionId: 4cb1720c-7588-412a-ae4a-e3df016c8305
---

🪝 **STALE `selfheal_skip` MARKER SILENTLY STALLS A CORRECTED+RE-PLANNED BRIEF.** Hit 2026-06-19 driving Report-02 P2 (`report02-p2-onesided-impl`) through a re-build after an AST-validation failure.

**Mechanism (verified by reading code + `compute_brief_status` live):**
- A `synthesis_or_ast_failed` outcome is DETERMINISTIC → `_retry_blocked_tasks` (autowork_daemon.py:942-943) sets `effective_max=1` → instant `retry_exhausted`, which writes a PERSISTENT marker `state/control/autowork/selfheal_skip/<task_id>` (daemon ~:962) that "survives the harvester's blocked/ eviction."
- `compute_brief_status` (harness/brief_status.py:**74**) classifies a task as `blocked` if `blocked/<tid>.json` OR `blocked/<tid>.exhausted` OR **`control/autowork/selfheal_skip/<tid>`** exists — **for ANY slug**. (The `_is_selfheal_brief`-gated veto is a DIFFERENT guard at daemon:2926 — that one only fires for `selfheal_`-prefixed slugs, which misled me into thinking the marker was inert for a normal slug. It is NOT inert: line 74 is slug-agnostic.)
- A `blocked` task → brief `state='blocked'` (brief_status.py:80) → excluded from `unstaged_task_ids` (`staged_or_done` set, :89-90). Then the daemon's `_auto_promote`: **Path A** stages only `unstaged` (empty) and **Path B** plans only `unplanned` briefs (state≠unplanned) → BOTH paths skip it → silent stall, no telemetry.

**The trap:** correcting the BRIEF (.md) for an AST failure + clearing `blocked/` does NOT clear `selfheal_skip`. The daemon even re-plans correctly (plan regenerates with the corrected exec-free guidance — confirmed in non_goals), but the stale marker keeps `state=blocked` so the regenerated plan's task never re-dispatches.

**FIX (operator, sanctioned — control-plane, not production code):** `rm state/control/autowork/selfheal_skip/<task_id>` → re-run `compute_brief_status` to CONFIRM `state` flips to `queued` and the tid appears in `unstaged_task_ids`. Then bump the **G-IDLE wake signal** to wake the idle daemon: it wakes edge-triggered on max-mtime of (`auto_promote.allowlist` + `brief_hooks_*.md`) (daemon:2345/2687), else sleeps to the 1800s heartbeat. A state-only change does NOT wake it — `touch state/control/autowork/auto_promote.allowlist` (leaves the brief mtime alone → no plan-staleness). Daemon then emits `idle_wake`→`extract`→`launch`→`worker_start`. P2 then cleared ast_validation exec-free and landed `a12c851` (oracle 11/11, OFF byte-identical, BYPASS unchanged, ON shadow logs `verdict=unverified tier=determinism_only`).

✅ ROOT-CAUSE PIPELINE FIX **LANDED + VERIFIED 2026-06-19** (`a0f389b`, slug `briefstatus_stale_skip_gate`, oracle 8/8, exec-free): added `_selfheal_skip_blocks(state_dir, tid, plan_mtime)` to brief_status.py — the `blocked` comprehension's selfheal_skip term now counts ONLY when `marker_mtime >= plan_file mtime` (a marker OLDER than the current plan = stale → ignored). `blocked/<tid>.json` + `.exhausted` stay unconditional. Behaviorally proven via os.utime: STALE marker→blocked=[]/unstaged=[tid] (re-dispatchable); FRESH→blocked=[tid]; .exhausted→still blocks. So the stall self-heals now: a corrected+re-planned brief (plan mtime > marker mtime) re-dispatches with NO manual marker removal. (The manual `rm marker` + `touch allowlist` recipe above is still the recovery for a marker written by an OLD daemon binary pre-`a0f389b`, or when the plan was NOT regenerated.) Per [[turn-recurring-failures-into-pipeline-fixes]] + [[fixes-are-permanent-and-reusable]]. Relates to [[stale-sidecar-precedence-gotcha]] + [[report03-p0-landed-and-epic-partial-activation]] (Int 2 build-out).
