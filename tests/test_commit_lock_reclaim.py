"""Oracle for bounded, stale-aware autowork commit-lock acquisition.

RED on HEAD: the helper ``_acquire_commit_lock_or_reclaim`` does not exist yet, so
both cases below error out (AttributeError) — a clean RED that never HANGS (a
"does-not-block" test against the current blocking ``flock(LOCK_EX)`` would hang
the suite, which is why the fix is a discrete helper rather than an inline change
that can only be exercised through the full push path).

GREEN after fix: ``harness/autowork_daemon._acquire_commit_lock_or_reclaim(
state_dir, deadline_sec=...)`` does a NON-BLOCKING ``flock(LOCK_NB)`` retry loop up
to ``deadline_sec``. On acquire it stamps the holder PID into the lock file and
returns ``(locked_fd, 'acquired')`` (the caller releases). If the deadline passes
with the lock still held: a stale holder (recorded owner PID not alive) is
reclaimed -> ``(locked_fd, 'reclaimed')``; a live holder yields ``(None, 'busy')``
WITHOUT blocking. ``_maybe_push_and_rebase_pin`` is rewired to use it (busy -> skip
the tick + telemetry, never block).
"""
import fcntl
import os
import time

from harness import autowork_daemon as awd


def _lock_path(state):
    d = state / "control" / "autowork"
    d.mkdir(parents=True, exist_ok=True)
    return d / "git_commit.lock"


def test_acquire_free_lock_stamps_owner_pid(tmp_path):
    state = tmp_path / "state"
    fd, status = awd._acquire_commit_lock_or_reclaim(state)
    try:
        assert status in ("acquired", "reclaimed")
        assert fd is not None
        content = _lock_path(state).read_text(encoding="utf-8")
        assert str(os.getpid()) in content  # owner PID stamped while held
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()
        except Exception:
            pass


def test_acquire_live_held_lock_is_bounded_busy(tmp_path):
    state = tmp_path / "state"
    lp = _lock_path(state)
    holder = open(lp, "a")
    fcntl.flock(holder, fcntl.LOCK_EX)  # a LIVE owner (this process) holds it
    lp.write_text(str(os.getpid()), encoding="utf-8")
    try:
        t0 = time.monotonic()
        fd, status = awd._acquire_commit_lock_or_reclaim(state, deadline_sec=0.3)
        elapsed = time.monotonic() - t0
        assert status == "busy"
        assert fd is None
        assert elapsed < 5  # bounded — must NOT block indefinitely
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        holder.close()
