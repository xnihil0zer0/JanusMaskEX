"""Oracle for Brief 9: generalize diff_extractor to child briefs — a
``_compare_brief_fields`` helper plus a ``child_briefs`` path in ``extract_diff``
that matches siblings on their stable ``slug``.

RED on HEAD: ``extract_diff`` reads only ``plan['tasks']`` and matches on
``task_id``/``files_touched``. Given two epic drafts (``child_briefs`` arrays,
no ``tasks``), it sees zero tasks and returns an EMPTY ``PlanDiff`` — the
decomposition diff is invisible. And there is no ``_compare_brief_fields`` to
diff brief-level fields with the Brief-8 FieldKind members. Leaf behaviour
(``tasks`` + ``task_id`` matching) must remain byte-for-byte unchanged.
"""
from __future__ import annotations

from harness.planner.diff_extractor import _compare_brief_fields, extract_diff
from harness.planner.diff_model import DiffKind, FieldKind


def _cb(slug: str, **over) -> dict:
    base = dict(slug=slug, title="T", scope="s", non_goals="n",
                inputs="i", deliverables="d")
    base.update(over)
    return base


# ---- Part A: _compare_brief_fields ---------------------------------------

def test_identical_briefs_no_divergence() -> None:
    assert _compare_brief_fields(_cb("x"), _cb("x")) == ()


def test_scope_divergence_uses_scope_text() -> None:
    divs = _compare_brief_fields(_cb("x", scope="A"), _cb("x", scope="B"))
    assert FieldKind.scope_text in {d[0] for d in divs}


def test_per_field_divergences() -> None:
    c = _cb("x", interfaces="sig_a", dependencies=[])
    g = _cb("x", deliverables="other", inputs="other",
            interfaces="sig_b", non_goals="diff", dependencies=["y"])
    kinds = {d[0] for d in _compare_brief_fields(c, g)}
    assert FieldKind.deliverables in kinds
    assert FieldKind.inputs in kinds
    assert FieldKind.interfaces in kinds
    assert FieldKind.non_goals in kinds
    assert FieldKind.dependencies in kinds


# ---- Part B: extract_diff child_briefs path ------------------------------

def test_epic_convergent_by_slug() -> None:
    diff = extract_diff({"plan_kind": "epic", "child_briefs": [_cb("a")]},
                        {"plan_kind": "epic", "child_briefs": [_cb("a")]})
    assert len(diff.items) == 1
    assert diff.items[0].kind == DiffKind.convergent
    assert diff.items[0].match_reason == "slug"


def test_epic_divergent_by_slug() -> None:
    diff = extract_diff({"child_briefs": [_cb("a", scope="A")]},
                        {"child_briefs": [_cb("a", scope="B")]})
    assert len(diff.items) == 1
    assert diff.items[0].kind == DiffKind.divergent
    assert FieldKind.scope_text in {d[0] for d in diff.items[0].field_divergences}


def test_epic_one_sided_slugs() -> None:
    diff = extract_diff({"child_briefs": [_cb("a"), _cb("b")]},
                        {"child_briefs": [_cb("a")]})
    kinds = sorted(i.kind.value for i in diff.items)
    assert "claude_only" in kinds
    assert "convergent" in kinds
    # Brief-8 slug identity fallback => no hash collision across items
    ids = {i.diff_item_id for i in diff.items}
    assert len(ids) == len(diff.items)


def test_epic_gemini_only() -> None:
    diff = extract_diff({"child_briefs": [_cb("a")]},
                        {"child_briefs": [_cb("a"), _cb("z")]})
    assert any(i.kind == DiffKind.gemini_only for i in diff.items)


# ---- Part C: leaf back-compat --------------------------------------------

def test_leaf_path_unchanged() -> None:
    cp = {"tasks": [{"task_id": "t1", "title": "x", "files_touched": ["f.py"]}]}
    gp = {"tasks": [{"task_id": "t1", "title": "x", "files_touched": ["f.py"]}]}
    diff = extract_diff(cp, gp)
    assert len(diff.items) == 1
    assert diff.items[0].kind == DiffKind.convergent
    assert diff.items[0].match_reason == "task_id"
