"""RED oracle: validate_plan must reject a non-harness_self_fix task that lists a
_SENSITIVE_APPLY_GLOBS path in files_touched (HANDOFF §2).

Contract for the files-touched-sensitive-guard leaf: such a task can NEVER commit
that path (_enforce_apply_scope refuses it at accept), so the plan must be rejected
at planning time with a clear `sensitive_files_touched` violation instead of
dead-ending at accept with auto_commit_failed retries. A `harness_self_fix` task
listing a sensitive path is untouched (it commits via the decision file). The
sensitive globs are harness/**, config/**, scripts/**, services/**.

We assert specifically on the presence/absence of the `sensitive_files_touched` code
so the test is robust to any other unrelated violations the plan may carry.
"""
from harness.planner.plan_validator import validate_plan


def _task(*, files, mtt="data_model"):
    return {
        "task_id": "SFT_GUARD_1",
        "title": "a task listing a sensitive path",
        "meta_task_type": mtt,
        "priority": 1,
        "dependencies": [],
        "files_touched": files,
        "acceptance_criteria": ["lands"],
        "spec_author": "test",
        "estimated_complexity": "S",
        "verification_command": "python -m pytest tests/autocompiler/test_foo.py -q",
    }


def _codes(task):
    return {v.code for v in validate_plan({"plan_kind": "implementation", "tasks": [task]})}


def test_data_model_task_listing_config_path_is_rejected():
    # The observed ac-selection / ac-fitness-vector trap: planner copied a
    # registration-only config path into files_touched.
    assert "sensitive_files_touched" in _codes(
        _task(files=["autocompiler/selection.py", "config/autocompiler.yaml"]))


def test_each_sensitive_glob_is_caught():
    for path in ("harness/foo.py", "config/foo.yaml", "scripts/foo.sh", "services/foo.py"):
        assert "sensitive_files_touched" in _codes(_task(files=[path])), path


def test_harness_self_fix_task_with_sensitive_path_is_untouched():
    assert "sensitive_files_touched" not in _codes(
        _task(files=["harness/planner/plan_validator.py"], mtt="harness_self_fix"))


def test_free_paths_are_untouched():
    assert "sensitive_files_touched" not in _codes(
        _task(files=["autocompiler/selection.py", "tests/autocompiler/test_foo.py"]))
