---
name: planner-empty-plan-systemic
description: "empty_plan planner discards are SYSTEMIC (~92 across ~50 brief slugs, 57 in 3 days), NOT brief-specific — a real recurring planner-reliability defect; many briefs land only after 5-6 empty_plan retries. Root cause unfixed."
metadata: 
  node_type: memory
  type: project
  originSessionId: ae16acba-9ad9-45c6-989f-a8c880d79cef
---

⚠️ CORRECTS an earlier wrong dismissal. During the 2026-06-15 repair_feedback_oracle
work I claimed the planner's `empty_plan` discard was BRIEF-SPECIFIC (one bad brief).
A 4-lane adversarial self-audit REFUTED that: `state/impl_progress.jsonl` has ~92
`planner_hallucination_discarded reason=empty_plan` rows spread across ~50 DISTINCT
brief slugs (57 in the last 3 days). Repeat offenders: integration-smoke-* (×5-6 each),
conductor-seams ×5, metatype_coerce_oracle ×5, plus srcdrive_*, ngv2-*, webui-*,
stage-workers. Many briefs that EVENTUALLY landed first emitted 5-6 empty_plan discards.

★ This is the likely dominant cause of the "slow / feels stuck" the owner keeps hitting:
each empty_plan burns a full planner subprocess (~210-365s wall) then discards, and the
daemon only re-plans on next idle_wake/heartbeat. Symptom in telemetry: "CLAUDE
reconciliation artifact received (128 chars)" then "already exited (code 0)" — the
claude planner draft agent returns a near-empty artifact, reconciliation yields no
tasks, `_check_hallucination` flags `empty_plan`, daemon discards.

★ Distinguish from a DIFFERENT discard class: many of the ~132 total
`planner_hallucination_discarded` rows are `reason=wall<min` or
`Brief load failed: Validation failed` (brief schema problem) — only the ~92
`reason=empty_plan` are true empty drafts.

★ Backoff (`_recently_failed_to_plan`, autowork_daemon.py:1238) is 0/0/300/3600/86400s
by attempts — so it NEVER permanently stops re-planning; a brief self-recovers IF the
planner ever drafts a complete plan. Not a wedge, but expensive churn.

★★ ROOT CAUSE FOUND 2026-06-15 (live repro, daemon full_stopped): NOT empty drafts and
NOT a 128-char failure. Both agents draft REAL plans (claude 8145c, gemini 5165c); the
128-char "reconciliation artifact" is a VALID stance file (`{"responses":[{...,"stance":
"concede"}]}`). The tasks are KEPT through reconciliation, then DROPPED by
`harness/planner/plan_normalizer.py::_drop_redundant_precommitted_oracles`. That pass
drops a SINGLETON test_authoring oracle when its mutation_target module exists AND any
committed test "covers" it — where "covers" = a `tests/**/test_<leaf>.py` exists OR ANY
`tests/**/*.py` merely IMPORTS the dotted module. harness.orchestrator has 120 test
importers + tests/test_orchestrator.py, so EVERY new oracle for a core module is dropped.
For a single-oracle brief that empties the plan -> validate_plan rejects (missing_required_task
post-c6b28e0, or just tasks:[]) -> CLI writes empty plan -> daemon logs `empty_plan`. The
"empty plan" is a LAUNDERED task-drop. ★Trace: merged_plan.json was STALE (red herring);
the live evidence = run the planner CLI standalone + diff the per-spawn workdirs
(state/planning/sessions/*/workdirs/*/outbox/plan_draft.json) which PERSIST per spawn.

★★ FIX LANDED 2026-06-15 (JM `ac5af72`, via pipeline harness_self_fix, full adversarial
gate green): `_drop_redundant_precommitted_oracles` now drops the oracle ONLY when the SAME
plan has a non-test_authoring impl task whose files_touched includes `_module_path(target)`
— plan_normalizer.py:682 `impl_paths` set + :721 guard `covered and _module_path(target)
in impl_paths`. Standalone oracle (no impl sibling) -> KEPT. Scoped gate 9 passed
(test_dedupe_precommitted_oracle.py + test_plan_normalizer.py). The fix brief ITSELF
planned fine (harness_self_fix EDIT, not an oracle -> not subject to the bug), confirming
the diagnosis. ★Standalone oracle briefs (repair_feedback_oracle etc.) should now plan
non-empty — WORKS-proof = re-dispatch one and confirm no empty_plan (pending).
See [[selfheal-deadlock-blocks-all-dispatch]], [[required-task-ids-enforcement]],
[[red-gate-silently-stuck-every-harness-fix]].
