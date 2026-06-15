---
interfaces: "_sensitive_glob_violations(task: dict, path_prefix: str) -> list[PlanViolation] — emits a sensitive_files_touched violation for each _SENSITIVE_APPLY_GLOBS path listed by a non-harness_self_fix task; called from validate_plan"
---

# Title

Validator guard: a non-harness_self_fix task may not list a sensitive-glob path in files_touched (harness/planner/plan_validator.py)

# Scope

Fix the planning-time gap (HANDOFF §2) observed on `ac-selection` / `ac-fitness-vector`: the planner
copied `config/autocompiler.yaml` (a registration file the task does not create) into a `data_model`
task's `files_touched`; at accept, `_enforce_apply_scope` refused the sensitive-glob write →
`auto_commit_failed`, retried to exhaustion. Nothing validates `files_touched` entries that fall
under `_SENSITIVE_APPLY_GLOBS` (`harness/**`, `config/**`, `scripts/**`, `services/**`) for tasks
that are not `meta_task_type: harness_self_fix` — such a task can NEVER commit that path, so the
plan must be rejected at planning time with a clear message.

Add ONE new module-level helper to `harness/planner/plan_validator.py`:
`_sensitive_glob_violations(task: dict, path_prefix: str) -> list[PlanViolation]` — if the task's
`meta_task_type` is `harness_self_fix`, return `[]`; otherwise for each str entry of
`files_touched` matching any sensitive glob via `fnmatch.fnmatch` (after `\\`→`/` normalization),
emit `PlanViolation('sensitive_files_touched', f'{path_prefix}.files_touched', <message naming the
offending path and explaining a non-harness_self_fix task can never commit it>)`. Resolve the glob
tuple with the worker's proven idiom (`harness/orchestrator_worker.py:940-961`): `try: from
harness.git_integration import _SENSITIVE_APPLY_GLOBS as _GLOBS except Exception: _GLOBS =
('harness/**', 'config/**', 'scripts/**', 'services/**')` (import inside the helper). Tolerate
missing/None/non-list `files_touched` and non-str entries (skip, never raise). Call the helper from
`validate_plan`'s per-task loop, extending the violations list.

meta_task_type=`harness_self_fix` (sensitive `harness/planner/**`; operator decision file provided).
verification_command: `python -m pytest tests/planner/test_files_touched_sensitive_guard.py tests/planner/test_files_touched_sensitive_guard_wired.py -q`

# Required plan shape

ONE impl task; meta_task_type=`harness_self_fix`; files_touched=
`["harness/planner/plan_validator.py"]` (NO other paths — listing any other path is itself the trap
this leaf fixes). The verification_command EXACTLY as above — it MUST name BOTH oracle files
including the `..._wired.py` token (omitting it fails `missing_wiring_oracle`). Both oracles are
PRE-COMMITTED and RED — their docstrings/assertions are the authoritative contract; do NOT author
tests. The task's `spec.non_goals` MUST contain the literal word `integration` (e.g. "No integration
test — exercised by the existing planner pipeline") so the `missing_integration_test` check is
excused — MANDATORY. >=2 edge_cases mirrored in regression/property tests (e.g. (a) each of the four
globs is caught, (b) a harness_self_fix task with a sensitive path is untouched, (c) free paths and
tests/** are untouched, (d) None/non-list files_touched tolerated without raising). EMISSION: symbol
patches — the NEW top-level helper `_sensitive_glob_violations` rides as an R-ANCHORED trailing node
of the `validate_plan` symbol patch (the documented new-top-level-symbol recipe), plus the call
inside `validate_plan`'s per-task loop. Do NOT emit whole-file or `__JANUSMASK_MANIFEST__` for this
EDIT.

# Inputs

Pre-committed RED oracle `tests/planner/test_files_touched_sensitive_guard.py` (authoritative
contract: violation code is EXACTLY `sensitive_files_touched`) and wiring oracle
`tests/planner/test_files_touched_sensitive_guard_wired.py` (asserts `_sensitive_glob_violations` is
module-level and invoked from `validate_plan`). The canonical glob source:
`harness/git_integration.py:16` `_SENSITIVE_APPLY_GLOBS` (read-only context — do NOT edit it). The
worker's try-import fallback idiom: `harness/orchestrator_worker.py:940-961` (read-only context).
`PlanViolation` is defined in the same file (`:64`). The per-task loop lives in `validate_plan`
(`:112+`), which already appends from helpers like `check_missing_fields`.

# Non-Goals

Do NOT edit `harness/git_integration.py`, `harness/orchestrator_worker.py`, or any
`_NEVER_AUTO_APPROVE` file. Do NOT strip or mutate `files_touched` (that is the normalizer's job;
this leaf REJECTS with a violation). Do NOT exempt any non-`harness_self_fix` meta type. Do NOT
touch `_is_module_creating`, `_is_wiring_oracle`, or any other existing symbol's logic. Behaviour
for plans with no sensitive paths must be byte-identical. Do NOT author or modify tests (oracles
pre-committed). No integration test — exercised by the existing planner pipeline.

# Deliverables

EDIT `harness/planner/plan_validator.py`: new `_sensitive_glob_violations(task, path_prefix)` helper
+ its call from `validate_plan`. Turns `tests/planner/test_files_touched_sensitive_guard.py` GREEN
with zero regressions in the planner suite.
