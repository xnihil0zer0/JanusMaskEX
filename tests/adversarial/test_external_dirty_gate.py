"""Adversarial oracle for the external dirty gate capability (REV23 §3-2).

Covers:
* External task, dirty external repo -> refuses with RuntimeError containing 'EXTERNAL_DIRTY_GATE', create_staging_worktree not called.
* External task, clean external repo -> proceeds (reaches create_staging_worktree).
* Self task, dirty repo -> proceeds (reaches create_staging_worktree without running the dirty check).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
import pytest

import harness.paths
from harness import git_integration
from harness import orchestrator
import harness.target_bootstrap


class ReachedStaging(BaseException):
    pass


def create_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(path), check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(path), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(path), check=True)
    
    # We must have at least one commit so git is in a clean state with a commit
    dummy = path / "dummy.txt"
    dummy.write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "dummy.txt"], cwd=str(path), check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(path), check=True)


def make_dirty(path: Path) -> None:
    dirty_file = path / "dirty.txt"
    dirty_file.write_text("dirty content", encoding="utf-8")


def test_external_dirty_gate_dirty(tmp_path, monkeypatch):
    # Setup external repo (dirty)
    ext_repo = tmp_path / "external_repo"
    create_git_repo(ext_repo)
    make_dirty(ext_repo)

    # Setup self repo (so rev-parse doesn't fail if called, though it shouldn't be for external)
    self_repo = tmp_path / "self_repo"
    create_git_repo(self_repo)
    state_dir = self_repo / "state"
    state_dir.mkdir()

    # Monkeypatch paths
    monkeypatch.setattr(harness.paths, "_target_is_self", lambda wd: wd == "self")
    monkeypatch.setattr(harness.paths, "effective_target_root", lambda wd: str(ext_repo))

    # Spy on create_staging_worktree
    calls = []
    def mock_create_staging_worktree(staging_path, parent_root):
        calls.append((staging_path, parent_root))
        raise ReachedStaging()
    monkeypatch.setattr(git_integration, "create_staging_worktree", mock_create_staging_worktree)

    # Resolve files touched
    monkeypatch.setattr(harness.orchestrator, "_resolve_files_touched", lambda state_dir, task, task_id: ["dummy.py"])

    # Monkeypatch external_staging_root
    ext_staging = tmp_path / "external_staging"
    ext_staging.mkdir()
    monkeypatch.setattr(harness.target_bootstrap, "external_staging_root", lambda: ext_staging)

    task = {"working_dir": "external"}
    task_id = "test_dirty"

    with pytest.raises(RuntimeError) as exc_info:
        orchestrator._auto_commit_accepted(state_dir, task, task_id)

    assert "EXTERNAL_DIRTY_GATE" in str(exc_info.value)
    assert len(calls) == 0, "create_staging_worktree should NOT be called for a dirty external repo"


def test_external_dirty_gate_clean(tmp_path, monkeypatch):
    # Setup external repo (clean)
    ext_repo = tmp_path / "external_repo"
    create_git_repo(ext_repo)

    # Setup self repo
    self_repo = tmp_path / "self_repo"
    create_git_repo(self_repo)
    state_dir = self_repo / "state"
    state_dir.mkdir()

    # Monkeypatch paths
    monkeypatch.setattr(harness.paths, "_target_is_self", lambda wd: wd == "self")
    monkeypatch.setattr(harness.paths, "effective_target_root", lambda wd: str(ext_repo))

    # Spy on create_staging_worktree
    calls = []
    def mock_create_staging_worktree(staging_path, parent_root):
        calls.append((staging_path, parent_root))
        raise ReachedStaging()
    monkeypatch.setattr(git_integration, "create_staging_worktree", mock_create_staging_worktree)

    # Resolve files touched
    monkeypatch.setattr(harness.orchestrator, "_resolve_files_touched", lambda state_dir, task, task_id: ["dummy.py"])

    # Monkeypatch external_staging_root
    ext_staging = tmp_path / "external_staging"
    ext_staging.mkdir()
    monkeypatch.setattr(harness.target_bootstrap, "external_staging_root", lambda: ext_staging)

    task = {"working_dir": "external"}
    task_id = "test_clean"

    # Should NOT refuse, should reach create_staging_worktree and raise ReachedStaging
    with pytest.raises(ReachedStaging):
        orchestrator._auto_commit_accepted(state_dir, task, task_id)

    assert len(calls) == 1


def test_external_dirty_gate_self_dirty(tmp_path, monkeypatch):
    # Setup self repo (make it dirty)
    self_repo = tmp_path / "self_repo"
    create_git_repo(self_repo)
    make_dirty(self_repo)
    state_dir = self_repo / "state"
    state_dir.mkdir()

    # Monkeypatch paths
    monkeypatch.setattr(harness.paths, "_target_is_self", lambda wd: wd == "self")
    # effective_target_root shouldn't be called, but we can set it to None just in case
    monkeypatch.setattr(harness.paths, "effective_target_root", lambda wd: None)

    # Spy on create_staging_worktree
    calls = []
    def mock_create_staging_worktree(staging_path, parent_root):
        calls.append((staging_path, parent_root))
        raise ReachedStaging()
    monkeypatch.setattr(git_integration, "create_staging_worktree", mock_create_staging_worktree)

    # Resolve files touched
    monkeypatch.setattr(harness.orchestrator, "_resolve_files_touched", lambda state_dir, task, task_id: ["dummy.py"])

    task = {"working_dir": "self"}
    task_id = "test_self_dirty"

    # Should NOT refuse, should reach create_staging_worktree and raise ReachedStaging
    with pytest.raises(ReachedStaging):
        orchestrator._auto_commit_accepted(state_dir, task, task_id)

    assert len(calls) == 1
