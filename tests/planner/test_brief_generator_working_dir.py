"""RED oracle (NGv2 Epic-1 auto-decompose, working_dir propagation step 1/3):
``serialize_child_brief_to_markdown`` must carry a child's ``working_dir`` into
the emitted brief frontmatter so ``load_brief`` recovers it.

RED on HEAD: the serializer only serializes ``dependencies`` and ``interfaces``;
``working_dir`` is silently dropped, so an epic-generated child brief loads with
``working_dir is None`` and the child plan never targets the external repo.

GREEN after the fix: a non-empty ``working_dir`` round-trips through
serialize -> write -> load_brief. Empty/absent working_dir still loads cleanly
(no frontmatter key emitted), preserving backward compatibility. All cases use a
HERMETIC external path under tmp_path (outside the JM repo) so load_brief's
self/inside-repo guard is not tripped.
"""
from __future__ import annotations

from harness.planner.brief_generator import serialize_child_brief_to_markdown
from harness.planner.brief_loader import load_brief


def _data(**over) -> dict:
    base = dict(
        slug="child_wd",
        title="Child WD",
        scope="Build the external X subsystem.",
        non_goals="Do not touch Y.",
        inputs="a.py",
        deliverables="b.py exposes f().",
    )
    base.update(over)
    return base


def _write(tmp_path, md: str, name: str = "brief_hooks_child_wd.md"):
    p = tmp_path / name
    p.write_text(md, encoding="utf-8")
    return p


def test_working_dir_roundtrips_external(tmp_path) -> None:
    ext = str(tmp_path / "ext_target")  # outside the JM repo -> loader accepts
    md = serialize_child_brief_to_markdown(_data(working_dir=ext))
    brief = load_brief(_write(tmp_path, md))
    assert brief.working_dir == ext


def test_working_dir_coexists_with_other_frontmatter(tmp_path) -> None:
    ext = str(tmp_path / "ext_target")
    md = serialize_child_brief_to_markdown(
        _data(working_dir=ext, dependencies=["sib_a"], interfaces="f(x: int) -> str")
    )
    brief = load_brief(_write(tmp_path, md))
    assert brief.working_dir == ext
    assert set(brief.dependencies) == {"sib_a"}
    assert brief.interfaces and "f(x: int) -> str" in brief.interfaces


def test_absent_working_dir_loads_none(tmp_path) -> None:
    brief = load_brief(_write(tmp_path, serialize_child_brief_to_markdown(_data())))
    assert brief.working_dir is None


def test_empty_working_dir_not_emitted(tmp_path) -> None:
    # An empty/whitespace working_dir must not break loading nor emit a key.
    brief = load_brief(
        _write(tmp_path, serialize_child_brief_to_markdown(_data(working_dir="   ")))
    )
    assert brief.working_dir is None
