"""Adversarial oracle for PHASE_WHOLE_FILE_DRIFT_GUARD.

Drives the REAL harness.git_integration.commit_accepted_output through the
LEGACY whole-file merge path (no patches.json / files.json sidecar) and asserts
the AST-node-set drift guard:

  - Test A (RED on HEAD): a whole-file submission that structurally changes BOTH
    top-level functions (foo AND bar) must be REJECTED fail-closed
    (committed=False, error starts 'whole_file_drift:', target file unchanged on
    disk). HEAD has no guard, so HEAD commits it -> Test A FAILS on HEAD.
  - Test B (positive control, GREEN both): a whole-file submission that changes
    ONLY foo's body (bar byte-identical) commits as today -> committed=True.
  - Test C (positive control): a whole-file submission that changes only foo's
    body (one AST change) is not blocked.

Setup is modelled on tests/adversarial/test_git_integration_acceptance_adversarial.py
(temp git repo + state/output/<task_id>.py + tracked .py target).
"""

from __future__ import annotations

import concurrent.futures
import os
import pathlib
import subprocess

import pytest

from harness.git_integration import commit_accepted_output


def _resolve(result):
    if isinstance(result, concurrent.futures.Future):
        return result.result(timeout=10)
    return result


def _git(cwd: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "t")
    env.setdefault("GIT_AUTHOR_EMAIL", "t@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "t")
    env.setdefault("GIT_COMMITTER_EMAIL", "t@example.com")
    return subprocess.run(
        ["git", *args], cwd=str(cwd), env=env, check=True,
        capture_output=True, text=True,
    )


# Target with TWO top-level functions, each with a distinct body + comment.
_TARGET_SRC = (
    "def foo():\n"
    "    # foo original\n"
    "    return 1\n"
    "\n"
    "\n"
    "def bar():\n"
    "    # bar original\n"
    "    return 2\n"
)


@pytest.fixture
def git_worktree(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "wt"
    root.mkdir()
    _git(root, "init", "-b", "main", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "commit", "--allow-empty", "-m", "root")
    return root


@pytest.fixture
def state_dir(git_worktree: pathlib.Path) -> pathlib.Path:
    sd = git_worktree / "state"
    (sd / "output").mkdir(parents=True)
    return sd


@pytest.fixture
def seed_target(git_worktree: pathlib.Path) -> pathlib.Path:
    t = git_worktree / "mod.py"
    t.write_text(_TARGET_SRC)
    _git(git_worktree, "add", "mod.py")
    _git(git_worktree, "commit", "-m", "seed")
    return t


def _assert_legacy_merge_path(state_dir: pathlib.Path, task_id: str) -> None:
    """Guard against silently dispatching to the sidecar branches: the legacy
    singular merge path requires NO files.json / patches.json sidecar to exist.
    """
    assert not (state_dir / "output" / f"{task_id}.files.json").exists()
    assert not (state_dir / "output" / f"{task_id}.patches.json").exists()


def test_two_symbol_whole_file_change_rejected(
    state_dir: pathlib.Path, seed_target: pathlib.Path
) -> None:
    """Test A (RED on HEAD): whole-file output changes BOTH foo and bar bodies.

    On HEAD this commits (no guard) -> this test FAILS on HEAD.
    After the fix: committed=False, error startswith 'whole_file_drift:',
    target file UNCHANGED on disk.
    """
    task_id = "WFDRIFT_A"
    out_code = (
        "def foo():\n"
        "    # foo changed\n"
        "    return 100\n"
        "\n"
        "\n"
        "def bar():\n"
        "    # bar changed\n"
        "    return 200\n"
    )
    (state_dir / "output" / f"{task_id}.py").write_text(out_code)
    _assert_legacy_merge_path(state_dir, task_id)

    before_disk = seed_target.read_text()
    result = _resolve(commit_accepted_output(task_id, str(seed_target), state_dir))

    assert result["committed"] is False, result
    assert isinstance(result["error"], str) and result["error"].startswith(
        "whole_file_drift:"
    ), result["error"]
    assert result["sha"] is None
    # Fail-closed: target untouched on disk.
    assert seed_target.read_text() == before_disk


def test_single_symbol_whole_file_change_allowed(
    state_dir: pathlib.Path, seed_target: pathlib.Path, git_worktree: pathlib.Path
) -> None:
    """Test B (GREEN both): whole-file output changes ONLY foo (bar byte-identical
    to target) -> single top-level symbol changed -> committed=True.
    """
    task_id = "WFDRIFT_B"
    out_code = (
        "def foo():\n"
        "    # foo changed\n"
        "    return 100\n"
        "\n"
        "\n"
        "def bar():\n"
        "    # bar original\n"
        "    return 2\n"
    )
    (state_dir / "output" / f"{task_id}.py").write_text(out_code)
    _assert_legacy_merge_path(state_dir, task_id)

    result = _resolve(commit_accepted_output(task_id, str(seed_target), state_dir))

    assert result["committed"] is True, result
    assert result["error"] is None
    assert isinstance(result["sha"], str) and len(result["sha"]) == 40
    # foo changed, bar preserved in the committed file.
    committed = seed_target.read_text()
    assert "return 100" in committed
    assert "return 2" in committed


def test_only_one_body_changed_not_blocked(
    state_dir: pathlib.Path, seed_target: pathlib.Path
) -> None:
    """Test C (positive control): exactly one top-level symbol (foo) changes its
    body while bar stays semantically identical -> guard allows commit.
    """
    task_id = "WFDRIFT_C"
    out_code = (
        "def foo():\n"
        "    # foo edited only\n"
        "    x = 5\n"
        "    return x\n"
        "\n"
        "\n"
        "def bar():\n"
        "    # bar original\n"
        "    return 2\n"
    )
    (state_dir / "output" / f"{task_id}.py").write_text(out_code)
    _assert_legacy_merge_path(state_dir, task_id)

    result = _resolve(commit_accepted_output(task_id, str(seed_target), state_dir))

    assert result["committed"] is True, result
    assert result["error"] is None
