"""RED-on-parent oracle for harness/git_integration.py::remove_staging_worktree.

VERIFIED ROOT-CAUSE BUG (parent HEAD 8034af8): the function runs
``git worktree prune`` UNCONDITIONALLY FIRST, THEN ``git worktree remove -f``
in a retry loop. When the staging worktree's *working directory* is missing but
its admin entry (``.git/worktrees/<name>``) is still registered, the leading
``prune`` DELETES that admin entry, so the subsequent ``git worktree remove -f``
exits 128 with ``fatal: '<path>' is not a working tree``. Every retry re-prunes,
so all 3 attempts fail, the function logs "failed after 3 attempts ... falling
back to rmtree", and the ``shutil.rmtree(ignore_errors=True)`` fallback silently
masks the failure (git's own teardown never ran).

Reproduced byte-for-byte in a throwaway git repo:
  * remove-FIRST on a working-dir-missing worktree  -> rc 0  (git cleans it up)
  * prune-FIRST then remove                          -> rc 128 ('is not a working tree')

REQUIRED FIX behavior these tests pin:
  1. ``git worktree remove -f`` is attempted on the LIVE admin entry FIRST; no
     ``git worktree prune`` runs before the first remove attempt (drop the
     leading unconditional prune).
  2. A remove failure whose stderr says the entry is already gone
     ("is not a working tree" / "No such working tree") is treated as success.
  3. On a remove failure the captured ``e.stderr`` is logged (observability).

These tests are HERMETIC and SELF-ISOLATING: each builds a real throwaway git
repo + a real ``git worktree add`` under ``tmp_path`` and never touches the live
repo. RED on parent HEAD, GREEN after the fix.

Intended-target destination (in-repo): tests/harness/test_remove_staging_worktree_ordering.py
"""
import logging
import pathlib
import subprocess

import pytest

from harness import git_integration


def _run_git(args, cwd):
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.fixture
def staging_worktree_with_missing_workdir(tmp_path):
    """Build a real parent repo + a real staging worktree, then delete the
    worktree's WORKING DIRECTORY while leaving its admin entry registered.

    This is the exact failure condition: ``git worktree prune`` will delete the
    dangling admin entry (working dir is gone), but ``git worktree remove`` on
    the still-registered path SUCCEEDS if attempted before any prune.

    Yields (parent_root: Path, staging_path: Path, admin_entry: Path).
    """
    parent_root = tmp_path / "parent_repo"
    parent_root.mkdir()
    _run_git(["init", "-q"], cwd=parent_root)
    _run_git(["config", "user.email", "oracle@test.invalid"], cwd=parent_root)
    _run_git(["config", "user.name", "oracle"], cwd=parent_root)
    (parent_root / "seed.txt").write_text("seed\n")
    _run_git(["add", "seed.txt"], cwd=parent_root)
    _run_git(["commit", "-qm", "init"], cwd=parent_root)

    staging_path = tmp_path / "staging_wt"
    _run_git(
        ["worktree", "add", "-q", str(staging_path), "-b", "stagingbranch"],
        cwd=parent_root,
    )

    admin_entry = parent_root / ".git" / "worktrees" / "staging_wt"
    assert admin_entry.exists(), "precondition: admin entry registered"
    assert staging_path.exists(), "precondition: worktree working dir present"

    # Create the dangling condition: remove the worktree's WORKING DIRECTORY
    # entirely (admin entry stays registered -> prune would delete it).
    import shutil as _shutil

    _shutil.rmtree(staging_path)
    assert not staging_path.exists()
    assert admin_entry.exists(), (
        "precondition: admin entry STILL registered after working dir removal"
    )
    return parent_root, staging_path, admin_entry


def test_remove_runs_before_prune_so_git_cleans_dangling_worktree(
    staging_worktree_with_missing_workdir, caplog
):
    """BEHAVIORAL: git itself must clean up the dangling worktree (NOT the
    rmtree fallback). On parent HEAD the leading prune deletes the admin entry
    first, so all 3 ``git worktree remove`` attempts fail (rc 128) and the
    function logs "failed after 3 attempts ... falling back to rmtree" -> RED.
    """
    parent_root, staging_path, admin_entry = staging_worktree_with_missing_workdir

    with caplog.at_level(logging.INFO, logger="harness.git_integration"):
        git_integration.remove_staging_worktree(
            str(staging_path), parent_root=str(parent_root)
        )

    # The remove must have succeeded via git, NOT degraded to the rmtree
    # fallback. On parent HEAD the leading prune kills the admin entry, so every
    # remove attempt fails and this error IS logged -> assertion fails (RED).
    fallback_errors = [
        r.getMessage()
        for r in caplog.records
        if "failed after 3 attempts" in r.getMessage()
        or "falling back to rmtree" in r.getMessage()
    ]
    assert not fallback_errors, (
        "git worktree remove degraded to the rmtree fallback instead of "
        f"cleanly removing the dangling worktree: {fallback_errors}"
    )

    # And it must have actually logged a successful git removal.
    success_logs = [
        r.getMessage()
        for r in caplog.records
        if "Removed staging worktree reference" in r.getMessage()
    ]
    assert success_logs, (
        "expected a successful 'Removed staging worktree reference' log; "
        f"got records: {[r.getMessage() for r in caplog.records]}"
    )

    # End state: both the working dir and the admin entry are gone.
    assert not staging_path.exists()
    assert not admin_entry.exists(), "admin entry should be cleaned up by git"


