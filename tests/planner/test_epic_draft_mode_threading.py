"""Oracle for Brief 6 [BLOCKER]: thread a `mode` so epic drafts are validated
with the BRIEF schema (validate_child_brief_plan) instead of the leaf schema.

RED on HEAD: there is no `validate_draft` dispatcher and `collect_agent_draft`
takes no `mode` — so epic drafts are only ever run through `validate_plan`,
which inspects `plan['tasks']` and IGNORES `plan['child_briefs']` entirely. A
MALFORMED child-brief draft (missing sections, empty, bad deps) is therefore
vacuously accepted, and the dual-model decomposition proceeds on garbage. This
is the make-or-break seam: nothing downstream (diff/reconcile/first-light) is
trustworthy until epic drafts are validated with the right schema.

Back-compat is mandatory: `validate_plan` keeps its signature (5 callers) and
the default mode is `leaf`, so every existing path is byte-for-byte unchanged.
"""
from __future__ import annotations

import json

import pytest

from harness.planner import PlanningBrief
from harness.planner import blind_draft as bd
from harness.planner.plan_validator import (
    validate_child_brief_plan,
    validate_draft,
    validate_plan,
)


# ---- fixtures: representative plans --------------------------------------

def _valid_child_brief() -> dict:
    return dict(
        slug="child_1",
        title="Child One",
        scope="do the thing",
        non_goals="not that",
        inputs="ins",
        deliverables="outs",
    )


def _valid_epic_draft() -> dict:
    return {"plan_kind": "epic", "child_briefs": [_valid_child_brief()]}


def _malformed_epic_draft() -> dict:
    # child_briefs present but each child missing every required section ->
    # validate_child_brief_plan REJECTS, validate_plan vacuously accepts.
    return {"plan_kind": "epic", "child_briefs": [{"slug": "child_1"}]}


def _empty_tasks_plan() -> dict:
    return {"tasks": []}


# ---- Part A: validate_draft dispatcher -----------------------------------

def test_validate_draft_leaf_mode_equals_validate_plan() -> None:
    for p in (_malformed_epic_draft(), _valid_epic_draft(), _empty_tasks_plan()):
        assert validate_draft(p, mode="leaf") == validate_plan(p)


def test_validate_draft_epic_mode_equals_child_validator() -> None:
    for p in (_malformed_epic_draft(), _valid_epic_draft()):
        assert validate_draft(p, mode="epic") == validate_child_brief_plan(p)


def test_validate_draft_defaults_to_leaf() -> None:
    p = _malformed_epic_draft()
    assert validate_draft(p) == validate_plan(p)


def test_validate_draft_epic_rejects_malformed_child() -> None:
    # The crux: epic mode actually validates the child briefs.
    assert validate_draft(_malformed_epic_draft(), mode="epic") != []


def test_validate_draft_leaf_now_catches_epic_shaped_draft() -> None:
    # Brief 13 SUPERSEDED the old latent bug: validate_plan now dispatches any
    # plan_kind=='epic' to validate_epic_plan, so leaf-mode no longer vacuously
    # accepts a malformed epic-shaped draft. The dispatcher's core contract —
    # validate_draft(leaf) == validate_plan — still holds (see the test above).
    assert validate_draft(_malformed_epic_draft(), mode="leaf") != []


# ---- Part B: collect_agent_draft mode threading --------------------------

def _write_draft(agent_dir, agent: str, draft: dict) -> None:
    d = agent_dir / "planning" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{agent}_draft.json").write_text(json.dumps(draft), encoding="utf-8")


def test_collect_epic_mode_rejects_malformed_child(tmp_path) -> None:
    ad = tmp_path / "ad"
    _write_draft(ad, "claude", _malformed_epic_draft())
    draft, status = bd.collect_agent_draft(
        "claude", ad, tmp_path, elapsed=100.0, timeout=200.0,
        spawn_start_epoch=None, mode="epic",
    )
    assert draft is None and status == "invalid"


