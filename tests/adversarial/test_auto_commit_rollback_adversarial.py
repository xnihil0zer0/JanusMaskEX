"""Adversarial battery for rollback / verification in the auto-commit path.

Plan: adversarial_test_plans/02_apply_commit_validation_fuzzing.md §F (F1-F3).
Targets orchestrator._auto_commit_accepted verification gating and
_rollback_rejected_commit's peer-commit-safe rollback (INV-6).

No agents. Staging-worktree helpers are stubbed so commit_accepted_output runs
directly against the tmp repo; verification subprocess runs real /bin/bash.
"""
from __future__ import annotations

import json
import os
import subprocess

import pytest

import harness.orchestrator as orch


def _git(args, cwd):
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "t")
    env.setdefault("GIT_AUTHOR_EMAIL", "t@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "t")
    env.setdefault("GIT_COMMITTER_EMAIL", "t@example.com")
    return subprocess.run(["git", *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True, env=env)


@pytest.fixture
def tmp_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "state" / "output").mkdir(parents=True)
    (repo / "pkg" / "mod.py").write_text("def f():\n    return 1\n")
    _git(["init", "-q", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "init"], repo)
    return repo


@pytest.fixture
def real_staging(tmp_repo, monkeypatch):
    """Use a REAL sibling staging worktree (as production does). The commit
    lands in staging, not the parent; _auto_commit_accepted does NOT merge
    back, so we assert on the return value + parent-side ledger, and verify
    the staging worktree is removed after a rejection."""
    monkeypatch.setattr(orch, "_mark_processed", lambda *a, **k: None)
    return tmp_repo


def _head_count(repo):
    return int(_git(["rev-list", "--count", "HEAD"], repo).stdout.strip())


def _staging_dir(repo):
    return repo.parent / f"{repo.name}_staging"


# --------------------------------------------------------------------------- #
# F1 — verification_command missing -> rollback + ledger row + returns False
# --------------------------------------------------------------------------- #
class TestF1MissingVerification:
    def test_missing_vcmd_rolls_back_and_ledgers(self, real_staging):
        repo = real_staging
        sd = repo / "state"
        (sd / "output" / "F1.py").write_text("def f():\n    return 2\n")
        parent_before = _head_count(repo)
        task = {"task_id": "F1", "files_touched": ["pkg/mod.py"]}  # no verification_command
        ok = orch._auto_commit_accepted(sd, task, "F1")
        assert ok is False
        # parent HEAD untouched (commit happened in staging, then rolled back)
        assert _head_count(repo) == parent_before
        # staging worktree removed after the rejection
        assert not _staging_dir(repo).exists(), "staging not cleaned up after reject"
        # ledger row appended in parent state_dir
        ledger = sd / "impl_progress.jsonl"
        assert ledger.exists()
        rows = [json.loads(ln) for ln in ledger.read_text().splitlines() if ln.strip()]
        assert any(r.get("event") == "verification_missing" for r in rows), rows


# --------------------------------------------------------------------------- #
# F3 — verification non-zero exit -> rollback + verification_failed ledger row
# --------------------------------------------------------------------------- #
class TestF3FailingVerification:
    def test_false_vcmd_rolls_back_and_ledgers(self, real_staging):
        repo = real_staging
        sd = repo / "state"
        (sd / "output" / "F3.py").write_text("def f():\n    return 3\n")
        task = {"task_id": "F3", "files_touched": ["pkg/mod.py"],
                "verification_command": "false"}
        ok = orch._auto_commit_accepted(sd, task, "F3")
        assert ok is False
        assert not _staging_dir(repo).exists(), "staging not cleaned up after reject"
        ledger = sd / "impl_progress.jsonl"
        rows = [json.loads(ln) for ln in ledger.read_text().splitlines() if ln.strip()]
        assert any(r.get("event") == "verification_failed" for r in rows), rows

    def test_true_vcmd_commits_in_staging_and_returns_true(self, real_staging):
        repo = real_staging
        sd = repo / "state"
        (sd / "output" / "F3OK.py").write_text("def f():\n    return 7\n")
        task = {"task_id": "F3OK", "files_touched": ["pkg/mod.py"],
                "verification_command": "true"}
        ok = orch._auto_commit_accepted(sd, task, "F3OK")
        assert ok is True, "passing verification should keep the commit"
        # An 'accepted' ledger row is written on success.
        ledger = sd / "impl_progress.jsonl"
        rows = [json.loads(ln) for ln in ledger.read_text().splitlines() if ln.strip()]
        assert any(r.get("phase") == "accepted" and r.get("event") == "auto_commit"
                   for r in rows), rows


# --------------------------------------------------------------------------- #
# F2 — _rollback_rejected_commit does not clobber a peer commit (INV-6)
# --------------------------------------------------------------------------- #
class TestF2PeerCommitPreserved:
    def test_revert_used_when_peer_landed_on_top(self, tmp_repo):
        repo = tmp_repo
        # This worker commits change S to pkg/mod.py.
        (repo / "pkg" / "mod.py").write_text("def f():\n    return 2\n")
        _git(["add", "pkg/mod.py"], repo)
        _git(["commit", "-qm", "worker S"], repo)
        sha_s = _git(["rev-parse", "HEAD"], repo).stdout.strip()
        # A peer worker commits a DIFFERENT file on top, so HEAD != S.
        (repo / "pkg" / "peer.py").write_text("peer = 1\n")
        _git(["add", "pkg/peer.py"], repo)
        _git(["commit", "-qm", "peer commit"], repo)
        # Now roll back S. Because HEAD != S, it must `git revert S`, NOT reset.
        orch._rollback_rejected_commit(repo, sha_s, "pkg/mod.py", "T", "verification_failed")
        # Peer commit's file survives.
        assert (repo / "pkg" / "peer.py").exists(), "peer commit clobbered by rollback"
        # S's change is reverted: pkg/mod.py back to return 1.
        assert (repo / "pkg" / "mod.py").read_text() == "def f():\n    return 1\n", (
            "worker S's change was not reverted")

    def test_reset_used_when_worker_commit_is_tip(self, tmp_repo):
        repo = tmp_repo
        (repo / "pkg" / "mod.py").write_text("def f():\n    return 9\n")
        _git(["add", "pkg/mod.py"], repo)
        _git(["commit", "-qm", "worker tip"], repo)
        sha = _git(["rev-parse", "HEAD"], repo).stdout.strip()
        before = _head_count(repo)
        orch._rollback_rejected_commit(repo, sha, "pkg/mod.py", "T", "verification_failed")
        # HEAD==sha path -> reset --hard HEAD~1 -> count drops by 1
        assert _head_count(repo) == before - 1
        assert (repo / "pkg" / "mod.py").read_text() == "def f():\n    return 1\n"