def test_remove_is_invoked_before_any_prune(
    staging_worktree_with_missing_workdir, monkeypatch
):
    """ORDERING BACKSTOP (spy): the FIRST ``git worktree`` subcommand reaching
    git must be ``remove`` -- never ``prune``. On parent HEAD ``prune`` runs
    unconditionally first -> RED.
    """
    parent_root, staging_path, _admin_entry = staging_worktree_with_missing_workdir

    git_worktree_subcommands = []
    real_run = subprocess.run

    def spy_run(cmd, *args, **kwargs):
        if (
            isinstance(cmd, (list, tuple))
            and len(cmd) >= 3
            and list(cmd[:2]) == ["git", "worktree"]
        ):
            git_worktree_subcommands.append(cmd[2])
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy_run)

    git_integration.remove_staging_worktree(
        str(staging_path), parent_root=str(parent_root)
    )

    assert git_worktree_subcommands, "expected at least one git worktree call"
    assert git_worktree_subcommands[0] == "remove", (
        "the FIRST git worktree subcommand must be 'remove' (no leading prune); "
        f"actual order: {git_worktree_subcommands}"
    )


def test_already_gone_stderr_is_treated_as_success(tmp_path, caplog, monkeypatch):
    """HARDENING: if ``git worktree remove`` fails with stderr indicating the
    entry is already gone ('is not a working tree'), it is treated as success --
    no "failed after 3 attempts" error, no retry storm. On parent HEAD this
    CalledProcessError is logged as a failure and falls through to rmtree -> RED.
    """
    parent_root = tmp_path / "parent_repo"
    parent_root.mkdir()
    staging_path = tmp_path / "staging_wt"
    staging_path.mkdir()  # dir present so the rmtree fallback would also "succeed"

    def fake_run(cmd, *args, **kwargs):
        if (
            isinstance(cmd, (list, tuple))
            and len(cmd) >= 3
            and list(cmd[:3]) == ["git", "worktree", "remove"]
        ):
            raise subprocess.CalledProcessError(
                returncode=128,
                cmd=list(cmd),
                output="",
                stderr=f"fatal: '{staging_path}' is not a working tree",
            )
        # prune / rev-parse / anything else: succeed quietly.
        return subprocess.CompletedProcess(list(cmd), 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with caplog.at_level(logging.INFO, logger="harness.git_integration"):
        git_integration.remove_staging_worktree(
            str(staging_path), parent_root=str(parent_root)
        )

    fallback_errors = [
        r.getMessage()
        for r in caplog.records
        if "failed after 3 attempts" in r.getMessage()
    ]
    assert not fallback_errors, (
        "'is not a working tree' (entry already gone) must be treated as "
        f"success, not a retry/rmtree failure: {fallback_errors}"
    )


def test_remove_failure_logs_stderr(tmp_path, caplog, monkeypatch):
    """OBSERVABILITY: a genuine remove failure must log git's real ``e.stderr``
    (not just the bare exception repr). On parent HEAD only ``{e}`` is logged,
    so the distinctive stderr text is absent -> RED.
    """
    parent_root = tmp_path / "parent_repo"
    parent_root.mkdir()
    staging_path = tmp_path / "staging_wt"
    staging_path.mkdir()

    sentinel = "JANUSMASK_STDERR_SENTINEL_locked_by_other_process"

    def fake_run(cmd, *args, **kwargs):
        if (
            isinstance(cmd, (list, tuple))
            and len(cmd) >= 3
            and list(cmd[:3]) == ["git", "worktree", "remove"]
        ):
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=list(cmd),
                output="",
                stderr=f"fatal: {sentinel}",
            )
        return subprocess.CompletedProcess(list(cmd), 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with caplog.at_level(logging.INFO, logger="harness.git_integration"):
        git_integration.remove_staging_worktree(
            str(staging_path), parent_root=str(parent_root)
        )

    all_logs = " ".join(r.getMessage() for r in caplog.records)
    assert sentinel in all_logs, (
        "a remove failure must log git's real stderr (e.stderr) for diagnosis; "
        f"sentinel not found in logs: {all_logs}"
    )
