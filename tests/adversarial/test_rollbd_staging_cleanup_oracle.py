"""ROLLB-D (STAGING_CLEANUP_GUARANTEE) crash-safety oracle.

Targets ``harness.orchestrator._auto_commit_accepted``. The function creates a
task-scoped sibling staging worktree (ROLLB-A:
``{root.name}_{task_id}_staging``) at the top of its body, then runs commit /
verification / mutation-gate / merge. Every EXPLICIT reject path
(verification_missing / verification_failed / verification_sandbox_error /
mutation_gate_*) and the success path (via ``merge_staging_to_parent``) already
remove the staging worktree. But:

  * the SEC-3 disabled-sandbox ``FileNotFoundError`` *re-raise* path, and
  * ANY unexpected exception raised between staging-creation and a clean exit
    (e.g. ``commit_accepted_output`` raising on an index.lock race / OSError),

propagate OUT of ``_auto_commit_accepted`` with the staging worktree LEAKED on
disk and registered in ``git worktree list``. ROLLB-D wraps the post-creation
body in ``try: ... finally: remove_staging_worktree(...)`` so the worktree is
ALWAYS torn down.

This oracle is NON-VACUOUS: it forces an unexpected exception mid-body (by
monkeypatching ``commit_accepted_output`` to raise) and a SEC-3 disabled-sandbox
FileNotFoundError, then asserts (a) the exception still propagates (behavior
preserved) AND (b) the staging worktree directory is gone and no longer in
``git worktree list``. On HEAD both assertions on cleanup FAIL (RED) because
there is no ``finally``; with the ROLLB-D wrapper they PASS (GREEN).

No agents. Uses a real tmp git repo + real sibling staging worktree.
"""
from __future__ import annotations

import json
import os
import subprocess

import pytest

import harness.orchestrator as orch
from harness import agent_jail
from harness import git_integration


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


def _staging_dir(repo, task_id):
    # ROLLB-A task-scoped staging sibling path.
    return repo.parent / f"{repo.name}_{task_id}_staging"


def _staging_in_worktree_list(repo, staging_path):
    out = _git(["worktree", "list", "--porcelain"], repo).stdout
    target = str(staging_path.resolve())
    for line in out.splitlines():
        if line.startswith("worktree "):
            if os.path.realpath(line[len("worktree "):].strip()) == os.path.realpath(target):
                return True
    return False


class TestRollbDUnexpectedExceptionCleansStaging:
    """An unexpected exception mid-body must NOT leak the staging worktree."""

    def test_commit_raises_unexpected_still_cleans_staging(self, tmp_repo, monkeypatch):
        repo = tmp_repo
        sd = repo / "state"
        task_id = "ROLLBD_BOOM"
        (sd / "output" / f"{task_id}.py").write_text("def f():\n    return 2\n")
        task = {"task_id": task_id, "files_touched": ["pkg/mod.py"],
                "verification_command": "true"}

        # commit_accepted_output is called AFTER the staging worktree is created
        # (ROLLB-A). Force an unexpected, non-handled exception there to simulate
        # an index.lock race / OSError mid-commit. On HEAD this escapes the
        # function with the staging worktree leaked.
        def _boom(*a, **k):
            raise RuntimeError("simulated mid-commit crash (index.lock race)")
        monkeypatch.setattr(git_integration, "commit_accepted_output", _boom)
        monkeypatch.setattr(orch, "_mark_processed", lambda *a, **k: None)

        staging = _staging_dir(repo, task_id)
        with pytest.raises(RuntimeError, match="simulated mid-commit crash"):
            orch._auto_commit_accepted(sd, task, task_id)

        # Behavior preserved: the exception propagated. ROLLB-D crash-safety:
        # the staging worktree must be removed despite the raise.
        assert not staging.exists(), (
            "ROLLB-D: staging worktree dir leaked after an unexpected exception")
        assert not _staging_in_worktree_list(repo, staging), (
            "ROLLB-D: staging worktree still registered in git worktree list "
            "after an unexpected exception")


class TestRollbDSec3DisabledSandboxRaiseCleansStaging:
    """SEC-3 disabled-sandbox FileNotFoundError re-raise must not leak staging."""

    def test_disabled_sandbox_fnf_reraise_cleans_staging(self, tmp_repo, monkeypatch):
        repo = tmp_repo
        sd = repo / "state"
        task_id = "ROLLBD_FNF"
        (sd / "output" / f"{task_id}.py").write_text("def f():\n    return 3\n")
        task = {"task_id": task_id, "files_touched": ["pkg/mod.py"],
                "verification_command": "true"}

        # Sandbox DISABLED -> the verify subprocess runs unjailed (shell=True).
        # A FileNotFoundError raised by the verify subprocess.run is re-raised
        # (SEC-3 only swallows it when sandboxing is ENABLED). The commit has
        # already landed in staging, so on HEAD this re-raise leaks the worktree.
        # agent_jail is imported function-locally inside _auto_commit_accepted,
        # so patch the source module attribute it resolves at call time.
        monkeypatch.setattr(agent_jail, "sandbox_enabled", lambda *a, **k: False)
        monkeypatch.setattr(orch, "_mark_processed", lambda *a, **k: None)

        real_run = subprocess.run

        def _fnf_on_verify(*a, **k):
            # Only the verify call uses shell=True; let all git subprocesses run.
            if k.get("shell") and k.get("executable") == "/bin/bash":
                raise FileNotFoundError("simulated missing /bin/bash on verify")
            return real_run(*a, **k)
        # subprocess is imported function-locally in _auto_commit_accepted, so
        # patch the global subprocess.run that the local `import subprocess`
        # re-binds to. The filter lets every git subprocess run normally and
        # only fails the shell=True /bin/bash verify call.
        monkeypatch.setattr(subprocess, "run", _fnf_on_verify)

        staging = _staging_dir(repo, task_id)
        with pytest.raises(FileNotFoundError, match="simulated missing"):
            orch._auto_commit_accepted(sd, task, task_id)

        assert not staging.exists(), (
            "ROLLB-D: staging worktree dir leaked after SEC-3 disabled-sandbox "
            "FileNotFoundError re-raise")
        assert not _staging_in_worktree_list(repo, staging), (
            "ROLLB-D: staging worktree still registered in git worktree list "
            "after SEC-3 disabled-sandbox FileNotFoundError re-raise")


class TestRollbDHappyPathStillMergesAndCleans:
    """Regression guard: the finally must NOT break the success path."""

    def test_success_path_merges_and_removes_staging(self, tmp_repo, monkeypatch):
        repo = tmp_repo
        sd = repo / "state"
        task_id = "ROLLBD_OK"
        # A real accepted output that differs from HEAD so a commit is produced.
        (sd / "output" / f"{task_id}.py").write_text(
            "def f():\n    return 1\n\n\ndef g():\n    return 9\n")
        task = {"task_id": task_id, "files_touched": ["pkg/mod.py"],
                "verification_command": "python -c \"import sys; sys.exit(0)\""}
        monkeypatch.setattr(orch, "perform_process_handover", lambda *a, **k: None)

        staging = _staging_dir(repo, task_id)
        ok = orch._auto_commit_accepted(sd, task, task_id)
        assert ok is True, "success path must still accept"
        # merge_staging_to_parent advanced the parent HEAD.
        head_count = int(_git(["rev-list", "--count", "HEAD"], repo).stdout.strip())
        assert head_count == 2, "parent HEAD must have the merged commit"
        # staging removed (by merge; finally is a harmless no-op).
        assert not staging.exists(), "staging worktree must be removed on success"
        assert not _staging_in_worktree_list(repo, staging)
