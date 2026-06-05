"""Oracle for Brief 10b [FIRST LIGHT]: the epic decomposition pipeline.

RED on HEAD: cli.main has no epic branch — an epic brief is synthesized as leaf
tasks like any other. There is no _run_epic_pipeline and no _should_run_epic
gate. This oracle pins the first visible decomposition: given an epic brief, the
pipeline drafts child briefs (dual-model), reconciles them, writes re-plannable
brief_hooks_<slug>.md files at the repo root, and persists a plan_hooks epic
record listing the child slugs. Everything gated behind
hierarchical_planning.enabled (default-off).
"""
from __future__ import annotations

import json

import pytest

from harness.planner import PlanningBrief
from harness.planner import blind_draft as bd
from harness.planner import cli
from harness.planner.blind_draft import BlindDraftResult
from harness.planner.brief_generator import serialize_child_brief_to_markdown
from harness.planner.brief_loader import load_brief


def _brief(epic: bool = True) -> PlanningBrief:
    return PlanningBrief(
        title="Epic", scope="Decompose me.", non_goals="N", inputs="I",
        deliverables="D", raw_text="raw", source_path="/tmp/brief_hooks_epic.md",
        sha256="0" * 64, epic=epic,
    )


def _cb(slug: str, **over) -> dict:
    base = dict(slug=slug, title=f"Child {slug}", scope=f"build {slug}",
                non_goals="none", inputs="ins", deliverables=f"{slug}.py")
    base.update(over)
    return base


# ---- Part A: the default-off gate ----------------------------------------

def test_should_run_epic_gating() -> None:
    on = {"hierarchical_planning": {"enabled": True}}
    off = {"hierarchical_planning": {"enabled": False}}
    assert cli._should_run_epic(_brief(epic=True), on) is True
    assert cli._should_run_epic(_brief(epic=True), off) is False
    assert cli._should_run_epic(_brief(epic=False), on) is False
    assert cli._should_run_epic(_brief(epic=True), {}) is False  # missing -> off


# ---- Part B: the decomposition pipeline ----------------------------------

def _patch_drafts(monkeypatch, children: list) -> None:
    draft = {"plan_kind": "epic", "child_briefs": children}
    monkeypatch.setattr(
        bd, "run_blind_drafts",
        lambda b, c, s: BlindDraftResult(draft, "ok", draft, "ok"),
    )


def test_run_epic_pipeline_writes_children_and_record(monkeypatch, tmp_path) -> None:
    children = [_cb("alpha"), _cb("beta", dependencies=["alpha"],
                                  interfaces="f(x: int) -> str")]
    _patch_drafts(monkeypatch, children)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    out = tmp_path / "plan_hooks_epic.json"

    rc = cli._run_epic_pipeline(_brief(epic=True),
                                {"hierarchical_planning": {"enabled": True}},
                                state_dir, out)
    assert rc == 0

    # child briefs written at repo root (= state_dir.parent) and load cleanly
    a = tmp_path / "brief_hooks_alpha.md"
    b = tmp_path / "brief_hooks_beta.md"
    assert a.is_file() and b.is_file()
    assert load_brief(a).title == "Child alpha"
    lb = load_brief(b)
    assert set(lb.dependencies) == {"alpha"}
    assert lb.epic is False  # child briefs are leaf -> re-planned normally

    # epic record persisted with child slugs
    rec = json.loads(out.read_text())
    assert rec.get("plan_kind") == "epic"
    assert set(rec.get("child_slugs", [])) == {"alpha", "beta"}
    assert len(rec.get("child_briefs", [])) == 2


def test_run_epic_pipeline_both_agents_failed(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(bd, "run_blind_drafts",
                        lambda b, c, s: BlindDraftResult(None, "timeout", None, "timeout"))
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    rc = cli._run_epic_pipeline(_brief(epic=True),
                                {"hierarchical_planning": {"enabled": True}},
                                state_dir, tmp_path / "p.json")
    assert rc == 2


# ---- Part C: main routes epic briefs to the pipeline ----------------------

def test_main_routes_epic_to_pipeline(monkeypatch, tmp_path) -> None:
    brief_path = tmp_path / "brief_hooks_epic.md"
    brief_path.write_text(
        serialize_child_brief_to_markdown(
            dict(title="E", scope="s", non_goals="n", inputs="i", deliverables="d")
        ),
        encoding="utf-8",
    )
    called = {}
    monkeypatch.setattr(cli, "_should_run_epic", lambda brief, config: True)

    def _spy(brief, config, state_dir, out):
        called["hit"] = True
        return 0

    monkeypatch.setattr(cli, "_run_epic_pipeline", _spy)
    with pytest.raises(SystemExit) as ei:
        cli.main([str(brief_path), "--output-plan", str(tmp_path / "plan.json")])
    assert called.get("hit") is True
    assert ei.value.code == 0
