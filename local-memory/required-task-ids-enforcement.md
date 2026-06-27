---
name: required-task-ids-enforcement
description: Briefs can declare required_task_ids in frontmatter; validate_plan rejects any plan that drops one (missing_required_task). Layer 1 landed c6b28e0; Layer 2 = brief-completion ledger (keep brief open until all land)
metadata: 
  node_type: memory
  type: project
  originSessionId: ae16acba-9ad9-45c6-989f-a8c880d79cef
---

ROOT-CAUSE FIX for the planner silently dropping a brief's dependent task
(e.g. factory brief said "Emit EXACTLY TWO tasks" but only the edit landed; the
test_authoring oracle was omitted — confirmed plan-time: daemon idle_wake'd
repeatedly with no dispatch because the re-plan emitted only the no_diff edit).

★ LAYER 1 LANDED 2026-06-15 (JM `c6b28e0`, via pipeline, single-task brief to
bootstrap past the very drop-bug): a brief may declare `required_task_ids` in YAML
frontmatter (list OR comma-separated). `brief_loader.PlanningBrief` carries it
(field default `()`), `planner/cli.py` threads it onto the plan dict (mirrors
`working_dir`, BEFORE `validate_plan(final_plan)`), and `plan_validator.validate_plan`
appends a `missing_required_task` PlanViolation if any declared id is absent from
`seen_task_ids` (mirrors the existing cross-task `missing_wiring_oracle` precedent).
VERIFIED functional: plan declaring [edit, oracle] but emitting only edit →
missing_required_task; control (both present) → clean. Purely additive: briefs
without the field are unaffected.

★ CAVEAT: Layer 1 REJECTS an incomplete plan but does not itself ADD the missing
task — it relies on the planner being ABLE to (re-)draft a complete plan. If the
planner systematically can't emit the 2nd task, rejection alone loops. Watch for
rejection-loop exhaustion; the planner draft is nondeterministic so it usually
produces a complete plan within retries.

★ LAYER 2 (TODO): brief-completion ledger — a brief is not spent/archived until
EVERY required_task_id has reached committed; until then the daemon re-dispatches
the missing ones. This is what catches "task planned+landed but its sibling never
got built" even when Layer 1 passed. Declare its OWN required_task_ids (now
enforced). See [[red-gate-silently-stuck-every-harness-fix]],
[[factory-new-module-wireup-gates]].

★ AUDIT 2026-06-15: Layer 1 is BUILT-but-UNPROVEN — there is NO regression test for
the `missing_required_task` path anywhere (grep tests/ → none). Also c6b28e0 caused a
REGRESSION: appending `required_task_ids` as a trailing PlanningBrief field broke
`tests/planner/test_brief_loader_epic_parse.py` positional assertion (scoped vcmd missed
it); FIXED `9582415` (order-independent trailing-3 assert). Also brief_loader.py:43
declares the field mid-class after `to_agent_prompt` (works, cosmetic smell). LESSON:
adding a trailing dataclass field needs the WHOLE planner suite as vcmd, not a scoped one.

★ Layer 2 DECISION: do NOT build. Audit confirmed it's redundant — Layer 1 rejects a
dropped-required-task plan PRE-staging, so no perpetual-queued stuck state arises; re-plan
backoff recovers. Layer 2's only uncovered case = a required task staged-then-lost after a
VALID plan (rare). Not worth the regression risk.

Usage: add to any multi-task brief frontmatter:
  required_task_ids:
    - <task-id-1>
    - <task-id-2>
