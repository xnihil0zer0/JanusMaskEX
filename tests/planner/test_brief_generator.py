"""Oracle for Brief 11: serialize a child-brief dict to markdown that
``load_brief`` accepts.

RED on HEAD: there is no ``harness/planner/brief_generator`` module. The epic
pipeline (Brief 10) writes child ``brief_hooks_<slug>.md`` files that the daemon
re-plans through ``load_brief``; if the serialized markdown is missing a required
section or has malformed frontmatter the child brief fails to load (planner exits
3). This oracle pins the round-trip: serialize -> write -> load_brief succeeds
and every field survives.
"""
from __future__ import annotations

from harness.planner.brief_generator import serialize_child_brief_to_markdown
from harness.planner.brief_loader import load_brief


def _data(**over) -> dict:
    base = dict(
        slug="child_one",
        title="Child One",
        scope="Build the X subsystem.",
        non_goals="Do not touch Y.",
        inputs="a.py, the existing loader",
        deliverables="b.py exposes f().",
    )
    base.update(over)
    return base


def _write(tmp_path, md: str, name: str = "brief_hooks_child_one.md"):
    p = tmp_path / name
    p.write_text(md, encoding="utf-8")
    return p


def test_returns_str_with_required_headings() -> None:
    md = serialize_child_brief_to_markdown(_data())
    assert isinstance(md, str)
    low = md.lower()
    for h in ("# title", "# scope", "# non-goals", "# inputs", "# deliverables"):
        assert h in low, f"missing heading {h}"


def test_serialized_brief_loads_and_roundtrips(tmp_path) -> None:
    brief = load_brief(_write(tmp_path, serialize_child_brief_to_markdown(_data())))
    assert brief.title == "Child One"
    assert "Build the X subsystem." in brief.scope
    assert "Do not touch Y." in brief.non_goals
    assert "a.py" in brief.inputs
    assert "b.py exposes f()." in brief.deliverables


def test_dependencies_and_interfaces_roundtrip(tmp_path) -> None:
    md = serialize_child_brief_to_markdown(
        _data(dependencies=["sib_a", "sib_b"], interfaces="f(a: int) -> str")
    )
    brief = load_brief(_write(tmp_path, md))
    assert set(brief.dependencies) == {"sib_a", "sib_b"}
    assert brief.interfaces and "f(a: int) -> str" in brief.interfaces


def test_no_optional_fields_still_loads(tmp_path) -> None:
    brief = load_brief(_write(tmp_path, serialize_child_brief_to_markdown(_data())))
    assert brief.dependencies == ()
    assert brief.epic is False  # child briefs are leaf, re-planned normally


def test_empty_dependencies_list_loads(tmp_path) -> None:
    brief = load_brief(_write(tmp_path, serialize_child_brief_to_markdown(_data(dependencies=[]))))
    assert brief.dependencies == ()


def test_content_with_special_chars_loads(tmp_path) -> None:
    md = serialize_child_brief_to_markdown(
        _data(scope="Use a: b, c; and `code` and dashes - like this.")
    )
    brief = load_brief(_write(tmp_path, md))
    assert "code" in brief.scope
