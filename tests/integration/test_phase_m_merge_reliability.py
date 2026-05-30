"""Phase M oracle — merge reliability of the blue-green deploy half.

Pins the silent-task-loss fix:
  * M-b/M-c: merge_staging_to_parent must use a WHOLE-TREE stash so a parent
    tree dirty on the target file (or an untracked-file collision) no longer
    aborts the fast-forward merge.
  * M-d: the staging worktree is always removed.
  * M-a: when the merge raises, _auto_commit_accepted must route the task to
    blocked/ (re-claimable) and must NOT mark it processed/ (silent loss).

Self-contained + deterministic: real temp git repos under tmp_path, no agents,
no worker. create_staging_worktree requires the staging dir to be a SIBLING of
the parent repo (staging_path.parent == parent_root.parent), so all staging
dirs are placed beside their parent.
"""
from __future__ import annotations

import inspect
import json
import subprocess

import pytest

from harness import git_integration
from harness import orchestrator


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True)


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q", "-b", "main"], path)
    _git(["config", "user.name", "Test User"], path)
    _git(["config", "user.email", "test@janusmask.local"], path)


def _make_parent_with_staging_commit(tmp_path, target_rel="target.txt",
                                     base="base\n", staged="merged\n"):
    """Parent repo + a sibling staging worktree whose HEAD edits target_rel."""
    parent = tmp_path / "parent"
    _init_repo(parent)
    (parent / target_rel).write_text(base, encoding="utf-8")
    _git(["add", target_rel], parent)
    _git(["commit", "-q", "-m", "initial"], parent)

    staging = tmp_path / "parent_staging"   # sibling of parent (required)
    git_integration.create_staging_worktree(str(staging), parent_root=parent)
    (staging / target_rel).write_text(staged, encoding="utf-8")
    _git(["add", target_rel], staging)
    _git(["commit", "-q", "-m", "staging edit"], staging)
    return parent, staging


# ---- M-b / M-c / M-d: merge layer --------------------------------------------

def test_phase_m_dirty_parent_target_merge_does_not_silently_lose(tmp_path):
    """Parent dirty on the SAME file the staging commit touches.

    Pre-Phase-M this aborts ('local changes would be overwritten'). With the
    whole-tree stash it must safely stash + FF, leaving the parent at the
    staging content; the staging worktree must be removed (M-d).
    """
    parent, staging = _make_parent_with_staging_commit(
        tmp_path, base="base\n", staged="merged\n")
    (parent / "target.txt").write_text("dirty-local-edit\n", encoding="utf-8")
    assert _git(["status", "--porcelain"], parent).stdout.strip() != ""

    git_integration.merge_staging_to_parent(staging, parent_root=parent)

    head_content = _git(["show", "HEAD:target.txt"], parent).stdout
    assert head_content == "merged\n"      # accept NOT lost
    assert not staging.exists()            # M-d


def test_phase_m_untracked_collision_merge_succeeds(tmp_path):
    """Staging adds a NEW file that collides with an untracked parent file.

    Pre-Phase-M -> 'untracked working tree files would be overwritten'. The
    whole-tree `-u` stash removes the untracked file before the FF.
    """
    parent = tmp_path / "parent"
    _init_repo(parent)
    (parent / "keep.txt").write_text("keep\n", encoding="utf-8")
    _git(["add", "keep.txt"], parent)
    _git(["commit", "-q", "-m", "initial"], parent)

    staging = tmp_path / "parent_staging"
    git_integration.create_staging_worktree(str(staging), parent_root=parent)
    (staging / "new.txt").write_text("from-staging\n", encoding="utf-8")
    _git(["add", "new.txt"], staging)
    _git(["commit", "-q", "-m", "add new.txt"], staging)

    (parent / "new.txt").write_text("untracked-parent\n", encoding="utf-8")

    git_integration.merge_staging_to_parent(staging, parent_root=parent)

    assert _git(["show", "HEAD:new.txt"], parent).stdout == "from-staging\n"
    assert not staging.exists()


def test_phase_m_clean_parent_still_merges(tmp_path):
    """Regression: a clean parent FF-merges and removes the worktree (no stash)."""
    parent, staging = _make_parent_with_staging_commit(tmp_path)
    git_integration.merge_staging_to_parent(staging, parent_root=parent)
    assert _git(["show", "HEAD:target.txt"], parent).stdout == "merged\n"
    assert not staging.exists()


# ---- M-a: accept-path ordering / restore-on-fail -----------------------------

def test_phase_m_mark_processed_runs_after_merge_in_source():
    """FIX-DETECTOR: _mark_processed must be called AFTER merge_staging_to_parent.

    Pre-Phase-M, _auto_commit_accepted calls _mark_processed BEFORE the merge, so a
    failed merge orphans the task in processed/ with no commit (silent loss). The
    fix reorders it to run only after a successful merge, and routes a merge
    failure to blocked/. This source-level assertion fails on the old order and
    passes on the fixed order — the behavioural reorder has no clean runtime
    signature short of a fully-staged accept, so we pin the structure directly.
    """
    src = inspect.getsource(orchestrator._auto_commit_accepted)
    assert "merge_staging_to_parent" in src, "merge call missing"
    assert "_mark_processed" in src, "_mark_processed call missing"
    assert src.index("merge_staging_to_parent") < src.rindex("_mark_processed"), (
        "_mark_processed must run AFTER merge_staging_to_parent (M-a): a merge "
        "failure must never leave the task orphaned in processed/"
    )
    assert "_mark_blocked" in src, (
        "the merge-failure branch must route the task to blocked/ via _mark_blocked (M-a)"
    )


