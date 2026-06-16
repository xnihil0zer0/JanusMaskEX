"""Oracle for Brief 3: load_brief parses epic / complexity_score / dependencies /
interfaces frontmatter with TYPED coercion (not the str()-wrapping that the
required-section normalize loop applies).

RED on HEAD: load_brief never reads these keys, and PlanningBrief has no
dependencies / interfaces fields — so every parse assertion below fails.

Design (the Area-B §5 gap): child-brief frontmatter `dependencies` must survive
load_brief so sibling order can be re-projected downstream (Briefs 10/12). This
brief makes the data available on the brief object; it does NOT itself project
onto leaf tasks.
"""
from __future__ import annotations

import dataclasses
import textwrap

import pytest

from harness.planner import PlanningBrief, load_brief


def _write_brief(tmp_path, frontmatter: str) -> "object":
    body = textwrap.dedent(
        """\
        # Scope
        Scope details.

        # Non-Goals
        None.

        # Inputs
        Some inputs.

        # Deliverables
        A thing.
        """
    )
    fm = "---\n" + frontmatter.strip() + "\n---\n"
    p = tmp_path / "brief.md"
    p.write_text(fm + body, encoding="utf-8")
    return p


# ---- field existence / defaults ------------------------------------------

def test_planningbrief_has_dependencies_and_interfaces_fields() -> None:
    names = [f.name for f in dataclasses.fields(PlanningBrief)]
    assert "dependencies" in names
    assert "interfaces" in names
    assert "required_task_ids" in names
    # dependencies/interfaces/required_task_ids are the trailing optional fields
    # (order-independent among the three, but pinned as the last three so a
    # future field append is a deliberate update, not a silent one).
    assert set(names[-3:]) == {"dependencies", "interfaces", "required_task_ids"}, names


def test_defaults_when_no_optional_frontmatter(tmp_path) -> None:
    brief = load_brief(_write_brief(tmp_path, "title: Plain"))
    assert brief.epic is False
    assert brief.complexity_score is None
    assert brief.dependencies == ()
    assert brief.interfaces is None


# ---- epic: typed bool, NOT the string "True" -----------------------------

def test_epic_true_parsed_as_bool(tmp_path) -> None:
    brief = load_brief(_write_brief(tmp_path, "title: E\nepic: true"))
    assert brief.epic is True
    assert isinstance(brief.epic, bool)


def test_epic_false_parsed_as_bool(tmp_path) -> None:
    brief = load_brief(_write_brief(tmp_path, "title: E\nepic: false"))
    assert brief.epic is False


def test_epic_string_true_coerced(tmp_path) -> None:
    # A quoted/stringy value must still coerce to a real bool, never "true".
    brief = load_brief(_write_brief(tmp_path, 'title: E\nepic: "true"'))
    assert brief.epic is True
    assert brief.epic is not "true"  # noqa: F632 — intentional identity guard


# ---- complexity_score: typed int|None ------------------------------------

def test_complexity_score_int(tmp_path) -> None:
    brief = load_brief(_write_brief(tmp_path, "title: C\ncomplexity_score: 7"))
    assert brief.complexity_score == 7
    assert isinstance(brief.complexity_score, int)


def test_complexity_score_string_digit_coerced(tmp_path) -> None:
    brief = load_brief(_write_brief(tmp_path, 'title: C\ncomplexity_score: "9"'))
    assert brief.complexity_score == 9
    assert isinstance(brief.complexity_score, int)


def test_complexity_score_garbage_is_none(tmp_path) -> None:
    brief = load_brief(_write_brief(tmp_path, "title: C\ncomplexity_score: not-a-number"))
    assert brief.complexity_score is None


# ---- dependencies: tuple[str, ...] ---------------------------------------

def test_dependencies_yaml_list(tmp_path) -> None:
    brief = load_brief(_write_brief(tmp_path, "title: D\ndependencies: [child_1, child_2]"))
    assert brief.dependencies == ("child_1", "child_2")
    assert isinstance(brief.dependencies, tuple)


def test_dependencies_comma_string(tmp_path) -> None:
    brief = load_brief(_write_brief(tmp_path, "title: D\ndependencies: child_1, child_2"))
    assert brief.dependencies == ("child_1", "child_2")


def test_dependencies_absent_is_empty_tuple(tmp_path) -> None:
    brief = load_brief(_write_brief(tmp_path, "title: D"))
    assert brief.dependencies == ()


# ---- interfaces: prose str|None ------------------------------------------

def test_interfaces_prose(tmp_path) -> None:
    brief = load_brief(_write_brief(tmp_path, 'title: I\ninterfaces: "x.py exposes f(a: int) -> str"'))
    assert brief.interfaces == "x.py exposes f(a: int) -> str"


def test_interfaces_absent_is_none(tmp_path) -> None:
    brief = load_brief(_write_brief(tmp_path, "title: I"))
    assert brief.interfaces is None


# ---- the optional keys must NOT disturb required-section validation -------

def test_optional_keys_do_not_satisfy_required_sections(tmp_path) -> None:
    from harness.planner import BriefValidationError

    # A brief whose ONLY content is optional epic frontmatter (no scope etc.)
    # must still fail required-section validation — the new keys are additive.
    p = tmp_path / "bad.md"
    p.write_text("---\ntitle: T\nepic: true\n---\n# Scope\nonly scope\n", encoding="utf-8")
    with pytest.raises(BriefValidationError):
        load_brief(p)


def test_epic_brief_still_loads_all_required_sections(tmp_path) -> None:
    brief = load_brief(
        _write_brief(tmp_path, "title: Full\nepic: true\ncomplexity_score: 3\ndependencies: [a]")
    )
    assert brief.title == "Full"
    assert brief.scope.startswith("Scope details")
    assert brief.epic is True
    assert brief.complexity_score == 3
    assert brief.dependencies == ("a",)
