"""P4 oracle: _run_planner_subprocess must reap the WHOLE process group on timeout.

Background
---------
``harness/autowork_daemon.py::_run_planner_subprocess`` spawns the planner CLI
(``python -m harness.planner.cli ...``). The planner in turn uses
``spawn_agent`` with ``start_new_session=True`` to launch claude/gemini
grandchildren. On HEAD the function calls ``subprocess.run(cmd, timeout=...)``.
When that timeout fires, CPython sends SIGKILL to ONLY the direct child (the
planner CLI). Any grandchild that the planner detached into a *new session*
is left orphaned to PID 1 and keeps running -- this is the ~40h runaway-process
bug.

The fix converts the function to ``Popen(start_new_session=True)`` +
``proc.communicate(timeout=...)`` and, on ``subprocess.TimeoutExpired``, calls
the existing ``_kill_process_group(state_dir, task_id, proc)`` helper, which
does ``os.killpg(os.getpgid(proc.pid), SIGKILL)`` -- reaping the entire group
including the detached grandchild. The function still returns ``124`` on the
timeout path.

Why this test is RED on HEAD
----------------------------
We make the "planner" a tiny real Python process that:
  1. spawns a grandchild that writes its PID to a pidfile and then sleeps far
     longer than the timeout, and
  2. the planner itself then sleeps past the (short) timeout so the
     ``TimeoutExpired`` branch is exercised.

The grandchild stays in the planner's process group (it does NOT start its own
session). This is precisely the kind of descendant that ``subprocess.run``'s
timeout SIGKILL-to-the-direct-child-only leaves orphaned to PID 1, and that
``_kill_process_group``'s ``os.killpg(os.getpgid(proc.pid), SIGKILL)`` reaps --
because the fixed code spawns the planner with ``start_new_session=True`` so the
planner leads the group that the grandchild belongs to.

The kill path is kept REAL (we do NOT stub ``_kill_process_group``, ``os.killpg``
or ``os.getpgid``). We only rewrite the *command* the function launches, via a
thin ``subprocess`` shim that swaps ``cmd`` for our sleeper while passing every
other kwarg (timeout, ``start_new_session``, pipes) straight through to the real
``subprocess`` module. So ``Popen``/``run``, ``communicate``, ``TimeoutExpired``,
``getpgid`` and ``killpg`` all run for real.

After the timeout path returns:
  * On the FIXED code the planner leads a process group, ``killpg`` reaps the
    detached grandchild too -> ``os.kill(grandchild_pid, 0)`` raises
    ``ProcessLookupError`` -> GREEN.
  * On HEAD ``subprocess.run`` kills only the direct child; the grandchild
    survives -> ``os.kill(grandchild_pid, 0)`` succeeds -> RED.

The test always cleans up any survivor in a ``finally`` so it never leaks
processes regardless of pass/fail.
"""
from __future__ import annotations

import os
import signal
import subprocess as _real_subprocess
import sys
import time
from pathlib import Path

import pytest

import harness.autowork_daemon as daemon


# A self-contained "planner": spawn a grandchild (in the planner's OWN process
# group -- no new session) that records its pid and sleeps a long time, then the
# planner itself sleeps past the timeout. The grandchild models the agent CLIs
# the real planner leaves running: a bare proc.kill() of the planner orphans it,
# but a killpg of the planner's group reaps it.
_SLEEPER_SRC = r'''
import os, sys, time, subprocess
pidfile = sys.argv[1]
gc_src = (
    "import os,sys,time\n"
    "open(sys.argv[1],'w').write(str(os.getpid()))\n"
    "time.sleep(60)\n"
)
# Grandchild stays in THIS process's group (no start_new_session): only a
# process-group kill reaps it; a direct child-only kill orphans it to PID 1.
subprocess.Popen([sys.executable, "-c", gc_src, pidfile])
# Give the grandchild a beat to write its pidfile, then hang past the timeout.
time.sleep(60)
'''


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _reap(pid: int) -> None:
    """Best-effort: kill a surviving pid (and reap zombie) so the test never leaks."""
    if pid <= 0:
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        os.waitpid(pid, os.WNOHANG)
    except OSError:
        pass


class _CmdSwappingSubprocess:
    """Proxy for the real ``subprocess`` module that rewrites ``cmd`` for
    ``run``/``Popen`` to our sleeper, forwarding every other attribute and kwarg
    so the timeout / process-group machinery stays REAL."""

    def __init__(self, replacement_cmd):
        self._replacement_cmd = list(replacement_cmd)

    def run(self, cmd, *args, **kwargs):
        return _real_subprocess.run(self._replacement_cmd, *args, **kwargs)

    def Popen(self, cmd, *args, **kwargs):
        return _real_subprocess.Popen(self._replacement_cmd, *args, **kwargs)

    def __getattr__(self, name):
        # TimeoutExpired, PIPE, SubprocessError, etc. come from the real module.
        return getattr(_real_subprocess, name)


def test_run_planner_subprocess_timeout_reaps_detached_grandchild(tmp_path, monkeypatch):
    pidfile = tmp_path / "grandchild.pid"
    sleeper = tmp_path / "sleeper.py"
    sleeper.write_text(_SLEEPER_SRC)

    replacement_cmd = [sys.executable, str(sleeper), str(pidfile)]
    monkeypatch.setattr(
        daemon, "subprocess", _CmdSwappingSubprocess(replacement_cmd)
    )

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    brief_path = tmp_path / "brief.md"
    brief_path.write_text("# dummy brief\n")
    output_plan = tmp_path / "plan.json"

    grandchild_pid = None
    try:
        # Short timeout so the planner (and thus our sleeper) hits the
        # TimeoutExpired branch quickly.
        rc, wall, stderr_tail = daemon._run_planner_subprocess(
            brief_path, output_plan, state_dir, timeout_sec=2.0
        )

        # Return contract on the timeout path is preserved.
        assert rc == 124, f"expected 124 on timeout, got {rc}"
        assert isinstance(wall, float)
        assert isinstance(stderr_tail, str)

        # The detached grandchild must have written its pidfile by now.
        deadline = time.time() + 5.0
        while not pidfile.exists() and time.time() < deadline:
            time.sleep(0.05)
        assert pidfile.exists(), (
            "grandchild never wrote its pidfile; test seam is broken"
        )
        grandchild_pid = int(pidfile.read_text().strip())

        # Give the kill path a brief moment to take effect.
        deadline = time.time() + 3.0
        while _alive(grandchild_pid) and time.time() < deadline:
            time.sleep(0.05)

        # THE ASSERTION: on a correct fix the whole process group is killed,
        # so the detached grandchild is dead. On HEAD (subprocess.run kills
        # only the direct child) the grandchild is orphaned and SURVIVES -> RED.
        assert not _alive(grandchild_pid), (
            "detached grandchild SURVIVED the planner timeout -> the timeout "
            "path did not reap the whole process group (orphaned to PID 1)"
        )
    finally:
        if grandchild_pid is not None:
            _reap(grandchild_pid)
