"""Adversarial bar for autowork_unfinished_work_tag.

These tests are xfail-strict until the dispatch lands the NEW top-level
function `compute_autowork_backlog(repo_root, state_dir, now=None,
max_age_sec=604800)` in `harness/brief_status.py`. On accept, drop the
xfail markers (or flip to non-xfail) so they become regression guards.
They assert the same invariants the task's verification_command checks,
but split into discrete pytest cases.

The new function must be PURELY ADDITIVE: the pre-existing
`compute_brief_status` and `compute_autowork_eligibility` functions must
remain present and callable with their original return shapes.
"""

from __future__ import annotations

import ast
import importlib
import pathlib

import pytest

BRIEF_STATUS_PATH = (
    pathlib.Path(__file__).resolve().parents[2] / "harness" / "brief_status.py"
)


def _module_tree() -> ast.Module:
    src = BRIEF_STATUS_PATH.read_text()
    return ast.parse(src)


def _top_level_function_names(tree: ast.Module) -> set[str]:
    return {
        node.name
        for node in ast.iter_child_nodes(tree)
        if isinstance(node, ast.FunctionDef)
    }


def _function_def_by_name(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _make_fixture(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """One recent unplanned brief + an allowlist that admits it.

    REPL-1/G-EMPTYALLOW: a missing allowlist is now DENY-ALL, so the fixture
    must explicitly allowlist ``demo`` for it to count as eligible-with-work.
    """
    (tmp_path / "brief_hooks_demo.md").write_text("# Title\ndemo\n")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    aw = state_dir / "control" / "autowork"
    aw.mkdir(parents=True)
    (aw / "auto_promote.allowlist").write_text("demo\n", encoding="utf-8")
    return tmp_path, state_dir


def test_compute_autowork_backlog_defined_as_top_level_function():
    tree = _module_tree()
    node = _function_def_by_name(tree, "compute_autowork_backlog")
    assert node is not None, (
        "compute_autowork_backlog not found as a top-level ast.FunctionDef "
        "in harness/brief_status.py"
    )
    arg_names = [a.arg for a in node.args.args]
    assert arg_names[:2] == ["repo_root", "state_dir"]
    assert "now" in arg_names
    assert "max_age_sec" in arg_names


def test_compute_autowork_backlog_return_shape_has_three_keys(tmp_path):
    from harness import brief_status as bs

    importlib.reload(bs)
    assert hasattr(bs, "compute_autowork_backlog"), (
        "harness.brief_status.compute_autowork_backlog missing — not yet dispatched"
    )
    root, state_dir = _make_fixture(tmp_path)
    res = bs.compute_autowork_backlog(root, state_dir)
    assert isinstance(res, dict)
    assert set(res.keys()) >= {"eligible_with_work", "eligible_without_work", "detail"}
    assert isinstance(res["eligible_with_work"], list)
    assert isinstance(res["eligible_without_work"], list)
    assert isinstance(res["detail"], list)


def test_unplanned_eligible_brief_tagged_has_unfinished_work_true(tmp_path):
    from harness import brief_status as bs

    importlib.reload(bs)
    assert hasattr(bs, "compute_autowork_backlog"), (
        "harness.brief_status.compute_autowork_backlog missing — not yet dispatched"
    )
    root, state_dir = _make_fixture(tmp_path)
    res = bs.compute_autowork_backlog(root, state_dir)
    # The lone brief is unplanned (no plan_hooks_demo.json) => unfinished work.
    assert "demo" in res["eligible_with_work"]
    assert "demo" not in res["eligible_without_work"]
    demo_rows = [r for r in res["detail"] if r["slug"] == "demo"]
    assert len(demo_rows) == 1
    assert demo_rows[0]["has_unfinished_work"] is True
    assert demo_rows[0]["state"] == "unplanned"


def test_detail_covers_all_eligible_briefs_with_required_keys(tmp_path):
    from harness import brief_status as bs

    importlib.reload(bs)
    assert hasattr(bs, "compute_autowork_backlog"), (
        "harness.brief_status.compute_autowork_backlog missing — not yet dispatched"
    )
    root, state_dir = _make_fixture(tmp_path)
    eligibility = bs.compute_autowork_eligibility(root, state_dir)
    res = bs.compute_autowork_backlog(root, state_dir)
    # detail covers every eligible brief.
    assert len(res["detail"]) == eligibility["eligible_count"]
    detail_slugs = {r["slug"] for r in res["detail"]}
    assert detail_slugs == set(eligibility["eligible"])
    for row in res["detail"]:
        assert set(row.keys()) >= {"slug", "has_unfinished_work", "state"}
        assert isinstance(row["slug"], str)
        assert isinstance(row["has_unfinished_work"], bool)
        assert isinstance(row["state"], str)


def test_with_plus_without_work_partitions_eligible_set(tmp_path):
    from harness import brief_status as bs

    importlib.reload(bs)
    assert hasattr(bs, "compute_autowork_backlog"), (
        "harness.brief_status.compute_autowork_backlog missing — not yet dispatched"
    )
    root, state_dir = _make_fixture(tmp_path)
    eligibility = bs.compute_autowork_eligibility(root, state_dir)
    res = bs.compute_autowork_backlog(root, state_dir)
    with_work = set(res["eligible_with_work"])
    without_work = set(res["eligible_without_work"])
    # The two buckets are disjoint and together equal the eligible set.
    assert with_work.isdisjoint(without_work)
    assert (with_work | without_work) == set(eligibility["eligible"])


def test_existing_two_functions_preserved_and_additive_only():
    tree = _module_tree()
    names = _top_level_function_names(tree)
    # Both pre-existing functions must remain present (byte-preserved, additive-only).
    assert "compute_brief_status" in names
    assert "compute_autowork_eligibility" in names
    # And the new function must coexist (gates the xfail->pass transition).
    assert "compute_autowork_backlog" in names

    # No class / __all__ should have been introduced.
    classes = [n for n in ast.iter_child_nodes(tree) if isinstance(n, ast.ClassDef)]
    assert classes == [], f"no ClassDef expected in brief_status.py; found {classes!r}"
    assign_names = {
        t.id
        for n in ast.iter_child_nodes(tree)
        if isinstance(n, ast.Assign)
        for t in n.targets
        if isinstance(t, ast.Name)
    }
    assert "__all__" not in assign_names

    # The two existing functions are still importable and callable.
    from harness import brief_status as bs

    importlib.reload(bs)
    assert callable(bs.compute_brief_status)
    assert callable(bs.compute_autowork_eligibility)
    assert callable(bs.compute_autowork_backlog)
