"""Wiring oracle for the planner-strip-unresolvable-deps leaf (*_wired requirement).

The edit target harness/planner/plan_normalizer.py is an existing module reached
from the live planner entrypoint; this asserts it stays wired and that the new
pass is reachable as a module-level symbol invoked by normalize_plan.
"""
import inspect
from pathlib import Path

from harness.wire_up import check_wired


def test_plan_normalizer_is_wired():
    repo_root = Path(__file__).resolve().parents[2]
    res = check_wired(repo_root, 'harness/planner/plan_normalizer.py')
    assert res.wired, res.reason


def test_strip_pass_invoked_by_normalize_plan():
    from harness.planner.plan_normalizer import normalize_plan, _strip_unresolvable_dependencies
    assert callable(_strip_unresolvable_dependencies)
    assert '_strip_unresolvable_dependencies(' in inspect.getsource(normalize_plan), (
        'normalize_plan must call the new pass (wiring-asserting oracle)')
