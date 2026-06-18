"""Shared serialization primitive for state reconciliation.

This stdlib-only module exposes :func:`state_reconcile_lock`, a context
manager that acquires and releases the single dedicated
``state_reconcile.lock`` under a given state directory. It is the ONE shared
lock on which every state-mutating reconciliation path serializes -- the
in-loop brief_status sweep, the standalone reconcile apply, and the
post-accept brief reaper -- so the slow, destructive reconciliation work can
never run concurrently across mutators.

It is deliberately DISTINCT from the short-lived ``git_commit.lock``. The
slow destructive section is held under ``state_reconcile.lock`` and NEVER
under ``git_commit.lock``: the git commit lock is a per-git-op latch only and
must not span a slow op. A 14 GB rmtree/compaction held under the commit lock
would exceed the 60s accept deadline and route a validated build to
``auto_commit_failed``.

The lock is fail-closed (exclusive create) and is ALWAYS released on
exception via a ``finally`` so a crashing mutator never wedges the others.
"""
import os
import time
from contextlib import contextmanager
from pathlib import Path
__all__ = ['state_reconcile_lock', 'LOCK_FILENAME']
LOCK_FILENAME = 'state_reconcile.lock'

@contextmanager
def state_reconcile_lock(state_dir, *, timeout: float=60.0, poll: float=0.05):
    """Acquire/release the single dedicated ``state_reconcile.lock``.

    Yields the :class:`~pathlib.Path` of the held lock file. The lock lives at
    ``<state_dir>/state_reconcile.lock`` and is acquired with an exclusive
    ``O_CREAT | O_EXCL`` create (fail-closed): if another mutator already
    holds it we poll until it is released or ``timeout`` seconds elapse, at
    which point a :class:`TimeoutError` is raised. The lock is removed in a
    ``finally`` block so it is released even if the wrapped body raises.
    """
    sd = Path(state_dir)
    sd.mkdir(parents=True, exist_ok=True)
    lock_path = sd / LOCK_FILENAME
    deadline = time.monotonic() + max(0.0, float(timeout))
    fd = None
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 420)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f'timed out acquiring {lock_path}')
            time.sleep(max(0.0, float(poll)))
    try:
        try:
            os.write(fd, str(os.getpid()).encode('ascii'))
        except OSError:
            pass
        yield lock_path
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(str(lock_path))
        except OSError:
            pass