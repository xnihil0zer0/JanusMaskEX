"""Oracle for Brief 2: PlanningBrief gains epic + complexity_score fields.

RED on HEAD: PlanningBrief has neither field, so constructing with epic=/
complexity_score= raises TypeError and the default-value assertions fail.

Brief 2 scope is ONLY the dataclass field block (parsing arrives in Brief 3).
The fields must be appended AFTER working_dir with defaults so the frozen
dataclass stays back-compatible for every existing constructor call site, and
the edit must NOT disturb the to_agent_prompt method (class-method red zone).
"""
from __future__ import annotations

import dataclasses

import pytest

from harness.planner import PlanningBrief


def _base_kwargs(**overrides) -> dict:
    kw = dict(
        title="T",
        scope="S",
        non_goals="N",
        inputs="I",
        deliverables="D",
        raw_text="raw",
        source_path="/tmp/brief.md",
        sha256="0" * 64,
    )
    kw.update(overrides)
    return kw


def test_epic_defaults_false() -> None:
    brief = PlanningBrief(**_base_kwargs())
    assert brief.epic is False


def test_complexity_score_defaults_none() -> None:
    brief = PlanningBrief(**_base_kwargs())
    assert brief.complexity_score is None


def test_epic_is_settable_true() -> None:
    brief = PlanningBrief(**_base_kwargs(epic=True))
    assert brief.epic is True


def test_complexity_score_is_settable_int() -> None:
    brief = PlanningBrief(**_base_kwargs(complexity_score=7))
    assert brief.complexity_score == 7


def test_backcompat_construction_without_new_fields() -> None:
    # Existing call sites that never pass the new fields must keep working,
    # and working_dir (the prior trailing optional) must still default to None.
    brief = PlanningBrief(**_base_kwargs())
    assert brief.working_dir is None
    assert brief.epic is False
    assert brief.complexity_score is None


def test_dataclass_remains_frozen() -> None:
    brief = PlanningBrief(**_base_kwargs())
    with pytest.raises(dataclasses.FrozenInstanceError):
        brief.epic = True  # type: ignore[misc]


def test_to_agent_prompt_unaffected_by_epic_fields() -> None:
    # The class-method body must be untouched: the rendered prompt is exactly the
    # five brief sections and never leaks the epic / complexity_score fields.
    brief = PlanningBrief(**_base_kwargs(epic=True, complexity_score=9))
    prompt = brief.to_agent_prompt()
    assert "epic" not in prompt.lower()
    assert "complexity_score" not in prompt
    assert prompt.startswith("Title: T")


def test_fields_declared_in_dataclass_order() -> None:
    # epic + complexity_score must be the LAST two fields (after working_dir) so
    # the default-argument ordering of the frozen dataclass stays legal.
    names = [f.name for f in dataclasses.fields(PlanningBrief)]
    assert names[-3:] == ["working_dir", "epic", "complexity_score"], names
