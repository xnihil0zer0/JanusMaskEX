"""RED oracle: _is_module_creating must not treat an EDIT of an EXISTING module as
module-creating (HANDOFF §3).

Contract for the validator-existing-edit leaf: a task whose non-test .py
files_touched ALL already exist on disk (resolved against the repo root) is an EDIT,
not a module creation, and must NOT be flagged `missing_wiring_oracle` when its
verification_command lacks a *_wired test. A task touching at least one non-test .py
that does NOT exist on disk is still module-creating (fail-safe: unknown/absent =>
creating, so external working_dir builds keep today's behavior).

We assert specifically on the presence/absence of the `missing_wiring_oracle` code so
the test is robust to any other unrelated violations the plan may carry.
"""
from harness.planner.plan_validator import validate_plan, _is_module_creating

EXISTING = "harness/planner/plan_normalizer.py"          # tracked, exists on disk
NEW = "harness/planner/zz_definitely_not_existing_module.py"   # does not exist


def _task(*, files, vcmd="python -m pytest tests/planner/test_plan_normalizer.py -q"):
    return {
        "task_id": "HSF_EDIT_1",
        "title": "edit an existing planner module",
        "meta_task_type": "harness_self_fix",
        "priority": 1,
        "dependencies": [],
        "files_touched": files,
        "acceptance_criteria": ["edit lands", "suite green"],
        "spec_author": "test",
        "estimated_complexity": "S",
        "verification_command": vcmd,
    }


def _codes(task):
    return {v.code for v in validate_plan({"plan_kind": "implementation", "tasks": [task]})}


def test_edit_of_existing_module_not_flagged():
    assert "missing_wiring_oracle" not in _codes(_task(files=[EXISTING]))


def test_new_module_still_flagged():
    assert "missing_wiring_oracle" in _codes(_task(files=[NEW]))


def test_mixed_new_and_existing_still_flagged():
    assert "missing_wiring_oracle" in _codes(_task(files=[EXISTING, NEW]))


def test_is_module_creating_consults_disk():
    assert _is_module_creating(_task(files=[EXISTING])) is False
    assert _is_module_creating(_task(files=[NEW])) is True


def test_pure_edit_types_still_exempt_regardless_of_existence():
    t = _task(files=[NEW])
    t["meta_task_type"] = "refactor"
    assert _is_module_creating(t) is False
