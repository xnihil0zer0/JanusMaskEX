"""RED oracle for the plan-validation wiring requirement
(epic: wire_up_phase, leaf: wiring-oracle-plan-validation).

Contract: a leaf that creates a NEW module must declare a WIRING oracle, or
validate_plan emits a `missing_wiring_oracle` violation pre-spawn. A wiring oracle is
recognised by its verification_command naming a `*_wired` test (the convention the
classifier keys on). A module-creating leaf whose only test is an isolated unit test
(no `_wired` oracle) is rejected; one that declares a wiring oracle passes the check.

We assert specifically on the presence/absence of the `missing_wiring_oracle` code so
the test is robust to any other unrelated violations the plan may carry.
"""
from harness.planner.plan_validator import validate_plan


def _task(*, vcmd, files):
    return {
        "task_id": "WUP_PV_1",
        "title": "create a new module",
        "meta_task_type": "harness_plumbing",
        "priority": 1,
        "dependencies": [],
        "files_touched": files,
        "acceptance_criteria": ["module exists", "wired into a live importer"],
        "spec_author": "test",
        "estimated_complexity": "S",
        "verification_command": vcmd,
    }


def _plan(task):
    return {"plan_kind": "implementation", "tasks": [task]}


def _codes(violations):
    return {v.code for v in violations}


def test_new_module_without_wiring_oracle_is_rejected():
    task = _task(
        vcmd="python -m pytest tests/harness/test_newmod.py -q",   # isolated unit test only
        files=["harness/newmod.py"],
    )
    assert "missing_wiring_oracle" in _codes(validate_plan(_plan(task)))


def test_new_module_with_wiring_oracle_passes_the_check():
    task = _task(
        vcmd="python -m pytest tests/harness/test_newmod_wired.py -q",  # declares a wiring oracle
        files=["harness/newmod.py"],
    )
    assert "missing_wiring_oracle" not in _codes(validate_plan(_plan(task)))


def test_pure_edit_leaf_not_required_to_have_wiring_oracle():
    # Editing an existing module (no new .py created) does not trigger the requirement.
    task = _task(
        vcmd="python -m pytest tests/harness/test_orchestrator.py -q",
        files=["harness/orchestrator.py"],
    )
    task["meta_task_type"] = "refactor"
    assert "missing_wiring_oracle" not in _codes(validate_plan(_plan(task)))
