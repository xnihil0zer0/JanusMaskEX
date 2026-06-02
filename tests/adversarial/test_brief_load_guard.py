import pytest
from harness.planner import load_brief, PlanningBrief, BriefValidationError
import harness.planner.brief_loader as BL
import harness.paths as P

def _write_brief(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p

_REQUIRED_FM = """\
title: External Target Project
scope: Do the thing in the external repo.
non_goals: Do not touch the harness.
inputs: Some external sources.
deliverables: A patched external module.
"""

def test_inside_root_nonself_working_dir_rejected(tmp_path, monkeypatch):
    working_dir = str(P.PROJECT_ROOT / "harness")
    text = "---\n" + _REQUIRED_FM + f"working_dir: {working_dir}\n" + "---\n"
    brief_path = _write_brief(tmp_path, "inside_nonself.md", text)

    # Monkeypatch so the guard sees False (non-self)
    monkeypatch.setattr("harness.paths._target_is_self", lambda wd: False)

    with pytest.raises(BriefValidationError):
        load_brief(brief_path)

def test_absent_working_dir_loads_as_self(tmp_path):
    text = "---\n" + _REQUIRED_FM + "---\n"
    brief_path = _write_brief(tmp_path, "no_wd.md", text)

    brief = load_brief(brief_path)
    assert isinstance(brief, PlanningBrief)
    assert brief.working_dir is None

def test_external_working_dir_loads(tmp_path):
    working_dir = str(tmp_path / "external_repo")
    text = "---\n" + _REQUIRED_FM + f"working_dir: {working_dir}\n" + "---\n"
    brief_path = _write_brief(tmp_path, "external_wd.md", text)

    brief = load_brief(brief_path)
    assert isinstance(brief, PlanningBrief)
    assert brief.working_dir == working_dir

def test_inside_root_self_working_dir_allowed(tmp_path):
    working_dir = str(P.PROJECT_ROOT)
    text = "---\n" + _REQUIRED_FM + f"working_dir: {working_dir}\n" + "---\n"
    brief_path = _write_brief(tmp_path, "inside_self.md", text)

    brief = load_brief(brief_path)
    assert isinstance(brief, PlanningBrief)
    assert brief.working_dir == working_dir

if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
