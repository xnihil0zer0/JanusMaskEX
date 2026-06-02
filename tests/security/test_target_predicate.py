import os
from pathlib import Path
import pytest
from harness.paths import _target_is_self, effective_target_root
import harness.paths as P


def test_target_is_self_exact_project_root():
    assert _target_is_self(str(P.PROJECT_ROOT)) is True
    assert _target_is_self(P.PROJECT_ROOT) is True


def test_target_is_self_none_or_empty_or_absent():
    assert _target_is_self(None) is True
    assert _target_is_self("") is True
    assert _target_is_self() is True


def test_target_is_self_external_dir(tmp_path):
    resolved_tmp = tmp_path.resolve()
    assert _target_is_self(resolved_tmp) is False
    assert effective_target_root(resolved_tmp) == resolved_tmp


def test_effective_target_root_self():
    assert effective_target_root(P.PROJECT_ROOT) == P.PROJECT_ROOT
    assert effective_target_root(None) == P.PROJECT_ROOT
    assert effective_target_root("") == P.PROJECT_ROOT


def test_target_is_self_dotdot_traversal():
    traversal_path = str(P.PROJECT_ROOT / "harness" / "..")
    assert _target_is_self(traversal_path) is True
    assert effective_target_root(traversal_path) == P.PROJECT_ROOT


def test_target_is_self_symlinks(tmp_path):
    link1 = tmp_path / "link"
    link2 = tmp_path / "link2"
    
    link1.symlink_to(P.PROJECT_ROOT)
    link2.symlink_to(P.PROJECT_ROOT / "harness")
    
    assert _target_is_self(link1) is True
    assert _target_is_self(link2) is True
    
    assert effective_target_root(link1) == P.PROJECT_ROOT
    assert effective_target_root(link2) == P.PROJECT_ROOT


def test_target_is_self_parent_of_repo():
    parent_path = str(P.PROJECT_ROOT.parent)
    assert _target_is_self(parent_path) is True
    assert effective_target_root(parent_path) == P.PROJECT_ROOT


def test_target_is_self_inside_state_dir():
    assert _target_is_self(str(P.STATE_DIR)) is True
    assert _target_is_self(str(P.STATE_DIR / "anything")) is True
    assert effective_target_root(str(P.STATE_DIR / "anything")) == P.PROJECT_ROOT


def test_target_is_self_inside_agent_workroot(tmp_path, monkeypatch):
    workroot = tmp_path / "workroot"
    workroot.mkdir()
    
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(workroot))
    
    assert P.agent_workroot().resolve() == workroot.resolve()
    
    inside_path = workroot / "agent1" / "session1"
    inside_path.mkdir(parents=True, exist_ok=True)
    
    assert _target_is_self(inside_path) is True
    assert effective_target_root(inside_path) == P.PROJECT_ROOT


def test_target_is_self_failsafe_on_exception(monkeypatch):
    def mock_resolve(*args, **kwargs):
        raise OSError("Simulated resolution error")
    
    monkeypatch.setattr(Path, "resolve", mock_resolve)
    
    assert _target_is_self("/some/external/path") is True
    assert effective_target_root("/some/external/path") == P.PROJECT_ROOT
