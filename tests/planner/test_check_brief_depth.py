"""Oracle for Brief 14: check_brief_depth + parent_epic belt-and-suspenders.

RED on HEAD: ``harness.depth_validator`` only knows ``check_true_depth``, which
walks ``parent_task``/``parent_task_id`` across *task* JSON. The hierarchical
planner's recursing chain is *briefs*: an epic plan record
(``plan_hooks_<epic>.json``, ``plan_kind='epic'``) lists ``child_slugs`` and its
own ``epic_slug``, optionally a ``parent_epic_slug``. Brief 14 (pulled forward
from Level 2) bounds runaway decomposition by walking that brief lineage with a
new ``check_brief_depth(slug, repo_root, max_depth)``. As cheap insurance it also
teaches ``check_true_depth`` to honor a ``parent_epic`` key in task JSON. Neither
exists yet, so this module errors on HEAD.
"""
from __future__ import annotations

import json

from harness.depth_validator import check_brief_depth, check_true_depth


def _epic_record(epic_slug, child_slugs, parent_epic_slug=None):
    rec = {"plan_kind": "epic", "epic": True, "epic_slug": epic_slug,
           "child_slugs": list(child_slugs)}
    if parent_epic_slug is not None:
        rec["parent_epic_slug"] = parent_epic_slug
    return rec


def _write_epic(repo_root, epic_slug, child_slugs, parent_epic_slug=None):
    p = repo_root / f"plan_hooks_{epic_slug}.json"
    p.write_text(json.dumps(_epic_record(epic_slug, child_slugs, parent_epic_slug)))
    return p


# ---------------------------------------------------------------------------
# check_brief_depth — walks the brief lineage reconstructed from epic records
# ---------------------------------------------------------------------------

def test_root_epic_within_budget(tmp_path):
    _write_epic(tmp_path, "A", ["B"])
    # A has no parent => depth 0 => within any positive budget.
    assert check_brief_depth("A", tmp_path, 4) is True


def test_direct_child_depth_one(tmp_path):
    _write_epic(tmp_path, "A", ["B"])
    # B's parent is A (one edge) => depth 1.
    assert check_brief_depth("B", tmp_path, 4) is True
    assert check_brief_depth("B", tmp_path, 1) is True
    assert check_brief_depth("B", tmp_path, 0) is False


def test_grandchild_exceeds_budget(tmp_path):
    # A -> B (B is itself an epic) -> C : C's lineage depth is 2.
    _write_epic(tmp_path, "A", ["B"])
    _write_epic(tmp_path, "B", ["C"])
    assert check_brief_depth("C", tmp_path, 2) is True
    assert check_brief_depth("C", tmp_path, 1) is False


def test_unknown_slug_is_within_budget(tmp_path):
    _write_epic(tmp_path, "A", ["B"])
    # A slug with no parent edge anywhere => depth 0 => True.
    assert check_brief_depth("orphan", tmp_path, 4) is True


def test_explicit_parent_epic_slug_edge_walked(tmp_path):
    # An epic that declares parent_epic_slug contributes an upward edge even
    # when no other record lists it as a child.
    _write_epic(tmp_path, "B", ["C"], parent_epic_slug="A")
    assert check_brief_depth("B", tmp_path, 1) is True
    assert check_brief_depth("B", tmp_path, 0) is False


def test_cycle_returns_false(tmp_path):
    # Mutually-referential epics must not hang and must report a violation.
    _write_epic(tmp_path, "A", ["B"], parent_epic_slug="B")
    _write_epic(tmp_path, "B", ["A"], parent_epic_slug="A")
    assert check_brief_depth("A", tmp_path, 4) is False


def test_bad_slug_input_false(tmp_path):
    assert check_brief_depth("", tmp_path, 4) is False
    assert check_brief_depth(None, tmp_path, 4) is False


def test_non_epic_plan_records_ignored(tmp_path):
    # A leaf plan_hooks (no plan_kind='epic') must not create lineage edges.
    (tmp_path / "plan_hooks_leaf.json").write_text(json.dumps({"tasks": []}))
    assert check_brief_depth("leaf", tmp_path, 4) is True


# ---------------------------------------------------------------------------
# check_true_depth belt-and-suspenders: honor a parent_epic key too
# ---------------------------------------------------------------------------

def _write_task(tasks_dir, tid, **fields):
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / f"{tid}.json").write_text(json.dumps({"task_id": tid, **fields}))


def test_check_true_depth_honors_parent_epic(tmp_path):
    tasks = tmp_path / "tasks"
    _write_task(tasks, "child", parent_epic="parent")
    _write_task(tasks, "parent")  # no parent => chain terminates
    # depth(child)=2: child -> parent. Within max_depth=3.
    assert check_true_depth("child", tasks, max_depth=3) is True
    # max_depth=1 must reject the 2-deep lineage.
    assert check_true_depth("child", tasks, max_depth=1) is False


def test_check_true_depth_parent_task_still_preferred(tmp_path):
    # Existing parent_task lookup is unchanged and takes precedence.
    tasks = tmp_path / "tasks"
    _write_task(tasks, "c", parent_task="p", parent_epic="ignored_when_parent_task_present")
    _write_task(tasks, "p")
    assert check_true_depth("c", tasks, max_depth=3) is True


def test_check_true_depth_no_parent_keys_is_root(tmp_path):
    tasks = tmp_path / "tasks"
    _write_task(tasks, "solo")
    assert check_true_depth("solo", tasks, max_depth=3) is True
