"""Oracle for Brief 13: validate_plan epic dispatch + validate_epic_plan.

RED on HEAD: validate_plan only knows the leaf-task schema. A persisted epic
plan record (the ``plan_hooks_<epic>.json`` written by ``_run_epic_pipeline`` —
``plan_kind='epic'``, ``child_briefs``, ``child_slugs``, ``epic_slug``) has no
``tasks`` and no per-task ``task_id``/``title``/... fields, so today it would
drown in spurious leaf ``missing_field`` violations. Per
``area_B_verified.md`` / PHASE1 Brief 13, ``validate_plan`` must discriminate on
``plan.get('plan_kind')``: an epic record routes to a new ``validate_epic_plan``
that enforces the epic-record schema (reusing the brief-schema checks); any
plan WITHOUT ``plan_kind == 'epic'`` (the 5 existing leaf callers) keeps the
unchanged leaf behavior. ``validate_epic_plan`` does not exist yet, so this
module fails to import / errors on HEAD.
"""
from __future__ import annotations

import json

import pytest

from harness.planner.plan_validator import validate_plan, validate_epic_plan


# ---------------------------------------------------------------------------
# Fixtures: well-formed epic record + well-formed leaf plan
# ---------------------------------------------------------------------------

def _good_child(slug: str) -> dict:
    return {
        "slug": slug,
        "title": f"Title {slug}",
        "scope": "do the thing",
        "non_goals": "not that thing",
        "inputs": "the inputs",
        "deliverables": "the deliverables",
    }


def _good_epic_record() -> dict:
    children = [_good_child("alpha"), _good_child("beta")]
    return {
        "plan_kind": "epic",
        "epic": True,
        "child_briefs": children,
        "child_slugs": ["alpha", "beta"],
        "epic_slug": "my_epic",
    }


def _good_leaf_task() -> dict:
    return {
        "task_id": "t1",
        "title": "Leaf task",
        "meta_task_type": "refactor",
        "priority": "medium",
        "dependencies": [],
        "files_touched": ["a.py"],
        "acceptance_criteria": ["works"],
        "spec_author": None,
        "estimated_complexity": "low",
        "verification_command": "pytest -q",
        "spec": {
            "objective": "o",
            "functional_requirements": ["fr1"],
            "interfaces": "i",
            "edge_cases": [],
            "non_goals": ["no integration: integration excused"],
            "implementation_notes": "n",
        },
        "test_spec": {
            "unit_tests": [{"name": "u1"}],
            "integration_tests": [],
            "property_tests": [],
            "regression_tests": [],
            "minimum_test_count": 2,
            "test_data_requirements": "none",
        },
        "token_budget_ratio": {
            "implementation_tokens": 100,
            "test_tokens": 200,
            "note": "n",
        },
        "attribution_metadata": {
            "proposed_by": "operator",
            "reconciled": False,
            "diff_resolution": None,
        },
    }


# ---------------------------------------------------------------------------
# validate_plan routing
# ---------------------------------------------------------------------------

def test_validate_plan_routes_wellformed_epic_to_no_violations():
    # A well-formed epic record must come back clean through validate_plan.
    assert validate_plan(_good_epic_record()) == []


def test_validate_plan_epic_record_produces_no_leaf_missing_field_codes():
    # The decisive routing proof: an epic record must NOT be judged against the
    # leaf-task schema (no task_id/title/meta_task_type/... missing_field spam).
    epic = _good_epic_record()
    # Even a deliberately leaf-incompatible epic record routes away from leaf.
    epic["child_briefs"][0].pop("inputs")  # an epic-schema violation
    vs = validate_plan(epic)
    codes = {v.code for v in vs}
    # epic-schema violation surfaces...
    assert "missing_field" in codes
    # ...but it is about the child brief, never a leaf task path.
    assert all(not v.path.startswith("tasks[") for v in vs)


def test_validate_plan_leaf_plan_unchanged_when_valid():
    # No plan_kind => leaf path, unchanged.
    assert validate_plan({"tasks": [_good_leaf_task()]}) == []


def test_validate_plan_leaf_plan_unchanged_when_invalid():
    # An invalid leaf plan still yields the leaf violations it always did.
    bad = {"tasks": [{"task_id": "t1"}]}  # missing nearly everything
    vs = validate_plan(bad)
    assert any(v.code == "missing_field" and v.path.startswith("tasks[") for v in vs)


def test_validate_plan_missing_plan_kind_is_leaf():
    # Missing key MUST mean leaf (back-compat for all 5 callers).
    bad = {"tasks": [{"task_id": "t1"}]}
    assert "plan_kind" not in bad
    vs = validate_plan(bad)
    assert any(v.path.startswith("tasks[") for v in vs)


def test_validate_plan_plan_kind_leaf_value_is_leaf():
    # plan_kind explicitly non-epic => leaf path.
    vs = validate_plan({"plan_kind": "leaf", "tasks": [{"task_id": "t1"}]})
    assert any(v.path.startswith("tasks[") for v in vs)


def test_validate_plan_from_path_epic(tmp_path):
    # Path input carrying an epic record also routes to epic validation.
    p = tmp_path / "plan_hooks_my_epic.json"
    p.write_text(json.dumps(_good_epic_record()))
    assert validate_plan(p) == []


# ---------------------------------------------------------------------------
# validate_epic_plan direct
# ---------------------------------------------------------------------------

def test_validate_epic_plan_accepts_wellformed():
    assert validate_epic_plan(_good_epic_record()) == []


def test_validate_epic_plan_rejects_non_epic_plan_kind():
    rec = _good_epic_record()
    rec["plan_kind"] = "leaf"
    codes = {v.code for v in validate_epic_plan(rec)}
    assert "invalid_plan_kind" in codes


def test_validate_epic_plan_rejects_child_slug_mismatch():
    rec = _good_epic_record()
    rec["child_slugs"] = ["alpha", "ghost"]  # 'ghost' not among child_briefs
    codes = {v.code for v in validate_epic_plan(rec)}
    assert any("slug" in c for c in codes)


def test_validate_epic_plan_flags_malformed_child_briefs():
    rec = _good_epic_record()
    rec["child_briefs"][1].pop("deliverables")
    codes = {v.code for v in validate_epic_plan(rec)}
    assert "missing_field" in codes


def test_validate_epic_plan_non_dict_input():
    vs = validate_epic_plan(["not", "a", "dict"])
    assert vs and vs[0].code == "invalid_structure"


def test_validate_epic_plan_never_raises_on_garbage():
    # Robustness: malformed shapes return violations rather than throwing.
    for garbage in ({}, {"plan_kind": "epic"}, {"plan_kind": "epic", "child_briefs": "x"}):
        out = validate_epic_plan(garbage)
        assert isinstance(out, list)
