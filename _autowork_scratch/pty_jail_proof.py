"""PROOF: bwrap-jailed INTERACTIVE claude driven over a direct PTY (pty.fork).

Builds the exact jailed interactive-claude argv that spawn_claude_tmux builds,
but launches it attached to a pseudo-terminal allocated by pty.fork instead of a
tmux pane. Drives: reach ready -> answer startup dialogs -> send seed -> wait
idle -> confirm the deliverable file landed.

Run: PYTHONPATH=. python _autowork_scratch/pty_jail_proof.py
"""
from __future__ import annotations
import os, pty, re, shutil, struct, fcntl, termios, time, signal, select, tempfile, yaml
from pathlib import Path
from overseer import tmux_seams
from harness import agent_jail
from harness.paths import PROJECT_ROOT

READY = 'shift+tab to cycle'
IN_FLIGHT = 'esc to interrupt'
TRUST = 'trust this folder'
BYPASS = 'Bypass Permissions mode'

_ANSI = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][AB012]|[\x00-\x08\x0b\x0c\x0e-\x1f]')

def strip(b: bytes) -> str:
    return _ANSI.sub('', b.decode('utf-8', 'replace')).replace('\r', '')

def compact(b: bytes) -> str:
    """Whitespace-removed, lowercased view of the stream.

    The raw PTY render cursor-positions each segment instead of emitting literal
    spaces, so after ANSI-strip 'shift+tab to cycle' reads 'shift+tabtocycle'.
    Match markers against this normalized form."""
    return re.sub(r'\s+', '', strip(b)).lower()

def _has(b: bytes, marker: str) -> bool:
    return re.sub(r'\s+', '', marker).lower() in compact(b)

def _norm(marker: str) -> str:
    return re.sub(r'\s+', '', marker).lower()

def _latest_idle(b: bytes) -> bool:
    """True iff the most-recent footer in the stream is the READY footer.

    Compares the last position of the ready marker vs the in-flight marker in the
    compacted stream: whichever claude rendered most recently reflects current
    state. Robust to scrollback (old 'esc to interrupt' frames don't win)."""
    c = compact(b)
    ri = c.rfind(_norm(READY))
    fi = c.rfind(_norm(IN_FLIGHT))
    return ri != -1 and ri > fi


def build_jailed():
    REPO = str(PROJECT_ROOT)
    cfg = yaml.safe_load(open(os.path.join(REPO, "harness/config.yaml")))
    claude_bin = cfg["agents"]["claude"]["command"].replace("${PROJECT_ROOT}", REPO)
    work_dir = tempfile.mkdtemp(prefix="ptyproof_")
    state_dir = os.path.join(REPO, "state")
    (Path(work_dir) / "outbox").mkdir(parents=True, exist_ok=True)
    config_dir = os.path.join(work_dir, ".tmuxcfg")
    tmux_seams.seed_config_dir(config_dir, home=os.environ["HOME"], copy=shutil.copy2,
                               exists=os.path.exists, makedirs=lambda d: os.makedirs(d, exist_ok=True))
    interactive = tmux_seams.build_interactive_argv(claude_bin, config_dir, model="opus",
                                                    tools=["Read", "Glob", "Grep", "Write"])
    jailed = agent_jail.build_jail_argv(interactive, repo_root=REPO, work_dir=work_dir,
                                        state_dir=state_dir, dbus_proxy_socket=None)
    return jailed, work_dir


