---
interfaces: "_strip_unresolvable_dependencies(tasks: list[dict]) -> None — drop each task dependency that is not a task_id of another task in the same plan; called from normalize_plan"
---

# Title

Normalizer pass: strip in-plan-unresolvable task dependencies (harness/planner/plan_normalizer.py)

# Scope

Fix the dependency-slug-drift defect found 2026-06-09 during the autocompiler Phase-A run: an epic
child brief carries frontmatter `dependencies:` naming SIBLING brief SLUGS (e.g. `ac_flags`,
`ac_population_db`). When that child is planned in isolation as a leaf, the slug strings land in the
generated task's `dependencies`. The autowork daemon gates dispatch (`collect_dispatchable_tasks`,
`harness/autowork_daemon.py:~246`) on each dependency string being a real ACCEPTED `task_id`, so a
slug matching no task_id in the same plan is unsatisfiable by construction and permanently wedges the
task (observed: `autocompiler_loop_impl` stuck on 8 sibling slug-deps AFTER all 8 modules were built
and committed). Cross-brief / cross-epic sequencing is a BRIEF-level concern (held briefs, allowlist,
epic child ordering); intra-plan task `dependencies` may only name sibling tasks of the same plan.

Add ONE new helper `_strip_unresolvable_dependencies(tasks: list[dict]) -> None` to
`harness/planner/plan_normalizer.py` (mirrors the existing in-place `_enforce_module_first(tasks)
-> None` pure-pass idiom): build the set of in-plan `task_id`s, then for each task filter its
`dependencies` list to keep ONLY entries that are str AND a member of that set, preserving original
order; mutate in place, return None; tolerate missing/None/non-list `dependencies` and non-str dep
entries. Call it from `normalize_plan` (`:538`) AFTER `_enforce_module_first(tasks)` and before the
later passes, operating on the same `tasks` list.

meta_task_type=`harness_self_fix` (sensitive `harness/planner/**`; operator decision file provided).
verification_command: `python -m pytest tests/planner/test_strip_unresolvable_deps.py tests/planner/test_strip_unresolvable_deps_wired.py -q`

# Required plan shape

ONE impl task; meta_task_type=`harness_self_fix`; files_touched=
`["harness/planner/plan_normalizer.py"]`; verification_command EXACTLY as above — it MUST name BOTH
oracle files, including the `..._wired.py` token (the plan validator requires a `*_wired` oracle for
any task editing a non-test `.py` file; omitting it fails `missing_wiring_oracle`). Both oracles are
PRE-COMMITTED and RED — their docstrings/assertions are the authoritative contract; do NOT author
tests. The task's `spec.non_goals` MUST contain the literal word `integration` (e.g. "No integration
test — exercised by the existing planner pipeline") so the `missing_integration_test` check is
excused — MANDATORY (the prior plan was discarded for omitting it). >=2 edge_cases mirrored in
regression/property tests (e.g. (a) a real intra-plan dep is preserved, (b) idempotent / strict no-op
on an already-clean plan, (c) None/non-list deps and non-str entries tolerated without raising).
EMISSION: symbol patches — the NEW top-level helper
`_strip_unresolvable_dependencies` rides as an R-ANCHORED trailing node of the `normalize_plan`
symbol patch (the documented new-top-level-symbol recipe), plus the one-line call inside
`normalize_plan`. Do NOT emit whole-file or `__JANUSMASK_MANIFEST__` for this EDIT.

# Inputs

Pre-committed RED oracle `tests/planner/test_strip_unresolvable_deps.py` (authoritative contract).
Idiom precedents in the SAME file: `_enforce_module_first(tasks) -> None` (`:142`, in-place pure
pass) and the `normalize_plan` pass-chain (`:538-565`). The dispatch gate that makes unresolvable
deps fatal: `harness/autowork_daemon.py` `collect_dispatchable_tasks` `:246-255` (read-only context —
it is `_NEVER_AUTO_APPROVE`, do NOT edit it).

# Non-Goals

Do NOT edit `harness/autowork_daemon.py` or any `_NEVER_AUTO_APPROVE` file. Do NOT attempt to MAP
slug-deps to sibling task_ids (the sibling task_ids are unknowable when a child is planned in
isolation) — the correct behaviour is to STRIP the unresolvable entries, not remap them. Do NOT
remove resolvable intra-plan deps or reorder tasks. Do NOT touch cycle detection in
`plan_validator.py`. Behaviour for plans whose deps are all already in-plan must be byte-identical
(idempotent no-op). Do NOT author or modify tests (oracle pre-committed). Integration with the
daemon dispatch loop is exercised by the existing pipeline, not re-tested here.

# Deliverables

EDIT `harness/planner/plan_normalizer.py`: new `_strip_unresolvable_dependencies(tasks) -> None` +
one-line call from `normalize_plan`. Turns `tests/planner/test_strip_unresolvable_deps.py` GREEN with
zero regressions in the existing planner suite.
