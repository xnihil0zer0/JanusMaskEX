"""Regression oracle for OWNER_HANDEDIT_PROPOSALS_2026-06-09 §4b.

The worker-side commit-lock acquisition in ``_auto_commit_accepted`` was an
UNBOUNDED blocking ``flock(LOCK_EX)``: a *live but hung* holder (e.g. a wedged
push) blocked the worker forever. The bounded helper must (a) acquire and
PID-stamp a free lock, (b) give up within the deadline against a live holder,
and (c) actually be wired into ``_auto_commit_accepted`` in place of the bare
blocking flock.

flock conflicts are per open-file-description, so two separate ``open()``
calls in one process genuinely contend -- no subprocess needed.
"""
import fcntl
import inspect
import os
import time

from harness.orchestrator import _acquire_git_commit_lock_bounded, _auto_commit_accepted


def test_free_lock_acquires_and_stamps_pid(tmp_path):
    lock_path = tmp_path / 'git_commit.lock'
    with open(lock_path, 'a') as fd:
        assert _acquire_git_commit_lock_bounded(fd, deadline_sec=2.0) is True
        assert lock_path.read_text().strip() == str(os.getpid())
        fcntl.flock(fd, fcntl.LOCK_UN)


def test_live_holder_times_out_within_deadline(tmp_path):
    lock_path = tmp_path / 'git_commit.lock'
    with open(lock_path, 'a') as holder, open(lock_path, 'a') as contender:
        fcntl.flock(holder, fcntl.LOCK_NB | fcntl.LOCK_EX)
        t0 = time.monotonic()
        try:
            assert _acquire_git_commit_lock_bounded(contender, deadline_sec=0.3) is False
        finally:
            fcntl.flock(holder, fcntl.LOCK_UN)
        # Bounded: returns promptly after the deadline, never hangs.
        assert time.monotonic() - t0 < 10.0


def test_dead_holder_does_not_block(tmp_path):
    # A released (kernel-dropped) lock must acquire on the first NB attempt --
    # the historical 0-byte stale file alone is benign residue.
    lock_path = tmp_path / 'git_commit.lock'
    lock_path.write_text('')
    with open(lock_path, 'a') as fd:
        t0 = time.monotonic()
        assert _acquire_git_commit_lock_bounded(fd, deadline_sec=5.0) is True
        assert time.monotonic() - t0 < 1.0
        fcntl.flock(fd, fcntl.LOCK_UN)


def test_bounded_acquire_is_wired_into_auto_commit_accepted():
    src = inspect.getsource(_auto_commit_accepted)
    assert '_acquire_git_commit_lock_bounded(lock_fd)' in src, \
        'bounded lock helper (§4b) not wired into _auto_commit_accepted'
    assert 'fcntl.flock(lock_fd, fcntl.LOCK_EX)' not in src, \
        'unbounded blocking LOCK_EX still present in _auto_commit_accepted'
    # Timeout must fail the attempt cleanly, not proceed to commit.
    assert 'git_commit_lock_timeout' in src
