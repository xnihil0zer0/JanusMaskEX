"""Oracle for Brief 12: persist_plan epic wrapper + parent_epic_slug provenance.

RED on HEAD: persist_plan injects source_brief_path/source_brief_sha256/
working_dir but knows nothing about epics. Per area_C_verified.md (M2), roll-up
(Brief 16) and brief-depth bounding (Brief 14) need each child plan_hooks to
carry a ``parent_epic_slug`` and each epic record to carry its own ``epic_slug``;
the natural home is persist_plan (it already stamps wrapper provenance) and
compute_brief_status reads it. This oracle pins that stamp, mirroring the
working_dir injection (conditional + idempotent), with leaf plans byte-unchanged.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from harness.planner.cli import persist_plan


def _brief(**over):
    base = dict(source_path="/tmp/brief_hooks_child.md", sha256="a" * 64,
                working_dir=None)
    base.update(over)
    return SimpleNamespace(**base)


def _load(p):
    return json.loads(p.read_text())


# ---- parent_epic_slug provenance (child plans) ---------------------------

def test_parent_epic_slug_stamped(tmp_path) -> None:
    out = tmp_path / "plan_hooks_child.json"
    persist_plan({"tasks": []}, out, brief_obj=_brief(parent_epic_slug="my_epic"))
    assert _load(out)["parent_epic_slug"] == "my_epic"


def test_parent_epic_slug_not_overwritten(tmp_path) -> None:
    out = tmp_path / "p.json"
    persist_plan({"tasks": [], "parent_epic_slug": "already"}, out,
                 brief_obj=_brief(parent_epic_slug="my_epic"))
    assert _load(out)["parent_epic_slug"] == "already"


def test_no_parent_epic_slug_when_absent(tmp_path) -> None:
    out = tmp_path / "p.json"
    persist_plan({"tasks": []}, out, brief_obj=_brief())  # no parent_epic_slug attr
    assert "parent_epic_slug" not in _load(out)


# ---- epic record self-identity (epic_slug) -------------------------------

def test_epic_record_gets_epic_slug(tmp_path) -> None:
    out = tmp_path / "plan_hooks_bigepic.json"
    persist_plan({"plan_kind": "epic", "child_slugs": ["a", "b"]}, out,
                 brief_obj=_brief(source_path="/tmp/brief_hooks_bigepic.md"))
    rec = _load(out)
    assert rec["epic_slug"] == "bigepic"


def test_epic_slug_not_added_to_leaf_plan(tmp_path) -> None:
    out = tmp_path / "p.json"
    persist_plan({"tasks": []}, out, brief_obj=_brief())
    assert "epic_slug" not in _load(out)


# ---- back-compat: existing wrapper injection preserved -------------------

def test_existing_wrapper_injection_preserved(tmp_path) -> None:
    out = tmp_path / "p.json"
    persist_plan({"tasks": []}, out,
                 brief_obj=_brief(source_path="/tmp/brief_hooks_x.md",
                                  working_dir="/repo"))
    rec = _load(out)
    assert rec["source_brief_path"] == "/tmp/brief_hooks_x.md"
    assert rec["source_brief_sha256"] == "a" * 64
    assert rec["working_dir"] == "/repo"
