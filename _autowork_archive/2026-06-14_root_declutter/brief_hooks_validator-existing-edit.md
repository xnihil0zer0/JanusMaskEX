---
interfaces: "_is_module_creating(task: Any) -> bool — unchanged signature; returns True only when at least one non-test .py in files_touched does NOT already exist on disk (resolved against the repo root)"
---

# Title

Fix `_is_module_creating` over-trigger: an EDIT of an existing module is not module-creating (harness/planner/plan_validator.py)

# Scope

Fix the validator defect (HANDOFF §3) observed on every `harness_self_fix` EDIT leaf this cycle: a
task that EDITS an already-existing, already-wired module is flagged `missing_wiring_oracle` unless
its verification_command names a `*_wired.py` test — even though the module is already reachable and
the edit creates nothing. Root cause: `_is_module_creating` (`harness/planner/plan_validator.py:31`)
returns True for ANY task whose `files_touched` has a non-test `.py` and whose `meta_task_type` is
not a pure-edit type; it never checks whether the file already exists. The exact current loop body is:

```python
    for path in files_touched:
        if not isinstance(path, str) or not path.endswith('.py'):
            continue
        if 'tests/' in path.replace('\\', '/'):
            continue
        return True
    return False
```

The fix is confined to the single existing top-level function `_is_module_creating`: instead of
`return True` on the first non-test `.py`, resolve the path against the repo root and return True
ONLY if that file does NOT already exist on disk; if ALL non-test `.py` paths exist, return False.
Derive the repo root inside the function as `Path(__file__).resolve().parents[2]` (the file lives at
`<repo>/harness/planner/plan_validator.py`; `Path` is already imported at module top). Treat an
absolute `files_touched` path as-is (no repo-root join). FAIL-SAFE direction: a path that does not
exist (including external working_dir builds whose paths are not under this repo) is still treated
as module-creating, exactly today's behavior. Keep the existing pure-edit-type and `test_*` early
exits and all `isinstance` tolerance unchanged.

meta_task_type=`harness_self_fix` (sensitive `harness/planner/**`; operator decision file provided).
verification_command: `python -m pytest tests/planner/test_module_creating_existing_edit.py tests/planner/test_module_creating_existing_edit_wired.py tests/planner/test_missing_wiring_oracle.py -q`

# Required plan shape

ONE impl task; meta_task_type=`harness_self_fix`; files_touched=
`["harness/planner/plan_validator.py"]` (NO other paths — do not list test files or config). The
verification_command EXACTLY as above — it MUST include the `..._wired.py` token (the plan validator
requires a `*_wired` oracle for any task editing a non-test `.py` file; omitting it fails
`missing_wiring_oracle`). All three oracle files are PRE-COMMITTED — the first two are the
authoritative contract (currently RED), the third is the pre-existing regression guard that must
stay GREEN; do NOT author tests. The task's `spec.non_goals` MUST contain the literal word
`integration` (e.g. "No integration test — exercised by the existing planner pipeline") so the
`missing_integration_test` check is excused — MANDATORY. >=2 edge_cases mirrored in
regression/property tests (e.g. (a) a task whose only non-test .py exists on disk is NOT flagged,
(b) a genuinely new .py path is STILL flagged, (c) mixed existing+new is STILL flagged, (d)
pure-edit meta types remain exempt regardless of existence). EMISSION: symbol patches — re-emit the
single existing top-level function `_is_module_creating` with the existence check added. Do NOT emit
whole-file or `__JANUSMASK_MANIFEST__`; do NOT add new top-level symbols; touch exactly ONE symbol.

# Inputs

Pre-committed RED oracle `tests/planner/test_module_creating_existing_edit.py` (authoritative
contract) and wiring oracle `tests/planner/test_module_creating_existing_edit_wired.py`. The
pre-existing guard `tests/planner/test_missing_wiring_oracle.py` (its new-module cases use a
nonexistent `harness/newmod.py`, so they must STAY rejected). The defect site is
`harness/planner/plan_validator.py:31` `_is_module_creating`; its caller is `validate_plan` at
`:164` (do NOT edit the caller — the fix is wholly inside `_is_module_creating`). `Path` is already
imported from `pathlib` at the module top.

# Non-Goals

Do NOT change `_is_module_creating`'s signature or its caller `validate_plan`. Do NOT thread a
`repo_root` parameter through `validate_plan` (multiple call sites; out of scope). Do NOT touch
`_is_wiring_oracle`, the pure-edit type set, or any other symbol in the file. Do NOT weaken the rule
for genuinely new files or external-repo paths (absent => still module-creating). Do NOT author or
modify tests (oracles pre-committed). No integration test — the change is exercised by the existing
planner pipeline.

# Deliverables

EDIT `harness/planner/plan_validator.py`: existence-aware `_is_module_creating`. Turns
`tests/planner/test_module_creating_existing_edit.py` GREEN while
`tests/planner/test_missing_wiring_oracle.py` stays GREEN, with zero regressions in the planner
suite.
