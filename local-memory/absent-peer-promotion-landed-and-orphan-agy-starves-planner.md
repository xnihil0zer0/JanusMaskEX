---
name: absent-peer-promotion-landed-and-orphan-agy-starves-planner
description: Absent-peer single-agent promotion fix LANDED clean (afcf85e+db95fef); planner ~302s rc=2 timeouts root-caused to stale agy orphans starving the shared ~/.gemini backend
metadata: 
  node_type: memory
  type: project
  originSessionId: 616f554d-443f-40fc-8bb7-280ce6b027c0
---

✅ CLEAN END-TO-END PASS 2026-06-20. The absent-peer single-agent promotion fix
LANDED through the pipeline with zero manual drive: impl `afcf85e`
(harness/orchestrator_worker.py +58/-9 — routes the case where one active agent
returns code and the peer returned None through the EXISTING
`_single_agent_promotion_decision` gate before the retry/continue fallback) +
oracle `db95fef` (tests/adversarial/test_p5b_promotion_wiring.py, 5 tests, vcmd
`5 passed`). The self-ref lint [[watchdog-stall-brief-queued-and-daemon-denylist]]
context (e0a5303 + 8cebe55) is also live.

⚠️ **CORRECTION 2026-06-20 (BUILT≠WORKS [[dont-conflate-built-with-works]]):** afcf85e
did NOT actually unblock claudecap-impl. Re-engaged claudecap (cleared blocked/exhausted
markers + stale sessions, allowlist→idle_wake re-extracts, NO daemon restart needed —
orchestrator_worker.py is fresh per worker subprocess). Impl re-ran and STILL failed
`synthesis_or_ast_failed / "no error-severity AST violations recorded"`. ROOT CAUSE
(code-proven, orchestrator_worker.py:1019-1021): the XOR promotion gate refuses unless
`consecutive_failures >= single_agent_promotion_ceiling (3)`, but `consecutive_failures =
retry_sidecar.attempts + 1` and a deterministic `synthesis_or_ast_failed` gets retry
budget **1** → max **2** dispatches → consecutive_failures maxes at **2 < 3** → promotion
NEVER fires. Evidence: claude emitted a VALID 25KB `__JANUSMASK_MANIFEST__`; gemini
produced NO submission session at all (agy times out on the big 3-file harness edit). The
ceiling is structurally unreachable for large harness edits where one agent times out.
The claudecap-ORACLE separately fails `auto_commit_failed` (authored test not
self-isolating → `git worktree remove` exit-128 on staging teardown). Both handed to a
fresh general-purpose agent (a450654bf29109578) to fix through the pipeline (recommended:
absent/EMPTY-peer waives the ceiling, since a timeout is deterministic-futile to retry —
same logic as budget=1). NOT yet landed.

🔑 ROOT CAUSE of recurring planner `planner_validation_rejected wall=~302s
reason=rc=2 stderr_tail=(empty)`: NOT a brief defect. The planner's gemini
blind-draft was starved by **stale agy orphans racing the shared `~/.gemini`
HOME** (agy_pool disabled → one shared session). 4 agy procs idle 1-2 DAYS
(parents = dead gnome-terminal bash shells / systemd) held the backend; the
planner's draft hit an internal ~300s timeout → degraded → rc=2. DIAGNOSIS PATH:
(1) `wall=302` with rc=2 NOT 124 = subprocess exited on its own, not the daemon's
1800s `_planner_timeout`; (2) every cli rc=2 path prints non-empty stderr but
ledger stderr_tail was EMPTY → not a validate_plan failure (that's rc=1,
cli.py:498); (3) `state/planning/planner_progress.jsonl` showed the run died at
`blind_drafts`; (4) `pgrep -af agy` + `ps -o ppid,etime` exposed the day-old
orphans. FIX = reap them (`kill -TERM`), then planner ran uncontended at wall=107s
→ valid plan → both tasks landed. ★Recurring leak: orphan agy accumulation
starving the backend is exactly what state_reconciler reap / the queued watchdog
brief should kill automatically — manual reap = the real defect.

⚠️ **CORRECTION 2026-06-22 (adversarial-eval, agent4_planner, script-backed):** do NOT
cite orphan-starvation as the GENERAL planner-latency root cause. The 2026-06-20 reap→107s
was a real OBSERVED before/after for THAT incident, but a 53-plan ledger study found planner
latency is BIMODAL (median **119s**, not slow) and the recent heavy-brief tail (targets_dir,
manifest_drop, p11 @ 1500-1791s) shows **zero** orphan/contention telemetry — every slow
window had concur_pids=1, 0 spawn events, 0 live agy. The MEASURED root cause of the heavy
tail is **sequential claude→gemini blind-drafting** in `antigravity_mode=True`: blind_drafts
60% + reconciliation 26% (both run the two agents back-to-back) + adversarial_review 14% =
86.3% of wall-time; pure-harness stages are ~0.0s. Real lever = parallelize the two drafts
(or single-drafter for trivial briefs). Orphan→slowness is **plausible-but-UNPROVEN** (the
ledger doesn't log agy pids, so it's absence-of-evidence) — demote it until someone captures
live agy-pid + ~/.gemini-lock timing during a slow plan. Also: agy logs show "not logged into
Antigravity"/"Failed to poll FetchAvailableModels" even while the model override fires —
served capacity under that auth state is unverified.

★VALIDATE-BEFORE-DISPATCH the RIGHT way: run the planner LOCALLY in the daemon's
EXACT mode = `python -m harness.planner.cli <brief> --output-plan /tmp/x.json`
(NO flag → `--bootstrap` default=True, cli.py:404). `--non-bootstrap` is STRICTER
(requires BOTH drafts non-empty + track record, cli.py:463-479) → false failures
the daemon never hits. The six test_spec rules are in plan_validator.py:243-267:
unit_tests>=functional_requirements; prop+reg>=min(2,edge_cases); minimum_test_count
>=1.5*FR; integration excused by literal `integration` token in non_goals; all
test_spec fields present. A brief's `# Required plan shape` must spell these out or
the LLM planner under-specifies test_spec.

★Detector bug: `auto_commit`/`accepted` ledger rows stamp an ISO-STRING ts
(`2026-06-20T16:16:20Z`), not an epoch float → the `ts>since` numeric filter in
claudecap_stall_detector.sh SKIPS them → false STALL after a successful land. Fix
the filter to parse ISO ts. [[stale-state-recovery-complete-2026-06-18]]
