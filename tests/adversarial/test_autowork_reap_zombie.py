"""Adversarial regression bar for G27 — _reap_running must detect zombie children.

Background: harness/autowork_daemon.py:_reap_running uses ``os.kill(pid, 0)``
to test process liveness. On Linux that call returns SUCCESS for a
<defunct>/zombie process — the kernel keeps the PID entry until the parent
``wait()``s on it. The autowork daemon's Popen workers become zombies
after they exit (parent never wait()s in the per-iteration loop), so
``_reap_running`` treats them as alive forever, the pidfile stays in place,
and the daemon never returns ``free_slots == cap`` to enter the idle path.

Witnessed in session #13 (G25 v1 dogfood, ledger ts 1779172711..1779186452):
daemon held in false-busy state for ~3.8 hours after worker_exit.

Two tests pin the platform contract + the regression bar:

1. ``test_kill_pid_zero_succeeds_on_zombie`` (contract, always passes):
   confirms the structural bug surface — kill(0) returns 0 on a zombie.
2. ``test_reap_running_treats_zombie_as_dead`` (regression bar):
   passes naturally under the waitpid(WNOHANG)-based liveness check
   landed in commit 2eef9df.
"""
from __future__ import annotations

import os
import pathlib
import time


def _spawn_zombie() -> int:
    """Fork a child that exits immediately; return its pid after it has
    entered the <defunct> (Z) state. Caller is responsible for eventually
    waiting on the pid to release the zombie entry."""
    pid = os.fork()
    if pid == 0:  # child
        os._exit(0)
    deadline = time.time() + 2.0
    while time.time() < deadline:
        try:
            with open(f"/proc/{pid}/status", encoding="utf-8") as fh:
                content = fh.read()
            if "State:\tZ" in content or "State:  Z" in content:
                return pid
            if "State:\tX" in content:  # dead-and-reaped
                return pid
        except (OSError, FileNotFoundError):
            return pid
        time.sleep(0.05)
    return pid


def _reap_quietly(pid: int) -> None:
    try:
        os.waitpid(pid, os.WNOHANG)
    except (ChildProcessError, OSError):
        pass


def test_kill_pid_zero_succeeds_on_zombie() -> None:
    """Pin the platform fact: os.kill(pid, 0) returns success on a zombie.

    This is the structural reason _reap_running's current liveness check
    misclassifies zombies as alive. If this test ever starts failing on
    a future kernel/libc, the G27 rationale needs revisiting."""
    pid = _spawn_zombie()
    try:
        try:
            os.kill(pid, 0)
            kill_returned = True
        except (ProcessLookupError, OSError):
            kill_returned = False
        # Confirm the same pid is also detectable via waitpid(WNOHANG),
        # which is the recommended fix surface.
        try:
            reaped_pid, _status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            reaped_pid = pid  # already reaped by some other path
    finally:
        _reap_quietly(pid)
    assert kill_returned, (
        "platform regression: kill(pid, 0) did NOT succeed on a zombie pid; "
        "G27's rationale needs revisiting."
    )
    assert reaped_pid in (pid, 0), (
        f"waitpid(pid, WNOHANG) returned unexpected value: {reaped_pid!r}"
    )


def test_reap_running_treats_zombie_as_dead(tmp_path: pathlib.Path) -> None:
    from harness.autowork_daemon import _reap_running

    state_dir = tmp_path / "state"
    rdir = state_dir / "control" / "autowork" / "running"
    rdir.mkdir(parents=True)

    pid = _spawn_zombie()
    pidfile = rdir / "ZOMBIE_TASK.pid"
    pidfile.write_text(str(pid), encoding="utf-8")

    try:
        live = _reap_running(state_dir)
    finally:
        _reap_quietly(pid)

    assert "ZOMBIE_TASK" not in live, (
        f"_reap_running classified a zombie pid as alive (live={live!r}); "
        f"daemon would stay in false-busy state indefinitely."
    )
    assert not pidfile.exists(), (
        "_reap_running did not unlink the zombie's pidfile; "
        "pidfile leak will accumulate over daemon lifetime."
    )
