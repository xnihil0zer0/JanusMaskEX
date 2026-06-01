"""STAGING-RM-NOTIMEOUT oracle (PHASE_STAGING_RM_NOTIMEOUT).

RED-on-HEAD, GREEN-after-fix oracle for harness/git_integration.py
remove_staging_worktree. On HEAD the `git worktree remove` is invoked exactly
once, with NO `timeout=` kwarg and NO retry: a busy/locked worktree (a jailed
subprocess still holding a file handle) would HANG forever. The fix wraps the
removal in a bounded retry loop, each subprocess.run passing a bounded
`timeout=` kwarg, catching subprocess.TimeoutExpired AND
subprocess.CalledProcessError, retrying, then falling through to rmtree.

These tests are deterministic and fast: subprocess.run is monkeypatched so the
first `git worktree remove` raises TimeoutExpired (no real hang), and shutil
removal is stubbed. The dest in-repo path is tests/unit/test_staging_rm_notimeout.py.

Intended-target destination (in-repo): tests/unit/test_staging_rm_notimeout.py
"""
import subprocess
import pathlib
import time
import math
import pytest
from harness import git_integration


def test_remove_retries_after_timeout(tmp_path, monkeypatch):
    recorded_calls = []
    remove_call_count = 0

    def fake_run(cmd, *args, **kwargs):
        recorded_calls.append((cmd, args, kwargs))
        if isinstance(cmd, list) and len(cmd) >= 3 and cmd[0:3] == ['git', 'worktree', 'remove']:
            nonlocal remove_call_count
            remove_call_count += 1
            if remove_call_count == 1:
                # FIRST remove call raises TimeoutExpired (busy/locked worktree).
                raise subprocess.TimeoutExpired(cmd, timeout=kwargs.get('timeout'))
            else:
                # SECOND remove call returns success.
                return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')
        return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')

    monkeypatch.setattr(git_integration.subprocess, 'run', fake_run)

    rmtree_calls = []
    def fake_rmtree(path, *args, **kwargs):
        rmtree_calls.append((path, args, kwargs))
    monkeypatch.setattr(git_integration.shutil, 'rmtree', fake_rmtree)

    some_path = tmp_path / "staging_worktree"
    some_path.mkdir()
    some_dir = tmp_path / "parent_root"
    some_dir.mkdir()

    exc = None
    try:
        git_integration.remove_staging_worktree(str(some_path), parent_root=str(some_dir))
    except Exception as e:
        exc = e

    assert exc is None, f"Exception propagated from remove_staging_worktree: {exc}"

    remove_calls = [c for c in recorded_calls if c[0][0:3] == ['git', 'worktree', 'remove']]
    assert len(remove_calls) > 1, f"Expected more than 1 git worktree remove calls (retry), got {len(remove_calls)}"


def test_remove_passes_bounded_timeout(tmp_path, monkeypatch):
    recorded_calls = []
    remove_call_count = 0

    def fake_run(cmd, *args, **kwargs):
        recorded_calls.append((cmd, args, kwargs))
        if isinstance(cmd, list) and len(cmd) >= 3 and cmd[0:3] == ['git', 'worktree', 'remove']:
            nonlocal remove_call_count
            remove_call_count += 1
            if remove_call_count == 1:
                raise subprocess.TimeoutExpired(cmd, timeout=kwargs.get('timeout'))
            else:
                return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')
        return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')

    monkeypatch.setattr(git_integration.subprocess, 'run', fake_run)

    rmtree_calls = []
    def fake_rmtree(path, *args, **kwargs):
        rmtree_calls.append((path, args, kwargs))
    monkeypatch.setattr(git_integration.shutil, 'rmtree', fake_rmtree)

    some_path = tmp_path / "staging_worktree"
    some_path.mkdir()
    some_dir = tmp_path / "parent_root"
    some_dir.mkdir()

    try:
        git_integration.remove_staging_worktree(str(some_path), parent_root=str(some_dir))
    except Exception:
        pass

    remove_calls = [c for c in recorded_calls if c[0][0:3] == ['git', 'worktree', 'remove']]
    assert len(remove_calls) > 0, "No git worktree remove calls recorded"
    for cmd, args, kwargs in remove_calls:
        assert 'timeout' in kwargs, "timeout kwarg is missing from git worktree remove call"
        timeout = kwargs['timeout']
        assert timeout is not None, "timeout kwarg value is None"
        assert isinstance(timeout, (int, float)), "timeout must be a number"
        assert timeout > 0, "timeout must be positive"
        assert math.isfinite(timeout), "timeout must be finite"


@pytest.mark.timeout(5)
def test_remove_does_not_propagate_unbounded(tmp_path, monkeypatch):
    recorded_calls = []
    remove_call_count = 0

    def fake_run(cmd, *args, **kwargs):
        recorded_calls.append((cmd, args, kwargs))
        if isinstance(cmd, list) and len(cmd) >= 3 and cmd[0:3] == ['git', 'worktree', 'remove']:
            nonlocal remove_call_count
            remove_call_count += 1
            if remove_call_count == 1:
                raise subprocess.TimeoutExpired(cmd, timeout=kwargs.get('timeout'))
            else:
                return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')
        return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')

    monkeypatch.setattr(git_integration.subprocess, 'run', fake_run)

    rmtree_calls = []
    def fake_rmtree(path, *args, **kwargs):
        rmtree_calls.append((path, args, kwargs))
    monkeypatch.setattr(git_integration.shutil, 'rmtree', fake_rmtree)

    some_path = tmp_path / "staging_worktree"
    some_path.mkdir()
    some_dir = tmp_path / "parent_root"
    some_dir.mkdir()

    start_time = time.perf_counter()
    # Must NOT raise and must complete quickly (no unbounded hang/propagation).
    git_integration.remove_staging_worktree(str(some_path), parent_root=str(some_dir))
    duration = time.perf_counter() - start_time
    assert duration < 1.0, f"Call took too long: {duration}s"


def test_remove_happy_path_control(tmp_path, monkeypatch):
    recorded_calls = []

    def fake_run(cmd, *args, **kwargs):
        recorded_calls.append((cmd, args, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')

    monkeypatch.setattr(git_integration.subprocess, 'run', fake_run)

    rmtree_calls = []
    def fake_rmtree(path, *args, **kwargs):
        rmtree_calls.append((path, args, kwargs))
    monkeypatch.setattr(git_integration.shutil, 'rmtree', fake_rmtree)

    some_path = tmp_path / "staging_worktree"
    some_path.mkdir()
    some_dir = tmp_path / "parent_root"
    some_dir.mkdir()

    # Should complete without error.
    git_integration.remove_staging_worktree(str(some_path), parent_root=str(some_dir))

    remove_calls = [c for c in recorded_calls if c[0][0:3] == ['git', 'worktree', 'remove']]
    assert len(remove_calls) == 1, f"Expected exactly 1 remove call on happy path, got {len(remove_calls)}"
