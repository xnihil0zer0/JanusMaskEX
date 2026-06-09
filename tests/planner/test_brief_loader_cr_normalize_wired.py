"""Wiring oracle for the brief-loader-cr-normalize leaf (*_wired requirement).

The edit target harness/planner/brief_loader.py is an existing module reached from
the live planner entrypoint; this asserts it stays wired after the edit.
"""
from pathlib import Path

from harness.wire_up import check_wired


def test_brief_loader_is_wired():
    repo_root = Path(__file__).resolve().parents[2]
    res = check_wired(repo_root, 'harness/planner/brief_loader.py')
    assert res.wired, res.reason


def test_load_brief_importable():
    from harness.planner.brief_loader import load_brief
    assert callable(load_brief)
