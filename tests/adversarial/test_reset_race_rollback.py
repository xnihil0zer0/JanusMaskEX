"""Adversarial test for G-RESET-RACE.

A rejected auto-commit must NOT destroy a peer worker's commit that landed on top
between this worker's commit and its rollback (the AW3 lock is released before the
verification_command runs). ``_rollback_rejected_commit`` hard-resets only when
this worker's commit is still the tip; otherwise it surgically reverts only this
worker's commit.
"""

from __future__ import annotations

import pathlib
import subprocess

from harness.orchestrator import _rollback_rejected_commit


def _git(repo: pathlib.Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True).stdout.strip()


def _init_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "base.txt").write_text("base\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def test_rollback_hard_resets_when_our_commit_is_tip(tmp_path):
    repo = _init_repo(tmp_path)
    base_sha = _git(repo, "rev-parse", "HEAD")
    # our commit is the tip
    (repo / "ours.py").write_text("OURS = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "our change")
    our_sha = _git(repo, "rev-parse", "HEAD")

    _rollback_rejected_commit(repo, our_sha, "ours.py", "task_ours", "verification_failed")

    # HEAD is back at base; our commit is gone; ours.py removed from the worktree
    assert _git(repo, "rev-parse", "HEAD") == base_sha
    assert not (repo / "ours.py").exists()


def test_rollback_preserves_peer_commit_via_revert(tmp_path):
    repo = _init_repo(tmp_path)
    # our commit
    (repo / "ours.py").write_text("OURS = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "our change")
    our_sha = _git(repo, "rev-parse", "HEAD")
    # a PEER worker commits a DIFFERENT file on top (the race)
    (repo / "peer.py").write_text("PEER = 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "peer change")
    peer_sha = _git(repo, "rev-parse", "HEAD")

    _rollback_rejected_commit(repo, our_sha, "ours.py", "task_ours", "verification_failed")

    # The peer commit MUST survive: peer.py present, peer commit still in history.
    assert (repo / "peer.py").read_text() == "PEER = 2\n", "peer worker's file was destroyed"
    log = _git(repo, "log", "--format=%H")
    assert peer_sha in log.splitlines(), "peer commit was discarded from history"
    # Our change is undone (a revert commit removed ours.py).
    assert not (repo / "ours.py").exists(), "our rejected change was not reverted"
    # HEAD advanced (revert commit), it did not rewind past the peer commit.
    head = _git(repo, "rev-parse", "HEAD")
    assert head != our_sha and head != peer_sha
