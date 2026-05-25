"""Adversarial acceptance battery for harness.git_integration.commit_accepted_output.

Pins the public contract ahead of the T10 orchestrator swap (see
brief_hooks_t5_swap_blueprint.md). Tests are written shape-agnostic so they
pass BOTH against the pre-T9 Future-returning shape and the post-T9 sync-dict
shape — the only load-bearing assertions are on the returned dict.

Test-partner for harness.git_integration (Gate 3 in scripts/impl_pre_write.py).
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import pathlib
import subprocess
import sys

import pytest

from harness.git_integration import commit_accepted_output


def _resolve(result):
    """Accept either a Future or a dict and return the underlying dict.

    Keeps the suite valid across the T9 sync-refactor boundary.
    """
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
    t.write_text("def foo():\n    return 1\n")
    _git(git_worktree, "add", "mod.py")
    _git(git_worktree, "commit", "-m", "seed")
    return t


class TestReturnShape:
    """Dict with the four documented keys, regardless of Future wrapping."""

    def test_return_keys_present_on_error(self, state_dir: pathlib.Path, git_worktree: pathlib.Path) -> None:
        # no output file → error path; still returns full dict
        result = _resolve(commit_accepted_output("MISSING", str(git_worktree / "mod.py"), state_dir))
        assert isinstance(result, dict)
        for key in ("committed", "sha", "error", "target"):
            assert key in result, f"missing key {key!r} in {result!r}"

    def test_target_field_round_trips_input(self, state_dir: pathlib.Path, git_worktree: pathlib.Path) -> None:
        target = str(git_worktree / "mod.py")
        result = _resolve(commit_accepted_output("MISSING", target, state_dir))
        assert result["target"] == target

    def test_committed_is_bool(self, state_dir: pathlib.Path, git_worktree: pathlib.Path) -> None:
        result = _resolve(commit_accepted_output("MISSING", str(git_worktree / "mod.py"), state_dir))
        assert isinstance(result["committed"], bool)


class TestPathValidation:
    """E2, E4: non-python targets rejected; targets escaping worktree rejected."""

    def test_non_python_target_via_copy2_committed(
        self, state_dir: pathlib.Path, git_worktree: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        """Post-F3 (88a70be multifmt-dispatch): non-.py targets are no longer
        rejected; commit_accepted_output uses shutil.copy2 to land the
        output verbatim. Regression guard for the new contract."""
        target = git_worktree / "mod.txt"
        target.write_text("x")
        _git(git_worktree, "add", "mod.txt")
        _git(git_worktree, "commit", "-m", "seed-txt")
        (state_dir / "output" / "T.py").write_text("# replacement\n")
        result = _resolve(commit_accepted_output("T", str(target), state_dir))
        assert result["committed"] is True
        assert result["error"] is None
        assert target.read_text() == "# replacement\n"

    def test_target_outside_worktree_rejected(
        self, state_dir: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        outside = tmp_path / "escape.py"
        outside.write_text("# outside\n")
        (state_dir / "output" / "T.py").write_text("# repl\n")
        result = _resolve(commit_accepted_output("T", str(outside), state_dir))
        assert result["committed"] is False
        assert result["error"] == "target escapes worktree"

    def test_missing_output_file_errors(
        self, state_dir: pathlib.Path, seed_target: pathlib.Path
    ) -> None:
        # do NOT create state/output/NONESUCH.py
        result = _resolve(commit_accepted_output("NONESUCH", str(seed_target), state_dir))
        assert result["committed"] is False
        assert result["error"] == "no output file"


class TestHappyCommit:
    def test_commits_and_returns_sha_on_change(
        self, state_dir: pathlib.Path, seed_target: pathlib.Path, git_worktree: pathlib.Path
    ) -> None:
        (state_dir / "output" / "T.py").write_text("def foo():\n    return 2\n")
        result = _resolve(commit_accepted_output("T", str(seed_target), state_dir))
        assert result["committed"] is True, result
        assert result["error"] is None
        assert isinstance(result["sha"], str) and len(result["sha"]) == 40
        # commit visible in git log
        log = _git(git_worktree, "log", "--oneline", "-1")
        assert "T" in log.stdout

    def test_no_diff_returns_committed_false_no_error_sentinel(
        self, state_dir: pathlib.Path, seed_target: pathlib.Path
    ) -> None:
        # output identical to target -> no staged changes. Post-G18bc
        # (e66f7f4): the silent no-diff branch now emits a 'no_diff:'
        # sentinel string in result['error'] (and a warn log) so callers
        # can discriminate "no work to do" from a genuine merge failure.
        # The committed=False and sha=None invariants are preserved.
        (state_dir / "output" / "T.py").write_text(seed_target.read_text())
        result = _resolve(commit_accepted_output("T", str(seed_target), state_dir))
        assert result["committed"] is False
        assert isinstance(result["error"], str) and result["error"].startswith("no_diff:"), result["error"]
        assert result["sha"] is None

    def test_nested_target_parent_dir_created(
        self, state_dir: pathlib.Path, git_worktree: pathlib.Path
    ) -> None:
        # W70 regression guard: restores inline stopgap's parent.mkdir so
        # future nested targets (e.g. harness/planner/new_submodule.py) do
        # not fail with FileNotFoundError on write_text.
        nested_target = git_worktree / "subdir" / "nested_mod.py"
        assert not nested_target.parent.exists()
        (state_dir / "output" / "NESTED.py").write_text("def bar():\n    return 99\n")
        result = _resolve(commit_accepted_output("NESTED", str(nested_target), state_dir))
        assert result["committed"] is True, result
        assert result["error"] is None
        assert nested_target.exists()
        assert nested_target.parent.exists()
        assert "bar" in nested_target.read_text()
        log = _git(git_worktree, "log", "--oneline", "-1")
        assert "NESTED" in log.stdout


class TestNonGitStateDir:
    def test_non_git_state_dir_returns_error(self, tmp_path: pathlib.Path) -> None:
        sd = tmp_path / "no-git-state"
        (sd / "output").mkdir(parents=True)
        (sd / "output" / "T.py").write_text("x=1\n")
        result = _resolve(commit_accepted_output("T", str(tmp_path / "mod.py"), sd))
        assert result["committed"] is False
        assert result["error"] is not None


class TestHostileTaskId:
    def test_task_id_with_dotdot_does_not_escape_output_dir(
        self, state_dir: pathlib.Path, seed_target: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        # Plant a file outside state/output/ that the traversal would reach.
        evil = tmp_path / "evil.py"
        evil.write_text("def attacker():\n    return 'pwn'\n")
        result = _resolve(commit_accepted_output("../../evil", str(seed_target), state_dir))
        # Either the lookup is normalised to stay inside state/output/ (no-output error),
        # or it fails validation. In neither case should the seeded target be clobbered.
        assert result["committed"] is False
        # Target is untouched (still seeded foo()).
        assert "attacker" not in seed_target.read_text()

    def test_task_id_with_newline_keeps_commit_subject_safe(
        self, state_dir: pathlib.Path, seed_target: pathlib.Path, git_worktree: pathlib.Path
    ) -> None:
        """Newline in task_id must not let an attacker forge the commit subject line.

        git treats the first line of -m as the subject. A task_id of
        "T\\ninjected" would make the body contain "injected" on line 2 but MUST
        NOT make "injected" the subject.
        """
        task_id = "T\ninjected-subject"
        output_file = state_dir / "output" / f"{task_id}.py"
        output_file.write_text("def foo():\n    return 42\n")
        result = _resolve(commit_accepted_output(task_id, str(seed_target), state_dir))
        if result["committed"]:
            subject = _git(git_worktree, "log", "-1", "--format=%s").stdout.strip()
            assert "injected-subject" != subject
            assert subject.startswith("Integrate validated code for")
        # Else: rejected outright is also acceptable (filesystem may refuse the filename
        # or git may refuse the argv); the contract is "no forged subject".

    def test_task_id_with_backtick_does_not_execute(
        self, state_dir: pathlib.Path, seed_target: pathlib.Path, git_worktree: pathlib.Path
    ) -> None:
        """Backticks in task_id must be passed verbatim — subprocess.run with a
        list arg does not spawn a shell, so `echo PWN` cannot execute.
        Canary: the literal backticked text must appear in the commit subject.
        """
        task_id = "T`echo PWN`"
        (state_dir / "output" / f"{task_id}.py").write_text("def foo():\n    return 1\n")
        result = _resolve(commit_accepted_output(task_id, str(seed_target), state_dir))
        if result["committed"]:
            subject = _git(git_worktree, "log", "-1", "--format=%s").stdout.strip()
            # Literal backticks survive — no shell substitution happened.
            assert "`echo PWN`" in subject, f"shell substitution occurred: subject={subject!r}"

    def test_task_id_with_dash_flag_prefix_not_parsed_as_option(
        self, state_dir: pathlib.Path, seed_target: pathlib.Path, git_worktree: pathlib.Path
    ) -> None:
        """task_id = '--amend' must not amend the prior commit.

        The task_id goes into the -m value (not as a bare argv token), but a
        defense-in-depth test pins that commit count grows by exactly 1.
        """
        before = _git(git_worktree, "rev-list", "--count", "HEAD").stdout.strip()
        task_id = "--amend"
        (state_dir / "output" / f"{task_id}.py").write_text("def foo():\n    return 9\n")
        result = _resolve(commit_accepted_output(task_id, str(seed_target), state_dir))
        after = _git(git_worktree, "rev-list", "--count", "HEAD").stdout.strip()
        if result["committed"]:
            assert int(after) == int(before) + 1, "amend happened: commit count unchanged"


class TestLoggerContract:
    """Gate observable logger side-effects so silent log-swallow post-swap is loud."""

    def test_git_stdout_lines_reach_logger_with_prefix(
        self, state_dir: pathlib.Path, seed_target: pathlib.Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        (state_dir / "output" / "T.py").write_text("def foo():\n    return 77\n")
        with caplog.at_level(logging.INFO, logger="harness.git_integration"):
            result = _resolve(commit_accepted_output("T", str(seed_target), state_dir))
        assert result["committed"] is True
        # Multiple git invocations happen; at least one "git: …" line must surface.
        git_lines = [r for r in caplog.records if r.getMessage().startswith("git: ")]
        assert git_lines, "no 'git: …' lines captured via logger"
