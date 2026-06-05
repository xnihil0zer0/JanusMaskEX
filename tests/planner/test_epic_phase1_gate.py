"""Brief 17 [GATE]: Phase-1 end-to-end acceptance proof for the hierarchical
(epic) planner.

This is the closing oracle for Phase 1. It drives the assembled Level-1 loop on
one allowlisted epic brief and proves it closes:

    epic brief (epic: true, flag ON)
      -> _run_epic_pipeline decomposes it
      -> N planless child brief_hooks_<slug>.md (each load_brief-valid => re-plannable)
      -> an epic plan_hooks record (validate_plan / validate_epic_plan clean)
      -> child slugs admitted to the auto_promote allowlist (operator step; the
         Brief-15 auto-admission is owner-security-gated and intentionally NOT
         automated here)
      -> children re-plan + their leaf tasks land
      -> compute_epic_status rolls the epic up to 'complete'

The ONLY mocked seams are the two LLM boundaries — run_blind_drafts and
run_reconciliation (the dual-model draft + reconcile) — and the child re-plan
*outcome* (writing child plan_hooks + accepting their tasks), because re-planning
each child likewise spawns real agents. Everything between (flag gating, brief
parsing, child-brief serialization, load_brief round-trip, epic-record
validation, depth bounding, eligibility, and the read-derived roll-up) is the
real production code.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.planner.brief_loader import load_brief
from harness.planner.cli import _should_run_epic, _run_epic_pipeline
from harness.planner.plan_validator import validate_plan, validate_epic_plan
from harness.depth_validator import check_brief_depth
from harness.brief_status import compute_epic_status, compute_autowork_eligibility


EPIC_SLUG = "my_epic"
CHILD_SLUGS = ["child_alpha", "child_beta"]


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _child_dict(slug: str) -> dict:
    return {
        "slug": slug,
        "title": f"Title {slug}",
        "scope": f"Build the {slug} component.",
        "non_goals": "No integration with unrelated subsystems.",
        "inputs": "The epic's shared interfaces.",
        "deliverables": f"A working {slug} module.",
    }


def _epic_draft() -> dict:
    return {"plan_kind": "epic", "child_briefs": [_child_dict(s) for s in CHILD_SLUGS]}


def _write_epic_brief(repo: Path) -> Path:
    body = (
        "---\n"
        "epic: true\n"
        "complexity_score: 8\n"
        "---\n\n"
        "# Title\n\nThe Epic\n\n"
        "# Scope\n\nDeliver alpha and beta as separable components.\n\n"
        "# Non-Goals\n\nNothing outside alpha/beta.\n\n"
        "# Inputs\n\nShared interface contracts.\n\n"
        "# Deliverables\n\nalpha + beta integrated.\n"
    )
    p = repo / f"brief_hooks_{EPIC_SLUG}.md"
    p.write_text(body, encoding="utf-8")
    return p


def _patch_llm_seams(monkeypatch):
    draft = _epic_draft()

    def _fake_blind_drafts(brief, config, state_dir):
        return SimpleNamespace(
            claude_draft=draft, claude_status="ok",
            gemini_draft=draft, gemini_status="ok",
        )

    def _fake_reconciliation(diff, c, g, config, state_dir, mode="leaf"):
        assert mode == "epic", "epic pipeline must reconcile in epic mode"
        return SimpleNamespace(merged_tasks=[_child_dict(s) for s in CHILD_SLUGS])

    monkeypatch.setattr("harness.planner.blind_draft.run_blind_drafts", _fake_blind_drafts)
    monkeypatch.setattr("harness.planner.reconciliation.run_reconciliation", _fake_reconciliation)


def _accept(state_dir: Path, task_id: str) -> None:
    ledger = state_dir / "impl_progress.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger, "a", encoding="utf-8") as f:
        f.write(json.dumps({"phase": "accepted", "event": "auto_commit",
                            "task_id": task_id, "commit_sha": "deadbeef", "ts": 1.0}) + "\n")


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------

def test_flag_off_does_not_decompose(tmp_path):
    repo = tmp_path
    brief = load_brief(_write_epic_brief(repo))
    assert brief.epic is True            # Brief 2/3: epic frontmatter parsed
    assert brief.complexity_score == 8
    # Brief 1: default-off gate. Flag off => no decomposition even for an epic.
    assert _should_run_epic(brief, {"hierarchical_planning": {"enabled": False}}) is False
    assert _should_run_epic(brief, {}) is False


def test_phase1_epic_loop_closes(tmp_path, monkeypatch):
    repo = tmp_path
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    config = {"hierarchical_planning": {"enabled": True, "max_planner_depth": 4}}

    brief = load_brief(_write_epic_brief(repo))
    assert _should_run_epic(brief, config) is True   # flag ON + epic brief

    _patch_llm_seams(monkeypatch)
    out_plan = repo / f"plan_hooks_{EPIC_SLUG}.json"

    # --- decomposition --------------------------------------------------
    rc = _run_epic_pipeline(brief, config, state, out_plan)
    assert rc == 0

    # N planless child briefs, each re-plannable (load_brief accepts them).
    for slug in CHILD_SLUGS:
        child_path = repo / f"brief_hooks_{slug}.md"
        assert child_path.exists(), f"missing child brief for {slug}"
        child_brief = load_brief(child_path)           # Brief 11 serializer => valid
        assert child_brief.title == f"Title {slug}"

    # --- epic record validates as an epic, not a malformed leaf ---------
    epic_record = json.loads(out_plan.read_text())
    assert epic_record["plan_kind"] == "epic"
    assert epic_record.get("epic_slug") == EPIC_SLUG    # Brief 12 provenance
    assert sorted(epic_record["child_slugs"]) == sorted(CHILD_SLUGS)
    assert validate_epic_plan(epic_record) == []        # Brief 13 validator
    assert validate_plan(epic_record) == []             # Brief 13 dispatch routes it

    # --- depth bounded (children are depth 1, within budget) ------------
    for slug in CHILD_SLUGS:
        assert check_brief_depth(slug, repo, 4) is True   # Brief 14

    # --- operator allowlist step (Brief 15 auto-admission is owner-gated)
    allow = state / "control" / "autowork" / "auto_promote.allowlist"
    allow.parent.mkdir(parents=True, exist_ok=True)
    allow.write_text("\n".join([EPIC_SLUG, *CHILD_SLUGS]) + "\n", encoding="utf-8")
    elig = compute_autowork_eligibility(repo, state)
    for slug in CHILD_SLUGS:
        assert slug in elig["eligible"], f"{slug} should be allowlist-eligible"

    # --- children re-plan: their leaf tasks land (simulated outcome) ----
    for slug in CHILD_SLUGS:
        tid = f"{slug}_t1"
        (repo / f"plan_hooks_{slug}.json").write_text(
            json.dumps({"tasks": [{"task_id": tid}]}), encoding="utf-8")
        _accept(state, tid)

    # --- roll-up: epic completes iff all children complete --------------
    epics = compute_epic_status(repo, state)             # Brief 16
    rec = next(e for e in epics if e["epic_slug"] == EPIC_SLUG)
    assert rec["state"] == "complete"


def test_epic_not_complete_until_all_children_land(tmp_path, monkeypatch):
    repo = tmp_path
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    config = {"hierarchical_planning": {"enabled": True}}
    brief = load_brief(_write_epic_brief(repo))
    _patch_llm_seams(monkeypatch)
    out_plan = repo / f"plan_hooks_{EPIC_SLUG}.json"
    assert _run_epic_pipeline(brief, config, state, out_plan) == 0

    # Only the first child's task lands.
    first, second = CHILD_SLUGS
    (repo / f"plan_hooks_{first}.json").write_text(
        json.dumps({"tasks": [{"task_id": f"{first}_t1"}]}), encoding="utf-8")
    _accept(state, f"{first}_t1")
    (repo / f"plan_hooks_{second}.json").write_text(
        json.dumps({"tasks": [{"task_id": f"{second}_t1"}]}), encoding="utf-8")
    # second child's task NOT accepted

    rec = next(e for e in compute_epic_status(repo, state) if e["epic_slug"] == EPIC_SLUG)
    assert rec["state"] != "complete"
