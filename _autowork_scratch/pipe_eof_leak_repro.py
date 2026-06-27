#!/usr/bin/env python3
"""Standalone repro for the planner communicate()-pipe-EOF leak.

Models orchestrator.spawn_agent()'s `_is_agy` branch:
    proc = Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE, text=True,
                 start_new_session=True)
    out, err = proc.communicate(input=stdin_prompt, timeout=_timeout)

The real agy/codex agent runs in a bwrap jail and a grandchild
(xdg-dbus-proxy / any forked daemon) INHERITS the stdout pipe write-end and
OUTLIVES the agent. The agent (direct child) exits → zombie, but the grandchild
keeps the pipe write-end open → no EOF on the read end → communicate() blocks
the FULL timeout even though proc has long since exited.

We reproduce that exact topology WITHOUT the real planner: a child process that
spawns a detached grandchild inheriting stdout, prints its own output, then
exits immediately. The grandchild lingers `LINGER` seconds holding the pipe.

We then show:
  A) BASELINE (current orchestrator behavior): communicate(timeout=T) blocks
     ~T (until killpg fires on TimeoutExpired) even though the child exited
     within ~0.1s.
  B) FIX (proposed): poll for child exit, then drain stdout with a SHORT
     post-exit grace deadline; on grace-expiry killpg the child's whole
     process group (reaping the lingering grandchild) and return promptly.

Run:  python3 _autowork_scratch/pipe_eof_leak_repro.py
"""
import os
import signal
import subprocess
import sys
import time

# ---- tunables -------------------------------------------------------------
TIMEOUT = 8.0      # stands in for synthesis.timeout_seconds (real value ~1625)
LINGER = 30.0      # grandchild outlives the child far past TIMEOUT
GRACE = 0.5        # proposed fix: post-exit read grace before killpg
# ---------------------------------------------------------------------------

# The child: print a line, spawn a detached grandchild that inherits our stdout
# (fd 1) and sleeps LINGER seconds, then the child EXITS immediately.
CHILD_SRC = f"""
import os, sys, time
# Print the agent's "solution" so the parent has real bytes to read.
sys.stdout.write("AGENT-OUTPUT-LINE\\n")
sys.stdout.flush()
# Fork a grandchild that inherits fd 1 (stdout PIPE write-end) and lingers,
# mirroring xdg-dbus-proxy outliving the bwrap agent.
pid = os.fork()
if pid == 0:
    # grandchild: keep the inherited stdout fd open, do NOT print to it
    time.sleep({LINGER})
    os._exit(0)
# child (the "agent") exits right away -> becomes a zombie while grandchild lingers
os._exit(0)
"""


def _spawn():
    return subprocess.Popen(
        [sys.executable, "-c", CHILD_SRC],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )


def baseline_communicate():
    """Exactly what orchestrator.py:453 does today."""
    proc = _spawn()
    t0 = time.monotonic()
    killpg_fired = False
    try:
        out, err = proc.communicate(input="prompt", timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        # the existing TimeoutExpired -> killpg handler (orchestrator.py:454-467)
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            killpg_fired = True
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            proc.kill()
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            out, err = proc.communicate(timeout=5)
        except Exception:
            out = ""
        else:
            pass
    dt = time.monotonic() - t0
    return dt, killpg_fired, out


def fixed_drain_on_exit():
    """Proposed fix: as soon as the child has exited (poll), drain stdout with a
    SHORT post-exit grace; if the pipe still hasn't hit EOF (a grandchild holds
    it), killpg the child's group to reap the lingerer, then return promptly.
    Preserves the existing full-timeout TimeoutExpired->killpg fallback for the
    case where the child itself never exits."""
    proc = _spawn()
    t0 = time.monotonic()
    # Push the input prompt (non-blocking-ish; tiny payload, mirrors stdin_prompt).
    try:
        proc.stdin.write("prompt")
        proc.stdin.close()
    except (BrokenPipeError, OSError):
        pass

    killpg_fired = False
    deadline = t0 + TIMEOUT
    exit_seen_at = None
    # Poll for child exit up to the full timeout (preserves old hard cap).
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            exit_seen_at = time.monotonic()
            break
        time.sleep(0.02)

    if exit_seen_at is None:
        # Child never exited within timeout -> existing TimeoutExpired path.
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            killpg_fired = True
        except (ProcessLookupError, PermissionError, OSError):
            pass
        out = ""
        dt = time.monotonic() - t0
        return dt, killpg_fired, out

    # Child exited. Drain remaining stdout with a bounded post-exit grace.
    grace_end = exit_seen_at + GRACE
    chunks = []
    import select
    while time.monotonic() < grace_end:
        r, _, _ = select.select([proc.stdout], [], [], max(0.0, grace_end - time.monotonic()))
        if not r:
            break
        data = os.read(proc.stdout.fileno(), 65536)
        if data == b"" if isinstance(data, bytes) else data == "":
            break  # real EOF (no lingering writer)
        chunks.append(data)
    # Grace expired (or EOF). If a grandchild still holds the pipe, killpg reaps it.
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        killpg_fired = True
    except (ProcessLookupError, PermissionError, OSError):
        pass
    out = "".join(c if isinstance(c, str) else c.decode("utf-8", "replace") for c in chunks)
    dt = time.monotonic() - t0
    return dt, killpg_fired, out


def main():
    print(f"TIMEOUT(stands in for synthesis.timeout_seconds)={TIMEOUT}s  "
          f"LINGER={LINGER}s  GRACE={GRACE}s\n")

    print("[A] BASELINE  proc.communicate(timeout=TIMEOUT)  (orchestrator.py:453 today)")
    dt, killpg, out = baseline_communicate()
    print(f"    elapsed={dt:6.2f}s  killpg_fired={killpg}  captured_output={out!r}")
    blocked_full = dt >= TIMEOUT - 1.0
    print(f"    -> blocked the FULL timeout? {blocked_full}  "
          f"(child exited within ~0.1s; the lingering grandchild held the pipe)\n")

    print("[B] FIX  poll-for-exit + bounded post-exit drain + killpg-the-group")
    dt2, killpg2, out2 = fixed_drain_on_exit()
    print(f"    elapsed={dt2:6.2f}s  killpg_fired={killpg2}  captured_output={out2!r}")
    fast = dt2 <= GRACE + 1.5
    got_output = "AGENT-OUTPUT-LINE" in out2
    print(f"    -> returned promptly (<= GRACE+slack)? {fast}   "
          f"captured the agent's real output? {got_output}\n")

    print("==== VERDICT ====")
    print(f"  baseline elapsed  = {dt:.2f}s  (expect ~{TIMEOUT:.0f}s = full timeout)")
    print(f"  fixed    elapsed  = {dt2:.2f}s  (expect ~{GRACE:.1f}s)")
    speedup = dt / dt2 if dt2 > 0 else float('inf')
    print(f"  speedup           = {speedup:.0f}x")
    ok = blocked_full and fast and got_output
    print(f"  ROOT-CAUSE CONFIRMED + FIX EFFECTIVE: {ok}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