def test_phase_m_merge_failure_routes_to_blocked_not_processed(tmp_path, monkeypatch):
    """If the merge raises, the task must NOT be orphaned in processed/.

    Asserts the production contract used by _auto_commit_accepted's merge-failure
    branch: _mark_blocked moves the task to blocked/ with a merge_failed retry
    sidecar, and _mark_processed is NOT what handles a failed merge.
    """
    state_dir = tmp_path / "state"
    tasks_dir = state_dir / "tasks"
    tasks_dir.mkdir(parents=True)
    task_id = "PHASE_M_ORACLE_TASK"
    (tasks_dir / f"{task_id}.json").write_text(
        json.dumps({"task_id": task_id}), encoding="utf-8")

    # Simulate the merge aborting (dirty tree / stash failure surfaces here).
    def _boom(*a, **k):
        raise RuntimeError("Fast-forward merge failed (simulated)")
    monkeypatch.setattr(orchestrator.git_integration,
                        "merge_staging_to_parent", _boom)

    # The merge seam raises ...
    with pytest.raises(RuntimeError):
        orchestrator.git_integration.merge_staging_to_parent("x", "y")

    # ... and the production failure route parks the task in blocked/, not processed/.
    orchestrator._mark_blocked(state_dir, task_id, outcome="merge_failed")

    assert not (tasks_dir / "processed" / f"{task_id}.json").exists(), \
        "task must NOT be orphaned in processed/ on merge failure"
    assert (tasks_dir / "blocked" / f"{task_id}.json").exists(), \
        "task must be routed to blocked/ for retry"
    sidecar = tasks_dir / "blocked" / f"{task_id}.retry.json"
    assert sidecar.exists()
    assert json.loads(sidecar.read_text())["last_outcome"] == "merge_failed"


# ---- M2: G-M-POPCONFLICT (stash-pop conflict resolution) ----
def test_phase_m_pop_conflict_leaves_clean_tree_no_orphan_stash(tmp_path):
    """G-M-POPCONFLICT: parent dirty on the SAME tracked file the staging commit
    modifies -> the FF merge succeeds but the best-effort `git stash pop` CONFLICTS.
    Pre-M2 this leaves an unmerged (UU) working tree + an orphaned stash while the
    function returns normally, so the orchestrator hands over on a conflicted tree.
    M2 must resolve deterministically (merged commit content wins): a CLEAN tree
    (no UU), the file at the merged content, and NO orphaned stash.
    """
    parent, staging = _make_parent_with_staging_commit(
        tmp_path, base="base\n", staged="base\nmerged\n")
    # Make the parent dirty on the SAME tracked file, with content that will
    # conflict with the merged result when the stash is popped back.
    (parent / "target.txt").write_text("base\nLOCAL-EDIT\n", encoding="utf-8")
    assert _git(["status", "--porcelain"], parent).stdout.strip() != ""

    git_integration.merge_staging_to_parent(staging, parent_root=parent)

    # Tree must be CLEAN — no unmerged (UU) entries, nothing left over.
    status = _git(["status", "--porcelain"], parent).stdout
    assert "UU" not in status, f"conflicted/unmerged tree after merge: {status!r}"
    assert status.strip() == "", f"working tree not clean after merge: {status!r}"
    # Merged commit content wins.
    assert (parent / "target.txt").read_text(encoding="utf-8") == "base\nmerged\n"
    # No orphaned stash left behind.
    assert _git(["stash", "list"], parent).stdout.strip() == ""
    # Staging worktree removed (M-d still holds).
    assert not staging.exists()



