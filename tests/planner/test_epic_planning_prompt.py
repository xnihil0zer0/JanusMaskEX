"""Oracle for Brief 7: extract a mode-aware ``_planning_prompt(brief, mode)``
helper + a prompt-file loader, backed by ``prompts/epic_decomposition_prompt.md``.

RED on HEAD: the planning prompt is a hard-coded inline f-string inside
``run_blind_drafts`` (blind_draft.py); there is no ``_planning_prompt`` helper
and no prompt-selection seam. So an epic brief would be drafted with the LEAF
task-synthesis prompt — both agents are told to emit a ``tasks`` array with the
full leaf schema, never child briefs. Brief 7 builds the prompt-selection seam
that Brief 10 (first light) routes through.

Back-compat: leaf mode must preserve the existing leaf-schema instructions the
agents rely on, and ``run_blind_drafts`` must select the prompt by the brief's
``epic`` flag.
"""
from __future__ import annotations

from pathlib import Path

from harness.planner import PlanningBrief
from harness.planner import blind_draft as bd


def _brief(epic: bool) -> PlanningBrief:
    return PlanningBrief(
        title="Epic Title Marker",
        scope="Epic Scope Marker",
        non_goals="Epic NonGoals Marker",
        inputs="Epic Inputs Marker",
        deliverables="Epic Deliverables Marker",
        raw_text="full epic body marker text",
        source_path="/tmp/e.md",
        sha256="0" * 64,
        epic=epic,
    )


# ---- Part A: the helper exists and is mode-aware -------------------------

def test_planning_prompt_is_callable() -> None:
    assert callable(getattr(bd, "_planning_prompt", None))


def test_leaf_is_the_default_mode() -> None:
    b = _brief(epic=False)
    assert bd._planning_prompt(b) == bd._planning_prompt(b, "leaf")


def test_leaf_prompt_preserves_leaf_schema_instructions() -> None:
    p = bd._planning_prompt(_brief(epic=False), "leaf")
    # The leaf prompt must keep instructing agents to emit the leaf task schema.
    assert "plan_draft.json" in p
    assert "meta_task_type" in p
    assert "tasks" in p


def test_leaf_prompt_embeds_brief_fields() -> None:
    p = bd._planning_prompt(_brief(epic=False), "leaf")
    assert "Epic Title Marker" in p
    assert "Epic Scope Marker" in p


# ---- Part B: epic mode loads the child-brief decomposition prompt --------

def test_epic_prompt_file_exists() -> None:
    f = Path(bd.__file__).parent / "prompts" / "epic_decomposition_prompt.md"
    assert f.is_file(), f"missing epic decomposition prompt file at {f}"


def test_epic_prompt_differs_from_leaf() -> None:
    b = _brief(epic=True)
    assert bd._planning_prompt(b, "epic") != bd._planning_prompt(b, "leaf")


def test_epic_prompt_instructs_child_brief_drafting() -> None:
    p = bd._planning_prompt(_brief(epic=True), "epic").lower()
    assert "child brief" in p or "child_brief" in p
    assert "slug" in p
    # the brief body sections that load_brief / the serializer require
    for section in ("scope", "non-goals", "deliverables"):
        assert section in p


def test_epic_prompt_declares_epic_output_schema() -> None:
    # epic drafts must be told to emit the child_briefs schema (not a tasks array)
    p = bd._planning_prompt(_brief(epic=True), "epic")
    assert "child_briefs" in p
    assert "plan_kind" in p


def test_epic_prompt_embeds_brief_fields() -> None:
    p = bd._planning_prompt(_brief(epic=True), "epic")
    assert "Epic Title Marker" in p  # the epic brief's own context threads through


# ---- Part C: run_blind_drafts selects the prompt by the brief's mode -----

def _prime_drafts(tmp_path) -> None:
    # Pre-place both draft files so run_both_agents is skipped (no real spawn).
    sess = tmp_path / "planning" / "sessions"
    sess.mkdir(parents=True, exist_ok=True)
    (sess / "claude_draft.json").write_text("{}", encoding="utf-8")
    (sess / "gemini_draft.json").write_text("{}", encoding="utf-8")


def test_run_blind_drafts_uses_planning_prompt_epic(monkeypatch, tmp_path) -> None:
    _prime_drafts(tmp_path)
    seen: dict = {}

    def _spy(brief, mode="leaf"):
        seen["mode"] = mode
        return "SPY_PROMPT"

    monkeypatch.setattr(bd, "_planning_prompt", _spy)
    monkeypatch.setattr(bd, "collect_agent_draft", lambda *a, **k: ({"ok": True}, "ok"))
    bd.run_blind_drafts(_brief(epic=True), {}, tmp_path)
    assert seen.get("mode") == "epic"


def test_run_blind_drafts_uses_planning_prompt_leaf(monkeypatch, tmp_path) -> None:
    _prime_drafts(tmp_path)
    seen: dict = {}

    def _spy(brief, mode="leaf"):
        seen["mode"] = mode
        return "SPY_PROMPT"

    monkeypatch.setattr(bd, "_planning_prompt", _spy)
    monkeypatch.setattr(bd, "collect_agent_draft", lambda *a, **k: ({"ok": True}, "ok"))
    bd.run_blind_drafts(_brief(epic=False), {}, tmp_path)
    assert seen.get("mode") == "leaf"
