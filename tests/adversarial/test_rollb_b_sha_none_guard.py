"""Adversarial oracle for ROLLB_B (rev12 finding F5).

``_rollback_rejected_commit`` falls through to ``git reset --hard HEAD~1`` when
called with ``sha=None``: the ``if sha and head_sha != sha:`` revert branch is
skipped and control reaches the legacy reset path, destroying the parent's actual
latest commit even though this worker committed nothing. The fix adds an early
guard that returns when ``sha`` is falsy, BEFORE the reset path.

RED on HEAD: test 1 fails (HEAD gets rewound to HEAD~1).
GREEN after the fix: test 1 passes (HEAD unchanged when sha=None).
Test 2 is a narrowness/positive control: when sha == HEAD the legacy reset path
must still rewind to HEAD~1 (the guard only affects the sha=None case).
"""

from __future__ import annotations

import pathlib
import subprocess

from harness.orchestrator import _rollback_rejected_commit


def _git(repo: pathlib.Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@t.t",
            "-c",
            "user.name=t",
            *args,
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _init_repo_two_commits(tmp_path: pathlib.Path) -> pathlib.Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "base.txt").write_text("base\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "first")
    (repo / "second.txt").write_text("second\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "second")
    return repo


def test_rollback_sha_none_does_not_reset_head(tmp_path):
    """sha=None must NOT rewind HEAD (no commit was made by this worker)."""
    repo = _init_repo_two_commits(tmp_path)
    head_before = _git(repo, "rev-parse", "HEAD")

    _rollback_rejected_commit(repo, None, "somefile.py", "task_x", "test_kind")

    head_after = _git(repo, "rev-parse", "HEAD")
    assert head_after == head_before, (
        "sha=None rollback destroyed the parent's latest commit via HEAD~1 reset"
    )
    # The 2nd commit's file must still be present in the worktree.
    assert (repo / "second.txt").exists(), "second commit's tree was destroyed"


def test_rollback_sha_matches_head_still_resets(tmp_path):
    """Positive control: sha == HEAD must still rewind to HEAD~1 (legacy path)."""
    repo = _init_repo_two_commits(tmp_path)
    first_sha = _git(repo, "rev-parse", "HEAD~1")
    head_sha = _git(repo, "rev-parse", "HEAD")

    _rollback_rejected_commit(repo, head_sha, "second.txt", "task_y", "test_kind")

    head_after = _git(repo, "rev-parse", "HEAD")
    assert head_after == first_sha, (
        "legitimate self-commit rollback (sha==HEAD) no longer resets to HEAD~1"
    )