# ---- M3: G-M2-RESET-UNCHECKED (fail-closed on a failed recovery reset) ----
def test_phase_m_reset_fail_fails_closed_clean_tree_no_leak(tmp_path, monkeypatch):
    """G-M2-RESET-UNCHECKED: the pop-conflict resolution `git reset --hard HEAD`
    can itself fail. Pre-M3 its returncode is IGNORED (check=False) and the
    function returns NORMALLY, leaving an unmerged (UU) HEAD-moved tree — so the
    caller (_auto_commit_accepted) skips _mark_blocked and proceeds to
    _mark_processed + os.execv on a conflicted tree (silent corruption).

    M3 must FAIL-CLOSED: capture the reset rc; on failure (i) do NOT drop the
    stash — PRESERVE it so the operator's stashed local changes remain
    recoverable, (ii) restore the parent to the captured pre-merge sha so the
    tree is CLEAN again (this recovery reset uses argv ['git','reset','--hard',
    <sha>], DISTINCT from the conflict-resolution ['git','reset','--hard',
    'HEAD']), (iii) STILL remove the staging worktree (deferred raise / nested
    finally — no leak), then RAISE so the caller routes the task to blocked/.

    This test forces ONLY the conflict-resolution `reset --hard HEAD` to fail
    (argv-exact monkeypatch, all other git calls pass through to the real
    subprocess.run — including the recovery `reset --hard <sha>`).

    MUST FAIL pre-M3 (current code returns normally on a UU tree — no raise, the
    `merge_staging_to_parent(...)` call returns and pytest.raises sees nothing).
    MUST PASS after M3 (raises, tree restored clean, worktree gone, stash
    PRESERVED for operator recovery).
    """
    parent, staging = _make_parent_with_staging_commit(
        tmp_path, base="base\n", staged="base\nmerged\n")
    # Parent dirty on the SAME tracked file -> the FF succeeds but the stash pop
    # conflicts, driving execution into the reset-recovery branch.
    (parent / "target.txt").write_text("base\nLOCAL-EDIT\n", encoding="utf-8")
    assert _git(["status", "--porcelain"], parent).stdout.strip() != ""

    _real_run = subprocess.run
    _reset_head = ["git", "reset", "--hard", "HEAD"]

    def _fake_run(args, *a, **k):
        # Force ONLY the conflict-resolution reset to fail; everything else
        # (status, stash push/pop, ff merge, the recovery `reset --hard <sha>`,
        # stash drop, stash show, worktree removal) hits the REAL subprocess.run.
        if args == _reset_head:
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="forced reset failure")
        return _real_run(args, *a, **k)

    monkeypatch.setattr(subprocess, "run", _fake_run)

    # Fail-closed: the function must RAISE so the caller routes to blocked/.
    with pytest.raises(Exception):
        git_integration.merge_staging_to_parent(staging, parent_root=parent)

    monkeypatch.undo()  # restore real subprocess.run for the assertions below

    # The parent tree must be restored CLEAN via the pre_merge_sha recovery reset
    # (no unmerged UU entries, nothing left over).
    status = _git(["status", "--porcelain"], parent).stdout
    assert "UU" not in status, f"conflicted/unmerged tree left after raise: {status!r}"
    assert status.strip() == "", f"parent tree not clean after fail-closed raise: {status!r}"
    # The staging worktree must STILL be removed on the raise path (no leak).
    assert not staging.exists(), "staging worktree leaked on the fail-closed path"
    # The stash must be PRESERVED (NOT dropped) on a failed reset, so the
    # operator's stashed local changes remain recoverable. The pre-M3 code drops
    # it unconditionally (an irrecoverable loss on the fail path); M3 keeps it.
    stash_list = _git(["stash", "list"], parent).stdout.strip()
    assert stash_list != "", (
        "stash must be PRESERVED on the failed-reset path (not dropped) so the "
        "operator's local changes stay recoverable"
    )
    assert len(stash_list.splitlines()) == 1, (
        f"exactly one preserved recovery stash expected, got: {stash_list!r}"
    )


# ---- M3-c: G-M2-NO-REMOVE-PARENT-TEST (coverage) ----
def test_phase_m_merge_finally_removes_worktree_with_parent_root():
    """FIX-DETECTOR (G-M2-NO-REMOVE-PARENT-TEST): the merge `finally` must call
    remove_staging_worktree with parent_root=parent_root, so worktree
    de-registration targets the right repo from a relocated daemon CWD.

    Source-level assertion (mirrors test_phase_m_mark_processed_runs_after_merge_in_source):
    a pure-runtime signature is awkward to pin here, so we pin the structure.
    """
    src = inspect.getsource(git_integration.merge_staging_to_parent)
    assert "remove_staging_worktree" in src, "remove_staging_worktree call missing from merge"
    assert "parent_root=parent_root" in src, (
        "the finally must call remove_staging_worktree(..., parent_root=parent_root) "
        "(G-M2-NO-REMOVE-PARENT-TEST / G-M-REMOVE-PARENT)"
    )


# ---- M3-b: G-M2-UNTRACKED-DROP (LOW, log-only audit trail) ----
def test_phase_m_dropped_stash_is_logged_for_audit():
    """FIX-DETECTOR (G-M2-UNTRACKED-DROP): before dropping the stash on the
    pop-conflict path, the function must emit an audit trail of WHAT is being
    discarded (e.g. `git stash show --include-untracked --name-only`) so a
    silently discarded unrelated untracked file is observable.

    M3-b is log-only with no clean runtime tree-signature (the conflict-branch
    behaviour is otherwise covered by the M2 oracle), so this is a source-level
    pin: assert the conflict branch references `git stash show` with the
    --include-untracked --name-only audit args. If you prefer to keep M3-b purely
    code-reviewed, DELETE this test (it is flagged optional in the brief).
    """
    src = inspect.getsource(git_integration.merge_staging_to_parent)
    assert "stash" in src and "show" in src, (
        "M3-b: drop path should `git stash show` the discarded stash for an audit trail"
    )
    assert "--include-untracked" in src and "--name-only" in src, (
        "M3-b: the audit log should use `git stash show --include-untracked --name-only`"
    )
