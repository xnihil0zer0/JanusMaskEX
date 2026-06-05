"""Oracle for Brief 5: validate_child_brief_plan — the BRIEF-schema sibling of
validate_plan.

RED on HEAD: harness.planner.plan_validator has no validate_child_brief_plan.

An epic decomposition emits a plan whose payload is `child_briefs` (a list of
child-brief dicts), NOT leaf tasks. This validator enforces the brief schema
(slug + the five required sections, optional dependencies/interfaces) and must
NOT require any leaf-task field (meta_task_type / files_touched / test_spec /
token_budget_ratio …) — wiring it into validate_plan's leaf list would break
every existing task.
"""
from __future__ import annotations

from harness.planner.plan_validator import validate_child_brief_plan


def _codes(violations) -> set[str]:
    return {v.code for v in violations}


def _child(slug="child_1", **over) -> dict:
    base = dict(
        slug=slug,
        title=f"{slug} title",
        scope="do the thing",
        non_goals="not that thing",
        inputs="some inputs",
        deliverables="a deliverable",
    )
    base.update(over)
    return base


def _plan(*children) -> dict:
    return {"plan_kind": "epic", "child_briefs": list(children)}


# ---- happy path ----------------------------------------------------------

def test_valid_single_child_no_violations() -> None:
    assert validate_child_brief_plan(_plan(_child())) == []


def test_valid_two_children_with_dependency() -> None:
    plan = _plan(
        _child("child_1"),
        _child("child_2", dependencies=["child_1"], interfaces="x.py exposes f()"),
    )
    assert validate_child_brief_plan(plan) == []


def test_child_brief_does_not_need_leaf_task_fields() -> None:
    # The crux: a child brief carries NONE of the leaf schema and must still pass.
    child = _child()
    for leaf_only in ("meta_task_type", "files_touched", "test_spec", "token_budget_ratio"):
        assert leaf_only not in child
    assert validate_child_brief_plan(_plan(child)) == []


# ---- structural ----------------------------------------------------------

def test_non_dict_plan_is_invalid_structure() -> None:
    assert "invalid_structure" in _codes(validate_child_brief_plan(["not", "a", "dict"]))


def test_child_briefs_not_a_list_is_invalid_structure() -> None:
    assert "invalid_structure" in _codes(validate_child_brief_plan({"child_briefs": {}}))


def test_empty_child_briefs_flagged() -> None:
    # An epic that decomposes to zero children is degenerate.
    assert "empty_child_briefs" in _codes(validate_child_brief_plan({"child_briefs": []}))


def test_child_entry_not_dict_is_invalid_structure() -> None:
    assert "invalid_structure" in _codes(validate_child_brief_plan({"child_briefs": ["x"]}))


# ---- per-child brief schema ----------------------------------------------

def test_missing_required_section_flagged() -> None:
    bad = _child()
    del bad["scope"]
    assert "missing_field" in _codes(validate_child_brief_plan(_plan(bad)))


def test_missing_slug_flagged() -> None:
    bad = _child()
    del bad["slug"]
    codes = _codes(validate_child_brief_plan(_plan(bad)))
    assert "missing_field" in codes or "invalid_slug" in codes


def test_empty_slug_is_invalid() -> None:
    assert "invalid_slug" in _codes(validate_child_brief_plan(_plan(_child(slug="  "))))


def test_non_string_slug_is_invalid() -> None:
    assert "invalid_slug" in _codes(validate_child_brief_plan(_plan(_child(slug=7))))


def test_duplicate_slug_flagged() -> None:
    plan = _plan(_child("dup"), _child("dup"))
    assert "duplicate_slug" in _codes(validate_child_brief_plan(plan))


# ---- optional fields -----------------------------------------------------

def test_dependencies_must_be_list() -> None:
    bad = _child("child_2", dependencies="child_1")
    assert "invalid_dependencies" in _codes(validate_child_brief_plan(_plan(_child("child_1"), bad)))


def test_dependency_on_unknown_sibling_flagged() -> None:
    bad = _child("child_2", dependencies=["nonexistent"])
    assert "unknown_dependency" in _codes(validate_child_brief_plan(_plan(_child("child_1"), bad)))


def test_interfaces_must_be_string() -> None:
    bad = _child(interfaces=["not", "a", "string"])
    assert "invalid_interfaces" in _codes(validate_child_brief_plan(_plan(bad)))


def test_valid_dependency_on_existing_sibling_ok() -> None:
    plan = _plan(_child("a"), _child("b", dependencies=["a"]))
    assert validate_child_brief_plan(plan) == []
