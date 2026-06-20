"""Regression: pin the ACTUAL load_brief behavior for an inside-the-repo
``working_dir`` (README §4.1 frontmatter-keys-table audit, Agent C).

The README frontmatter table previously claimed: "If it resolves *inside* the
repo but is not the repo root, the brief is rejected." That is NOT what
``load_brief`` does. The guard at ``brief_loader.py`` is::

    if _inside and (not _target_is_self(working_dir)):
        raise BriefValidationError(...)

but ``harness.paths._target_is_self`` returns True for ANY path that is the
repo root, a parent of it, OR a subdirectory of it (plus STATE_DIR /
agent_workroot). So for every path satisfying ``_inside`` (== repo root or a
subdir of the repo), ``_target_is_self`` is also True, and the raise NEVER
fires. The guard is dead for its documented purpose: an inside-not-root
``working_dir`` is ACCEPTED, not rejected.

These tests pin the real behavior so doc and code agree. If a future change
actually makes load_brief reject an inside-not-root working_dir, update the
README §4.1 table in the same change and flip the assertions here.
"""
from pathlib import Path

import pytest

from harness.planner import load_brief, PlanningBrief
from harness.planner.brief_loader import BriefValidationError
from harness.paths import PROJECT_ROOT


_BODY = """\
# Title
T
# Scope
S
# Inputs
I
# Non-Goals
integration NG
# Deliverables
D
"""


def _write(tmp_path: Path, working_dir: str) -> Path:
    p = tmp_path / "brief_hooks_x.md"
    p.write_text(f'---\nworking_dir: "{working_dir}"\n---\n' + _BODY, encoding="utf-8")
    return p


def test_working_dir_inside_repo_subdir_is_accepted_not_rejected(tmp_path):
    """A working_dir strictly INSIDE the repo (e.g. <root>/harness) loads
    cleanly — it is NOT rejected, contrary to older README wording."""
    inside = str(PROJECT_ROOT / "harness")
    brief = load_brief(_write(tmp_path, inside))
    assert isinstance(brief, PlanningBrief)
    assert brief.working_dir == inside


def test_working_dir_repo_root_is_accepted(tmp_path):
    """working_dir == the repo root (explicit self-build) loads cleanly."""
    root = str(PROJECT_ROOT)
    brief = load_brief(_write(tmp_path, root))
    assert brief.working_dir == root


def test_working_dir_external_path_is_accepted_by_loader(tmp_path):
    """An external (outside-repo) working_dir is accepted by load_brief — the
    external-roots allowlist is enforced later, at bootstrap, not here."""
    ext = "/tmp/some_external_target_repo"
    brief = load_brief(_write(tmp_path, ext))
    assert brief.working_dir == ext


def test_decorated_required_heading_fails_validation(tmp_path):
    """README §4.1 'Heading gotcha': a decorated heading like
    `# Inputs (do not rebuild)` does NOT normalize to `inputs`, so the brief is
    rejected as MISSING that required section."""
    body = _BODY.replace("# Inputs", "# Inputs (do not rebuild)")
    p = tmp_path / "brief_hooks_decor.md"
    p.write_text(body, encoding="utf-8")
    with pytest.raises(BriefValidationError) as ei:
        load_brief(p)
    assert "inputs" in ei.value.missing


def test_bare_required_heading_case_and_dash_insensitive(tmp_path):
    """The five bare headings match case/`-`/space-insensitively
    (`# non-goals` -> non_goals, `# inputs` -> inputs)."""
    body = _BODY.replace("# Inputs", "# inputs").replace("# Non-Goals", "# non-goals")
    p = tmp_path / "brief_hooks_bare.md"
    p.write_text(body, encoding="utf-8")
    brief = load_brief(p)
    assert brief.inputs == "I"
    assert brief.non_goals == "integration NG"
