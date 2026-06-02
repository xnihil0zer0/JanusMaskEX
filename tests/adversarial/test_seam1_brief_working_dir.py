"""
RED-on-HEAD oracle for REV21 §4 seam 1: PHASE_SEAM1_BRIEF_WORKINGDIR.

Adds an OPTIONAL, FRONTMATTER-ONLY `working_dir: str | None = None` field to
PlanningBrief so an operator brief can declare an external target. This seam is
PURE PLUMBING and INERT: it relaxes NO gate (nothing consumes working_dir for
gate-relaxation until G2/seam-5). Absent ⇒ self-build (fail-safe-to-self default).

RED on HEAD because:
  - PlanningBrief has no `working_dir` field (and load_brief drops the key in the
    REQUIRED_SECTIONS hard-filter at the normalize loop), so a frontmatter
    `working_dir:` is silently discarded and `.working_dir` does not exist.

GREEN only once the fix lands:
  - PlanningBrief gains `working_dir: str | None = None`.
  - The normalize loop keeps `working_dir` (via a LOCAL set / inline check inside
    load_brief — NOT a new module-level constant).
  - load_brief pulls `working_dir=fm_normalized.get('working_dir')` and passes it
    to the PlanningBrief(...) constructor.

Hermetic: builds a brief markdown string with frontmatter in tmp_path and calls
load_brief. No subprocesses, no real spawns.
"""
import pytest

from harness.planner import load_brief, PlanningBrief


def _write_brief(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# A brief whose frontmatter declares all required sections, used as the body for
# the positive/negative working_dir cases below.
_REQUIRED_FM = """\
title: External Target Project
scope: Do the thing in the external repo.
non_goals: Do not touch the harness.
inputs: Some external sources.
deliverables: A patched external module.
"""


def test_working_dir_field_is_loaded_from_frontmatter(tmp_path):
    """RED on HEAD: frontmatter working_dir must surface as PlanningBrief.working_dir."""
    target = "/some/abs/path/to/external/repo"
    text = "---\n" + _REQUIRED_FM + f"working_dir: {target}\n" + "---\n"
    brief_path = _write_brief(tmp_path, "with_wd.md", text)

    brief = load_brief(brief_path)

    assert isinstance(brief, PlanningBrief)
    # On HEAD this attribute does not exist -> AttributeError; once the field is
    # added the value must be the declared frontmatter path.
    assert brief.working_dir == target, (
        f"expected working_dir={target!r}, got {getattr(brief, 'working_dir', '<MISSING ATTR>')!r}"
    )


def test_working_dir_defaults_to_none_when_absent(tmp_path):
    """Absent working_dir => fail-safe-to-self default of None; required fields intact."""
    text = "---\n" + _REQUIRED_FM + "---\n"
    brief_path = _write_brief(tmp_path, "no_wd.md", text)

    brief = load_brief(brief_path)

    # fail-safe-to-self default
    assert getattr(brief, "working_dir", "<MISSING ATTR>") is None, (
        "absent working_dir must default to None (fail-safe-to-self)"
    )
    # regression guard: all existing required fields still load unchanged
    assert brief.title == "External Target Project"
    assert brief.scope == "Do the thing in the external repo."
    assert brief.non_goals == "Do not touch the harness."
    assert brief.inputs == "Some external sources."
    assert brief.deliverables == "A patched external module."


def test_working_dir_is_frontmatter_only_not_a_markdown_section(tmp_path):
    """A '# Working Dir' markdown heading must NOT populate working_dir (frontmatter-only)."""
    text = (
        "---\n" + _REQUIRED_FM + "---\n"
        "# Working Dir\n"
        "/should/be/ignored\n"
    )
    brief_path = _write_brief(tmp_path, "md_wd.md", text)

    brief = load_brief(brief_path)

    # markdown heading is not a recognized section -> working_dir stays None
    assert getattr(brief, "working_dir", "<MISSING ATTR>") is None, (
        "a markdown '# Working Dir' section must not set working_dir (frontmatter-only)"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