def run_pty(jailed, work_dir, seed, *, cols=200, rows=50,
            startup_timeout=90.0, idle_timeout=180.0, poll=1.0, settle_k=3, min_work=4.0):
    pid, master = pty.fork()
    if pid == 0:
        try:
            os.chdir(work_dir)
            os.execvp(jailed[0], jailed)
        except Exception as e:
            os.write(2, f"exec failed: {e}\n".encode())
        os._exit(127)
    # parent
    try:
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
    except Exception:
        pass
    fl = fcntl.fcntl(master, fcntl.F_GETFL)
    fcntl.fcntl(master, fcntl.F_SETFL, fl | os.O_NONBLOCK)
    buf = bytearray()

    def pump(window=0.4):
        end = time.monotonic() + window
        while time.monotonic() < end:
            r, _, _ = select.select([master], [], [], max(0.0, end - time.monotonic()))
            if not r:
                continue
            try:
                chunk = os.read(master, 65536)
            except OSError:
                return False
            if not chunk:
                return False
            buf.extend(chunk)
            del buf[:-65536]
        return True

    def screen():
        return strip(bytes(buf))

    # --- startup: answer dialogs until ready ---
    answered = set()
    t0 = time.monotonic()
    ready = False
    while time.monotonic() - t0 < startup_timeout:
        alive = pump(0.5)
        if _has(bytes(buf), READY):
            ready = True
            break
        if _has(bytes(buf), TRUST) and 'trust' not in answered:
            os.write(master, b'\r'); answered.add('trust'); time.sleep(0.4)
        elif _has(bytes(buf), BYPASS) and 'bypass' not in answered:
            os.write(master, b'\x1b[B'); time.sleep(0.2); os.write(master, b'\r')
            answered.add('bypass'); time.sleep(0.4)
        if not alive and os.waitpid(pid, os.WNOHANG)[0] != 0:
            return {'ready': False, 'idle': False, 'dead_early': True, 'screen': screen()}
    if not ready:
        _kill(pid)
        return {'ready': False, 'idle': False, 'screen': screen()}

    print(f"[run] READY reached at {time.monotonic()-t0:.0f}s; sending seed", flush=True)
    # --- send the seed turn ---
    os.write(master, seed.encode('utf-8'))
    time.sleep(0.5)
    os.write(master, b'\r')

    # --- wait idle ---
    # Idle detection works on PER-INTERVAL output, not the accumulated stream: a
    # working claude continuously redraws the spinner ('esc to interrupt') every
    # poll, so each interval's fresh bytes carry the marker; a finished claude
    # emits nothing new, so the interval is clean.
    consec = 0
    seen_work = False
    work_start = time.monotonic()
    idle = False
    deadline = time.monotonic() + idle_timeout
    grace = 25.0  # fallback: allow idle even if working phase was never observed
    last_log = 0.0
    deliverable = Path(work_dir) / "outbox" / "submission.py"
    deliv_size = -1
    deliv_stable = 0
    while time.monotonic() < deadline:
        pump(poll)
        at_idle = _latest_idle(bytes(buf))
        if not at_idle and _has(bytes(buf), IN_FLIGHT):
            seen_work = True
        el = time.monotonic() - work_start
        # Authoritative early-exit: the deliverable the orchestrator gates on has
        # appeared and stopped changing. Independent of TUI idle quirks.
        if deliverable.exists():
            sz = deliverable.stat().st_size
            if sz > 0 and sz == deliv_size:
                deliv_stable += 1
                if deliv_stable >= settle_k:
                    idle = True
                    break
            else:
                deliv_stable = 0
            deliv_size = sz
        if el - last_log >= 10:
            last_log = el
            print(f"[run] t={el:.0f}s at_idle={at_idle} seen_work={seen_work} consec={consec} deliv={deliverable.exists()} stable={deliv_stable}", flush=True)
        if at_idle and el >= min_work and (seen_work or el >= grace):
            consec += 1
            if consec >= settle_k:
                idle = True
                break
        else:
            consec = 0
    c = compact(bytes(buf))
    ri = c.rfind(_norm(READY)); fi = c.rfind(_norm(IN_FLIGHT))
    print(f"[dbg] rfind ready={ri} in_flight={fi} len={len(c)}", flush=True)
    print(f"[dbg] tail compact: ...{c[-400:]!r}", flush=True)
    _kill(pid)
    return {'ready': True, 'idle': idle, 'screen': screen()}


def _kill(pid):
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(0.5)
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        os.waitpid(pid, 0)
    except OSError:
        pass


if __name__ == '__main__':
    jailed, work_dir = build_jailed()
    print(f"[proof] work_dir={work_dir}")
    print(f"[proof] jailed[:10]={jailed[:10]}")
    Path(work_dir, '.tmux_prompt.txt').write_text(
        "Write a file at outbox/submission.py whose entire contents are exactly:\n\n"
        "print('PTY_JAIL_OK')\n\nUse the Write tool. Create no other files. Then you are finished.\n")
    seed = ("Read the file .tmux_prompt.txt in your current working directory and "
            "carry out its instructions exactly.")
    t0 = time.time()
    res = run_pty(jailed, work_dir, seed)
    dt = time.time() - t0
    print(f"[proof] ready={res['ready']} idle={res['idle']} dead_early={res.get('dead_early')} in {dt:.0f}s")
    print("[proof] === final screen tail ===")
    print('\n'.join(res['screen'].splitlines()[-25:]))
    sub = Path(work_dir) / "outbox" / "submission.py"
    ok = sub.exists() and 'PTY_JAIL_OK' in sub.read_text()
    print(f"[proof] outbox/submission.py exists={sub.exists()} content={sub.read_text() if sub.exists() else None!r}")
    print("[proof]", "PASS" if ok else "FAIL")
