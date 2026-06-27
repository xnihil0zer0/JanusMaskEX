"""De-risk smoke: drive an INTERACTIVE claude in a tmux pane (overseer substrate)
to perform a one-shot worker-style task and produce a FILE deliverable.

This validates the novel loop the tmux-jailed-claude factory backend needs:
  start interactive claude in tmux  ->  seed a task  ->  wait_idle  ->  file on disk.
The bwrap jail is proven separately (headless path already jails claude); this
smoke isolates the tmux+interactive+seed+idle+file-deliverable mechanics.

Run:  PYTHONPATH=. python _autowork_scratch/tmux_worker_smoke.py
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
import tempfile
import time

from overseer import tmux_session, tmux_seams

REPO = "/home/xnihil0zer0/JanusMaskJR"
CLAUDE_BIN = os.path.join(REPO, ".agents/claude-code/node_modules/.bin/claude")
HOME = os.environ["HOME"]


def tmux_exec(argv):
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=60).stdout


def main() -> int:
    workdir = tempfile.mkdtemp(prefix="tmuxworker_cwd_")
    config_dir = tempfile.mkdtemp(prefix="tmuxworker_cfg_")
    session = f"tmuxworker_{os.getpid()}"
    target = os.path.join(workdir, "OK.txt")

    copied = tmux_seams.seed_config_dir(
        config_dir, home=HOME, copy=shutil.copy2,
        exists=os.path.exists, makedirs=lambda d: os.makedirs(d, exist_ok=True),
    )
    print(f"[smoke] seeded config_dir with {copied}")
    print(f"[smoke] workdir={workdir}")
    print(f"[smoke] claude_bin exists={os.path.exists(CLAUDE_BIN)}")

    inner_argv = tmux_seams.build_interactive_argv(
        CLAUDE_BIN, config_dir, model="opus",
        tools=["Read", "Glob", "Grep", "Write"],
    )
    print(f"[smoke] inner_argv={inner_argv}")

    t0 = time.time()
    ready = tmux_session.start_session(
        session, inner_argv, workdir, tmux_exec=tmux_exec, sleep=time.sleep,
        max_dialog_rounds=20, settle=0.5,
    )
    print(f"[smoke] start_session ready={ready} ({time.time()-t0:.0f}s)")
    if not ready:
        snap = tmux_exec(tmux_session.build_capture_argv(session))
        print("[smoke] PANE SNAPSHOT (not ready):\n" + snap[-2000:])
        tmux_session.kill_session(session, tmux_exec=tmux_exec)
        return 2

    seed = ("Create a file named OK.txt in your current working directory whose "
            "entire contents are exactly the single line: DONE. Use the Write tool. "
            "Do not create any other files. Then you are finished.")
    tmux_session.send_turn(session, seed, tmux_exec=tmux_exec)
    idle = tmux_session.wait_idle(
        session, tmux_exec=tmux_exec, sleep=time.sleep, poll=2.0, timeout=180.0,
    )
    print(f"[smoke] wait_idle returned={idle} ({time.time()-t0:.0f}s total)")

    snap = tmux_exec(tmux_session.build_capture_argv(session))
    print("[smoke] FINAL PANE SNAPSHOT (tail):\n" + snap[-1500:])
    tmux_session.kill_session(session, tmux_exec=tmux_exec)

    exists = os.path.exists(target)
    content = open(target).read() if exists else None
    print(f"\n[smoke] RESULT file_exists={exists} content={content!r}")
    ok = exists and content is not None and content.strip() == "DONE"
    print(f"[smoke] {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