def test_collect_epic_mode_accepts_valid_child(tmp_path) -> None:
    ad = tmp_path / "ad"
    _write_draft(ad, "claude", _valid_epic_draft())
    draft, status = bd.collect_agent_draft(
        "claude", ad, tmp_path, elapsed=100.0, timeout=200.0,
        spawn_start_epoch=None, mode="epic",
    )
    assert status == "ok" and draft is not None and "child_briefs" in draft


def test_collect_leaf_default_catches_epic_shaped_draft(tmp_path) -> None:
    # Brief 13: validate_plan dispatches plan_kind=='epic' to the epic validator,
    # so even the default (leaf) collect path now rejects a malformed epic-shaped
    # draft instead of vacuously accepting it (the old latent bug is fixed).
    ad = tmp_path / "ad"
    _write_draft(ad, "claude", _malformed_epic_draft())
    draft, status = bd.collect_agent_draft(
        "claude", ad, tmp_path, elapsed=100.0, timeout=200.0,
        spawn_start_epoch=None,
    )
    assert status == "invalid" and draft is None


def test_collect_leaf_default_true_leaf_draft_unchanged(tmp_path) -> None:
    # Back-compat proof preserved: a TRUE leaf draft (no plan_kind) is unaffected
    # by Brief 13 and is accepted on the default path exactly as on HEAD.
    ad = tmp_path / "ad"
    _write_draft(ad, "claude", {"tasks": []})
    draft, status = bd.collect_agent_draft(
        "claude", ad, tmp_path, elapsed=100.0, timeout=200.0,
        spawn_start_epoch=None,
    )
    assert status == "ok" and draft is not None


# ---- Part C: run_blind_drafts threads mode from brief.epic ----------------

def _brief(epic: bool) -> PlanningBrief:
    return PlanningBrief(
        title="T", scope="S", non_goals="N", inputs="I", deliverables="D",
        raw_text="raw", source_path="/tmp/b.md", sha256="0" * 64, epic=epic,
    )


def _run_with_spy(monkeypatch, tmp_path, epic: bool) -> list[str]:
    # Pre-place both draft files so run_both_agents is skipped (no real spawn).
    sess = tmp_path / "planning" / "sessions"
    sess.mkdir(parents=True, exist_ok=True)
    (sess / "claude_draft.json").write_text("{}", encoding="utf-8")
    (sess / "gemini_draft.json").write_text("{}", encoding="utf-8")
    seen: list[str] = []

    def _spy(agent, agent_dir, state_dir, elapsed, timeout,
             spawn_start_epoch=None, min_response_seconds=10.0, mode="leaf"):
        seen.append(mode)
        return ({"ok": True}, "ok")

    monkeypatch.setattr(bd, "collect_agent_draft", _spy)
    bd.run_blind_drafts(_brief(epic), {}, tmp_path)
    return seen


def test_run_blind_drafts_epic_brief_threads_epic_mode(monkeypatch, tmp_path) -> None:
    seen = _run_with_spy(monkeypatch, tmp_path, epic=True)
    assert seen and set(seen) == {"epic"}


def test_run_blind_drafts_leaf_brief_threads_leaf_mode(monkeypatch, tmp_path) -> None:
    seen = _run_with_spy(monkeypatch, tmp_path, epic=False)
    assert seen and set(seen) == {"leaf"}


# ---- Part D: leaf back-compat invariants ---------------------------------

def test_validate_plan_signature_unchanged_rejects_bad_leaf_task() -> None:
    # A leaf plan with an incomplete task must still be rejected by validate_plan
    # directly (the 5 existing callers rely on this; Brief 6 must not touch it).
    bad_leaf = {"tasks": [{"task_id": "t1"}]}
    assert validate_plan(bad_leaf) != []
    assert validate_draft(bad_leaf, mode="leaf") == validate_plan(bad_leaf)
