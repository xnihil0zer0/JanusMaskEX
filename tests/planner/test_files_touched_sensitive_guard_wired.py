"""Wiring oracle for the files-touched-sensitive-guard leaf (*_wired requirement).

The edit target harness/planner/plan_validator.py is an existing module reached from
the live planner entrypoint; this asserts it stays wired and that the new guard is
reachable as a module-level symbol invoked by validate_plan.
"""
import inspect
from pathlib import Path

from harness.wire_up import check_wired


def test_plan_validator_is_wired():
    repo_root = Path(__file__).resolve().parents[2]
    res = check_wired(repo_root, 'harness/planner/plan_validator.py')
    assert res.wired, res.reason


def test_guard_invoked_by_validate_plan():
    from harness.planner.plan_validator import validate_plan, _sensitive_glob_violations
    assert callable(_sensitive_glob_violations)
    assert '_sensitive_glob_violations(' in inspect.getsource(validate_plan), (
        'validate_plan must call the new guard (wiring-asserting oracle)')
