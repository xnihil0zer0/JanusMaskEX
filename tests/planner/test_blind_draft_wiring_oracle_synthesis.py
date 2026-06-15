"""Oracle: blind_draft.collect_agent_draft deterministically synthesizes a
wiring-oracle token for module-creating leaves before validation.

ROOT CAUSE (RED on HEAD): a leaf that creates a NEW module must name a
``*_wired`` test in its ``verification_command`` or plan_validator raises
``missing_wiring_oracle``. The blind planning agents only emit that token
nondeterministically, and ``collect_agent_draft`` validates the RAW draft
PRE-normalization, so a perfectly good module-creating draft that simply omits
the token is discarded -> both agents fail -> ``planner_hallucination_discarded``
-> the leaf can never be planned. (Observed live: srcdrive_payload_bank, Leaf 4a.)

FIX: before validating, append a COMMENTED wiring-oracle token
(`` # tests/test_<stem>_wired.py``) to each module-creating leaf's vcmd that
lacks one and has no paired test_authoring oracle. The shell treats everything
after ``#`` as a comment (pytest never sees it); the authoritative reachability
enforcement remains the orchestrator's ``_run_wire_up_gate`` (which no-ops for
external-rootless targets and enforces orphan_unwired for rooted ones). This
makes the planner deterministically satisfy its OWN requirement.

The fix lives ONLY in blind_draft (NOT validate_plan), so the direct
plan_validator contract — including ``missing_wiring_oracle`` on a raw
module-creating task — is byte-for-byte unchanged.
"""
from __future__ import annotations

import json

import pytest

from harness.planner import blind_draft as bd


def _full_task(*, files, vcmd, meta="data_model", extra=None):
    t = {
        "task_id": "t1",
        "title": "make a new module",
        "meta_task_type": meta,
        "priority": "medium",
        "dependencies": [],
        "files_touched": files,
        "acceptance_criteria": ["lands"],
        "spec_author": None,
        "estimated_complexity": "low",
        "verification_command": vcmd,
        "spec": {
            "objective": "o",
            "functional_requirements": ["a"],
            "interfaces": "i",
            "edge_cases": ["e"],
            "non_goals": ["integration"],
            "implementation_notes": "n",
        },
        "test_spec": {
            "unit_tests": [{"name": "u"}],
            "integration_tests": [],
            "property_tests": [],
            "regression_tests": [{"name": "r1"}, {"name": "r2"}],
            "minimum_test_count": 2,
            "test_data_requirements": "none",
        },
        "token_budget_ratio": {"implementation_tokens": 100, "test_tokens": 200, "note": "n"},
        "attribution_metadata": {"proposed_by": "agent", "reconciled": False, "diff_resolution": ""},
    }
    if extra:
        t.update(extra)
    return t


def _write_draft(agent_dir, agent, draft):
    d = agent_dir / "planning" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{agent}_draft.json").write_text(json.dumps(draft), encoding="utf-8")


def _collect(agent_dir, state_dir, working_dir):
    return bd.collect_agent_draft(
        "claude", agent_dir, state_dir, elapsed=100.0, timeout=200.0,
        spawn_start_epoch=None, working_dir=working_dir,
    )


# ---- the fix: module-creating leaf w/o wiring oracle is ACCEPTED ----------

def test_module_creating_leaf_gets_synthesized_token(tmp_path):
    ext = tmp_path / "ExternalRepo"
    (ext / "pkg").mkdir(parents=True)            # pkg/ exists, brand_new.py absent
    ad = tmp_path / "ad"
    draft = {"working_dir": str(ext), "tasks": [
        _full_task(files=["pkg/brand_new.py"],
                   vcmd="python -m pytest tests/test_brand_new.py -q")]}
    _write_draft(ad, "claude", draft)
    out, status = _collect(ad, tmp_path, str(ext))
    assert status == "ok" and out is not None
    vcmd = out["tasks"][0]["verification_command"]
    assert "_wired" in vcmd, vcmd
    # the real (pre-#) command is untouched
    assert vcmd.split("#")[0].strip() == "python -m pytest tests/test_brand_new.py -q"


def test_synthesized_token_is_commented_out(tmp_path):
    ext = tmp_path / "ExternalRepo"
    (ext / "pkg").mkdir(parents=True)
    ad = tmp_path / "ad"
    draft = {"working_dir": str(ext), "tasks": [
        _full_task(files=["pkg/brand_new.py"],
                   vcmd="python -m pytest tests/test_brand_new.py -q")]}
    _write_draft(ad, "claude", draft)
    out, _ = _collect(ad, tmp_path, str(ext))
    assert "# " in out["tasks"][0]["verification_command"]


# ---- anti-regression: do NOT touch non-creating / already-wired / paired ---

def test_edit_leaf_vcmd_unchanged(tmp_path):
    ext = tmp_path / "ExternalRepo"
    (ext / "pkg").mkdir(parents=True)
    (ext / "pkg" / "existing.py").write_text("x = 1\n")   # exists -> edit, not creating
    ad = tmp_path / "ad"
    draft = {"working_dir": str(ext), "tasks": [
        _full_task(files=["pkg/existing.py"], meta="io_adapter",
                   vcmd="python -m pytest tests/test_existing.py -q")]}
    _write_draft(ad, "claude", draft)
    out, status = _collect(ad, tmp_path, str(ext))
    assert status == "ok"
    assert out["tasks"][0]["verification_command"] == "python -m pytest tests/test_existing.py -q"


def test_already_wired_vcmd_not_double_tokened(tmp_path):
    ext = tmp_path / "ExternalRepo"
    (ext / "pkg").mkdir(parents=True)
    ad = tmp_path / "ad"
    draft = {"working_dir": str(ext), "tasks": [
        _full_task(files=["pkg/brand_new.py"],
                   vcmd="python -m pytest tests/test_brand_new_wired.py -q")]}
    _write_draft(ad, "claude", draft)
    out, status = _collect(ad, tmp_path, str(ext))
    assert status == "ok"
    # exactly one occurrence of _wired (no duplication)
    assert out["tasks"][0]["verification_command"].count("_wired") == 1
