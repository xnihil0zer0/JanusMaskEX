"""Oracle for Brief 10a: extract a mode-aware ``_reconciliation_prompt(mode)``
helper + epic reconcile prompt loader, and thread ``mode`` through
``run_reconciliation``.

RED on HEAD: the reconciliation prompt is a hard-coded inline string inside
``run_reconciliation``; there is no ``_reconciliation_prompt`` helper and no
epic reconcile prompt file. So an epic decomposition with divergent child briefs
would be reconciled with the LEAF reconcile prompt (which talks about "task
plans"). Brief 10a adds the prompt-selection seam the epic pipeline (10b) uses.

Back-compat: leaf mode reproduces the existing reconcile prompt content, default
mode is leaf, and run_reconciliation keeps working for its current caller.
"""
from __future__ import annotations

from pathlib import Path

from harness.planner import reconciliation as rc
from harness.planner.diff_model import DiffItem, DiffKind, PlanDiff


# ---- Part A: _reconciliation_prompt helper -------------------------------

def test_reconciliation_prompt_is_callable() -> None:
    assert callable(getattr(rc, "_reconciliation_prompt", None))


def test_leaf_is_default_mode() -> None:
    assert rc._reconciliation_prompt() == rc._reconciliation_prompt("leaf")


def test_leaf_prompt_preserves_schema_markers() -> None:
    p = rc._reconciliation_prompt("leaf")
    assert "current_diff.json" in p
    assert "reconciliation.json" in p
    assert "responses" in p
    assert "diff_item_id" in p
    assert "stance" in p


def test_epic_prompt_file_exists() -> None:
    f = Path(rc.__file__).parent / "prompts" / "epic_reconciliation_prompt.md"
    assert f.is_file(), f"missing epic reconciliation prompt at {f}"


def test_epic_prompt_differs_and_mentions_child_briefs() -> None:
    leaf = rc._reconciliation_prompt("leaf")
    epic = rc._reconciliation_prompt("epic")
    assert epic != leaf
    low = epic.lower()
    assert "child brief" in low or "child_brief" in low
    # the response schema must be preserved so the collector still parses it
    assert "responses" in epic and "diff_item_id" in epic and "stance" in epic


# ---- Part B: run_reconciliation threads mode -----------------------------

def _divergent_diff() -> PlanDiff:
    item = DiffItem(
        kind=DiffKind.divergent,
        claude_task={"slug": "a", "scope": "A"},
        gemini_task={"slug": "a", "scope": "B"},
    )
    return PlanDiff(items=(item,))


def test_run_reconciliation_threads_mode(monkeypatch, tmp_path) -> None:
    seen: dict = {}

    def _spy(mode="leaf"):
        seen["mode"] = mode
        return "SPY_PROMPT"

    monkeypatch.setattr(rc, "_reconciliation_prompt", _spy)
    # Avoid spawning real agents; both "silent" -> divergent item unresolved.
    monkeypatch.setattr(rc, "run_both_agents", lambda *a, **k: (0, 0))
    rc.run_reconciliation(_divergent_diff(), {"child_briefs": []},
                          {"child_briefs": []}, {}, tmp_path, mode="epic")
    assert seen.get("mode") == "epic"


def test_run_reconciliation_default_mode_leaf(monkeypatch, tmp_path) -> None:
    seen: dict = {}
    monkeypatch.setattr(rc, "_reconciliation_prompt",
                        lambda mode="leaf": seen.setdefault("mode", mode) or "P")
    monkeypatch.setattr(rc, "run_both_agents", lambda *a, **k: (0, 0))
    rc.run_reconciliation(_divergent_diff(), {}, {}, {}, tmp_path)
    assert seen.get("mode") == "leaf"
