"""Wiring oracle for the validator-existing-edit leaf (*_wired requirement).

The edit target harness/planner/plan_validator.py is an existing module reached from
the live planner entrypoint; this asserts it stays wired after the edit.
"""
from pathlib import Path

from harness.wire_up import check_wired


def test_plan_validator_is_wired():
    repo_root = Path(__file__).resolve().parents[2]
    res = check_wired(repo_root, 'harness/planner/plan_validator.py')
    assert res.wired, res.reason


def test_is_module_creating_importable():
    from harness.planner.plan_validator import _is_module_creating
    assert callable(_is_module_creating)
