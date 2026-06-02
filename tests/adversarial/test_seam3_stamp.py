"""Adversarial oracle for SEAM3_STAMP (REV22 §4-1).

harness.planner.cli.persist_plan must stamp the TRUSTED working_dir from the
supplied brief_obj into the persisted plan JSON (plan['working_dir']), mirroring
the existing source_brief_* injection. Trusted source ONLY: the value must come
from brief_obj.working_dir, never from an LLM-controlled plan field.

INERT plumbing: no consumer reads plan['working_dir'] yet.

RED on HEAD: persist_plan does not stamp working_dir, so the persisted plan JSON
lacks the key and the positive-case assertion fails.
"""
import json
from pathlib import Path

import pytest

from harness.planner.cli import persist_plan
from harness.planner.brief_loader import PlanningBrief


def _make_brief(working_dir):
    return PlanningBrief(
        title="t",
        scope="s",
        non_goals="ng",
        inputs="in",
        deliverables="del",
        raw_text="raw",
        source_path="/tmp/brief.md",
        sha256="deadbeef",
        working_dir=working_dir,
    )


def test_working_dir_stamped_from_trusted_brief(tmp_path):
    """A brief with working_dir set -> persisted plan JSON carries it (trusted source)."""
    out = tmp_path / "planning" / "merged_plan.json"
    plan = {"tasks": [], "schema_version": "2.1"}
    brief = _make_brief("/home/xnihil0zer0/external_project")

    persist_plan(plan, out, brief_obj=brief)

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written.get("working_dir") == "/home/xnihil0zer0/external_project", (
        "persist_plan must stamp the trusted brief_obj.working_dir into the plan JSON"
    )


def test_working_dir_absent_when_brief_has_none(tmp_path):
    """A brief with working_dir=None -> key absent (or None) in persisted plan JSON."""
    out = tmp_path / "planning" / "merged_plan.json"
    plan = {"tasks": [], "schema_version": "2.1"}
    brief = _make_brief(None)

    persist_plan(plan, out, brief_obj=brief)

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written.get("working_dir") is None, (
        "no working_dir on the brief -> the plan JSON must not gain a non-None working_dir"
    )


def test_working_dir_not_taken_from_llm_plan_field_when_no_brief(tmp_path):
    """No brief_obj -> persist_plan must not invent/stamp a working_dir.

    Guards the trusted-source rule: an LLM-controlled plan that already contains
    a working_dir must not be 'blessed' by persist_plan when there is no trusted
    brief value. (Idempotent passthrough is acceptable, but persist_plan must not
    fabricate one.)
    """
    out = tmp_path / "planning" / "merged_plan.json"
    plan = {"tasks": []}

    persist_plan(plan, out, brief_obj=None)

    written = json.loads(out.read_text(encoding="utf-8"))
    assert "working_dir" not in written, (
        "with no trusted brief_obj, persist_plan must not stamp a working_dir"
    )
