"""Operator-authored per-unit oracle for harness/planner/brief_loader.py public
units, named ``test_<unit>_<behaviour>`` so the rebuild engine's
``pytest -k <unit>`` selects exactly one unit's tests (the shipped tests name by
behaviour, which per-unit -k scoping can't isolate).

Used as the verification oracle for the JanusMask->JR brief_loader.py rebuild (P2).
brief_loader imports yaml (available in JR's .venv -> the engine routes the
yaml-touching units to the oracle-skip/fuzzer-bypass path; these operator tests
gate them instead). tmp_path fixtures carry no JanusMask state, so this runs
identically in JR. Import is package-qualified (mirrors
test_rebuild_brief_status_oracle.py)."""

import pytest

from harness.planner.brief_loader import (
    BriefTooLargeError,
    BriefValidationError,
    PlanningBrief,
    REQUIRED_SECTIONS,
    load_brief,
)

_GOOD = (
    "# Title\nDo the thing\n"
    "# Scope\nNarrow\n"
    "# Non-Goals\nNothing else\n"
    "# Inputs\nA file\n"
    "# Deliverables\nA patch\n"
)


def _write(tmp_path, text, name="brief.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ----- load_brief -----
def test_load_brief_parses_all_required_sections(tmp_path):
    brief = load_brief(_write(tmp_path, _GOOD))
    assert isinstance(brief, PlanningBrief)
    assert brief.title == "Do the thing"
    assert brief.scope == "Narrow"
    assert brief.non_goals == "Nothing else"
    assert brief.inputs == "A file"
    assert brief.deliverables == "A patch"
    assert len(brief.sha256) == 64


def test_load_brief_accepts_yaml_frontmatter(tmp_path):
    text = (
        "---\n"
        "title: FM Title\nscope: FM Scope\nnon_goals: none\n"
        "inputs: in\ndeliverables: out\n"
        "---\nbody\n"
    )
    brief = load_brief(_write(tmp_path, text))
    assert brief.title == "FM Title"
    assert brief.deliverables == "out"


def test_load_brief_raises_on_missing_section(tmp_path):
    text = "# Title\nT\n# Scope\nS\n# Inputs\nI\n# Deliverables\nD\n"  # no non_goals
    with pytest.raises(BriefValidationError) as exc:
        load_brief(_write(tmp_path, text))
    assert "non_goals" in exc.value.missing


def test_load_brief_raises_on_empty_section(tmp_path):
    text = "# Title\nT\n# Scope\n\n# Non-Goals\nN\n# Inputs\nI\n# Deliverables\nD\n"
    with pytest.raises(BriefValidationError) as exc:
        load_brief(_write(tmp_path, text))
    assert "scope" in exc.value.empty


def test_load_brief_rejects_too_large(tmp_path):
    p = _write(tmp_path, _GOOD)
    with pytest.raises(BriefTooLargeError) as exc:
        load_brief(p, max_bytes=4)
    assert exc.value.actual_bytes > 4


def test_load_brief_rejects_non_utf8(tmp_path):
    p = tmp_path / "bad.md"
    p.write_bytes(b"\xff\xfe# Title\n")
    with pytest.raises(BriefValidationError):
        load_brief(p)


# ----- PlanningBrief -----
def test_planningbrief_to_agent_prompt_includes_all_fields(tmp_path):
    b = PlanningBrief(
        title="T", scope="S", non_goals="N", inputs="I", deliverables="D",
        raw_text="x", source_path="p", sha256="z",
    )
    prompt = b.to_agent_prompt()
    assert "Title: T" in prompt
    assert "Scope:\nS" in prompt
    assert "Non-Goals:\nN" in prompt
    assert "Inputs:\nI" in prompt
    assert "Deliverables:\nD" in prompt


def test_planningbrief_is_frozen(tmp_path):
    b = PlanningBrief(
        title="T", scope="S", non_goals="N", inputs="I", deliverables="D",
        raw_text="x", source_path="p", sha256="z",
    )
    with pytest.raises(Exception):
        b.title = "changed"


# ----- BriefValidationError -----
def test_briefvalidationerror_init_carries_missing_and_empty(tmp_path):
    e = BriefValidationError("msg", missing=["title"], empty=["scope"])
    assert e.missing == ["title"]
    assert e.empty == ["scope"]
    assert str(e) == "msg"


def test_briefvalidationerror_init_defaults_to_empty_lists(tmp_path):
    e = BriefValidationError("msg")
    assert e.missing == []
    assert e.empty == []


# ----- BriefTooLargeError -----
def test_brieftoolargeerror_init_carries_actual_bytes(tmp_path):
    e = BriefTooLargeError("too big", actual_bytes=999)
    assert e.actual_bytes == 999
    assert str(e) == "too big"


# === P1/C9.17: per-unit-named oracles for oracle-SKIP units (construct_mapping
# untyped; the two __init__ self_mutating) so `pytest -k <unit>` scopes them.
import yaml as _yaml

from harness.planner.brief_loader import UniqueKeyLoader


def test_uniquekeyloader_construct_mapping_accepts_unique_keys(tmp_path):
    assert _yaml.load("a: 1\nb: 2\n", Loader=UniqueKeyLoader) == {"a": 1, "b": 2}


def test_uniquekeyloader_construct_mapping_rejects_duplicate_keys(tmp_path):
    with pytest.raises(_yaml.constructor.ConstructorError):
        _yaml.load("a: 1\na: 2\n", Loader=UniqueKeyLoader)


def test_briefvalidationerror_init_stores_lists_and_message(tmp_path):
    e = BriefValidationError("boom", missing=["title"], empty=["scope"])
    assert e.missing == ["title"] and e.empty == ["scope"] and str(e) == "boom"
    d = BriefValidationError("only msg")
    assert d.missing == [] and d.empty == []


def test_brieftoolargeerror_init_stores_actual_bytes(tmp_path):
    e = BriefTooLargeError("too big", actual_bytes=512)
    assert e.actual_bytes == 512 and str(e) == "too big"


# === C9.17 (session #43): pins for the two parser privates. The merged==original
# fuzz oracle is VACUOUS for these -- a random fuzzed string almost never starts
# with a ``---`` front-matter fence or a REQUIRED_SECTIONS ``#`` heading, so the
# interesting branches are unreachable and a wrong reconstruction would land
# silently. These behavioural pins make ``pytest -k <unit>`` the real gate.
from harness.planner.brief_loader import _parse_frontmatter, _parse_markdown_sections


def test_parse_frontmatter_returns_empty_and_text_when_no_fence(tmp_path):
    assert _parse_frontmatter("# Title\nhello") == ({}, "# Title\nhello")


def test_parse_frontmatter_extracts_yaml_and_body(tmp_path):
    fm, body = _parse_frontmatter("---\nkey: val\nfoo: bar\n---\nbody here\n")
    assert fm == {"key": "val", "foo": "bar"}
    assert body == "body here\n"


def test_parse_frontmatter_raises_on_duplicate_keys(tmp_path):
    with pytest.raises(BriefValidationError):
        _parse_frontmatter("---\nk: 1\nk: 2\n---\nbody")


def test_parse_markdown_sections_collects_only_required_headings(tmp_path):
    # only REQUIRED_SECTIONS headings start a section; a non-required heading
    # (## Extra) is kept as the current section's CONTENT.
    out = _parse_markdown_sections("# Title\nT\n# Scope\nS\n## Extra\nE\n# Inputs\nI")
    assert out == {"title": "T", "scope": "S\n## Extra\nE", "inputs": "I"}


def test_parse_markdown_sections_drops_preamble_and_unrequired(tmp_path):
    # content before the first required heading is dropped
    assert _parse_markdown_sections("preamble\n# Title\nT") == {"title": "T"}
    # a document with no required heading yields no sections
    assert _parse_markdown_sections("# Random\nstuff") == {}
