"""RED oracle (Epic-3 decomposer fix, defect 2b): serialize_child_brief_to_markdown
must carry a child's ``epic`` flag into the emitted brief frontmatter so a
SUB-EPIC child round-trips through serialize -> write -> load_brief with
``epic is True`` (and the daemon's _should_run_epic then recurses on it).

RED on HEAD: the serializer emits working_dir/dependencies/interfaces only;
``epic`` is silently dropped, so a generated sub-epic child brief loads with
``epic is False`` and is mis-planned as a leaf.

GREEN after the fix: ``epic: true`` is emitted when brief_data['epic'] is truthy
and round-trips via load_brief; an absent/false epic emits no epic key (backward
compatible). Hermetic external path under tmp_path.
"""
from __future__ import annotations

from harness.planner.brief_generator import serialize_child_brief_to_markdown
from harness.planner.brief_loader import load_brief


def _data(**over) -> dict:
    base = dict(slug="child_ep", title="Child EP", scope="Build sub-epic X.",
                non_goals="none", inputs="i", deliverables="d",
                working_dir=str(over.pop("_wd", "/tmp/ext_epic_target")))
    base.update(over)
    return base


def _write_load(tmp_path, md, name="brief_hooks_child_ep.md"):
    p = tmp_path / name
    p.write_text(md, encoding="utf-8")
    return load_brief(p)


def test_epic_true_roundtrips(tmp_path) -> None:
    ext = str(tmp_path / "ext")
    md = serialize_child_brief_to_markdown(_data(_wd=ext, epic=True))
    assert "epic: true" in md
    brief = _write_load(tmp_path, md)
    assert brief.epic is True


def test_epic_absent_emits_no_epic_key(tmp_path) -> None:
    ext = str(tmp_path / "ext")
    md = serialize_child_brief_to_markdown(_data(_wd=ext))
    assert "epic:" not in md
    brief = _write_load(tmp_path, md)
    assert brief.epic is False


def test_epic_false_not_emitted(tmp_path) -> None:
    ext = str(tmp_path / "ext")
    md = serialize_child_brief_to_markdown(_data(_wd=ext, epic=False))
    assert "epic:" not in md
    brief = _write_load(tmp_path, md)
    assert brief.epic is False
