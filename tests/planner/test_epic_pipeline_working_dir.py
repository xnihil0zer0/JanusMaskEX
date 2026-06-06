"""RED oracle (NGv2 Epic-1 auto-decompose, working_dir propagation step 2/3):
``_run_epic_pipeline`` must stamp the epic brief's ``working_dir`` onto every
generated child brief so the child brief_hooks_<slug>.md (and the child plan
re-derived from it) targets the external repo.

RED on HEAD: ``_run_epic_pipeline`` writes child briefs from the reconciled child
dicts WITHOUT copying the epic's top-level working_dir into them, so each child
loads with working_dir=None even when the epic targets an external repo.

GREEN after the fix: each child brief written by _run_epic_pipeline carries the
epic's working_dir, recoverable via load_brief. A self/empty-working_dir epic
leaves children without a working_dir (backward compatible).

Depends on the serializer carrying working_dir (step 1/3). Hermetic: drafts are
monkeypatched; external paths live under tmp_path (outside the JM repo).
"""
from __future__ import annotations

from harness.planner import PlanningBrief
from harness.planner import blind_draft as bd
from harness.planner import cli
from harness.planner.blind_draft import BlindDraftResult
from harness.planner.brief_loader import load_brief


def _brief(working_dir=None) -> PlanningBrief:
    return PlanningBrief(
        title="Epic", scope="Decompose me.", non_goals="N", inputs="I",
        deliverables="D", raw_text="raw", source_path="/tmp/brief_hooks_epic.md",
        sha256="0" * 64, epic=True, working_dir=working_dir,
    )


def _cb(slug: str, **over) -> dict:
    base = dict(slug=slug, title=f"Child {slug}", scope=f"build {slug}",
                non_goals="none", inputs="ins", deliverables=f"{slug}.py")
    base.update(over)
    return base


def _patch_drafts(monkeypatch, children: list) -> None:
    draft = {"plan_kind": "epic", "child_briefs": children}
    monkeypatch.setattr(
        bd, "run_blind_drafts",
        lambda b, c, s: BlindDraftResult(draft, "ok", draft, "ok"),
    )


def _run(monkeypatch, tmp_path, brief, children):
    _patch_drafts(monkeypatch, children)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    out = tmp_path / "plan_hooks_epic.json"
    rc = cli._run_epic_pipeline(
        brief, {"hierarchical_planning": {"enabled": True}}, state_dir, out
    )
    assert rc == 0
    return tmp_path


def test_external_working_dir_stamped_on_every_child(monkeypatch, tmp_path) -> None:
    ext = str(tmp_path / "ext_target")
    root = _run(monkeypatch, tmp_path, _brief(working_dir=ext),
               [_cb("alpha"), _cb("beta", dependencies=["alpha"])])
    for slug in ("alpha", "beta"):
        cb = load_brief(root / f"brief_hooks_{slug}.md")
        assert cb.working_dir == ext, f"child {slug} missing working_dir"


def test_no_working_dir_epic_leaves_children_unrooted(monkeypatch, tmp_path) -> None:
    root = _run(monkeypatch, tmp_path, _brief(working_dir=None), [_cb("gamma")])
    cb = load_brief(root / "brief_hooks_gamma.md")
    assert cb.working_dir is None
