"""RED oracle (Epic-3 decomposer fixes): _run_epic_pipeline must

  (defect 1) NORMALIZE + DEDUPE child slugs so the two agents' hyphen/underscore
    variants (e.g. 'alpha-one' and 'alpha_one') collapse to ONE canonical child
    (hyphen form) instead of producing duplicate sibling leaves; and
  (defect 2a) MARK children as epics when the parent epic brief declares
    ``child_epics: true`` in its frontmatter, so the written child briefs carry
    ``epic: true`` and the daemon recursively decomposes them (multi-level).

RED on HEAD: merged children are written verbatim (dup hyphen+underscore slugs
both produced), and no child is marked epic regardless of the parent.

GREEN after the fix: a pure helper _finalize_epic_children(merged, epic_wd,
child_epics) canonicalizes slugs (replace '_' with '-'), dedupes by canonical
slug (first wins), stamps working_dir, and sets epic=True iff child_epics; and
_run_epic_pipeline parses child_epics from the parent brief frontmatter and uses
the helper. Hermetic: drafts monkeypatched; external paths under tmp_path.
"""
from __future__ import annotations

from harness.planner import PlanningBrief
from harness.planner import blind_draft as bd
from harness.planner import cli
from harness.planner.blind_draft import BlindDraftResult
from harness.planner.brief_loader import load_brief


def _brief(raw_text="raw", working_dir=None) -> PlanningBrief:
    return PlanningBrief(
        title="Epic", scope="Decompose me.", non_goals="N", inputs="I",
        deliverables="D", raw_text=raw_text, source_path="/tmp/brief_hooks_epic.md",
        sha256="0" * 64, epic=True, working_dir=working_dir,
    )


def _cb(slug, **over):
    base = dict(slug=slug, title=f"Child {slug}", scope=f"build {slug}",
                non_goals="none", inputs="ins", deliverables=f"{slug}.py")
    base.update(over)
    return base


def _patch(monkeypatch, children):
    draft = {"plan_kind": "epic", "child_briefs": children}
    monkeypatch.setattr(bd, "run_blind_drafts",
                        lambda b, c, s: BlindDraftResult(draft, "ok", draft, "ok"))


def _run(monkeypatch, tmp_path, brief, children):
    _patch(monkeypatch, children)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    out = tmp_path / "plan_hooks_epic.json"
    rc = cli._run_epic_pipeline(brief, {"hierarchical_planning": {"enabled": True}}, state_dir, out)
    assert rc == 0
    import json
    return tmp_path, json.loads(out.read_text(encoding="utf-8"))


# ---- defect 1: dedupe hyphen/underscore slug variants ----------------------

def test_duplicate_slug_variants_deduped(monkeypatch, tmp_path) -> None:
    _, plan = _run(monkeypatch, tmp_path,
                   _brief(working_dir=str(tmp_path / "ext")),
                   [_cb("alpha-one"), _cb("alpha_one"), _cb("beta")])
    # canonical (hyphen) dedup: alpha_one collapses into alpha-one
    assert plan["child_slugs"] == ["alpha-one", "beta"]
    # only the canonical brief files exist
    assert (tmp_path / "brief_hooks_alpha-one.md").exists()
    assert (tmp_path / "brief_hooks_beta.md").exists()
    assert not (tmp_path / "brief_hooks_alpha_one.md").exists()


# ---- defect 2a: mark children epic when parent declares child_epics --------

_PARENT_CHILD_EPICS = "---\nchild_epics: true\nworking_dir: \"%s\"\n---\n# Title\n\nx\n"


def test_child_epics_marks_children(monkeypatch, tmp_path) -> None:
    ext = str(tmp_path / "ext")
    root, _ = _run(monkeypatch, tmp_path,
                   _brief(raw_text=_PARENT_CHILD_EPICS % ext, working_dir=ext),
                   [_cb("suba"), _cb("subb")])
    for slug in ("suba", "subb"):
        cb = load_brief(root / f"brief_hooks_{slug}.md")
        assert cb.epic is True, f"child {slug} not marked epic"


def test_no_child_epics_children_are_leaves(monkeypatch, tmp_path) -> None:
    ext = str(tmp_path / "ext")
    root, _ = _run(monkeypatch, tmp_path, _brief(working_dir=ext), [_cb("leaf1")])
    cb = load_brief(root / "brief_hooks_leaf1.md")
    assert cb.epic is False
