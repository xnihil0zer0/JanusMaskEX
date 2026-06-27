"""PTY-driven jailed-interactive-claude worker backend (REFERENCE).

Live-debugged before pipeline transcription. This is the CORRECTED module to
replace the co-hallucinated ``harness/tmux_worker.py``.

Transport note: despite the module/entrypoint name (kept for the orchestrator
wiring contract at ``orchestrator.spawn_agent``), the worker drives claude over a
direct **pseudo-terminal** (``pty.fork``), NOT a tmux pane. A bwrap-jailed
INTERACTIVE claude (billed to Max/OAuth, never the headless ``-p`` API) renders
its TUI fine under a PTY but dies in a tmux pane; the PTY is the working transport.

Design:
  * ``run_pty_worker`` is a pure orchestrator over injectable seams (``spawn``,
    ``os_read``, ``os_write``, ``select_fn``, ``os_kill``, ``os_waitpid``,
    ``monotonic``, ``sleep``, ``exists``, ``getsize``) so the leaf oracle exercises
    the real start->ready->send->complete logic over fakes -- no real PTY/claude.
  * ``spawn_claude_tmux`` is the thin real-wiring entrypoint: build the interactive
    argv (overseer.tmux_seams.build_interactive_argv -- never ``-p``), seed a
    per-task CLAUDE_CONFIG_DIR under the jailed work_dir, jail via
    ``agent_jail.build_jail_argv``, then drive via ``run_pty_worker``.

Termination is gated on the DELIVERABLE the orchestrator itself harvests
(``outbox/submission.py`` going non-empty and stable) -- robust, because an
interactive claude keeps its turn "active" (composing prose, retrying MCP) long
after it has written the file. TUI idle (ready footer is the most-recent footer)
is a secondary fallback signal.
"""
from __future__ import annotations
import os
import re
import shutil
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence

from overseer import tmux_seams
from harness import agent_jail

__all__ = ['TmuxWorkerResult', '_ExitedProc', 'seed_from_prompt_file',
           'run_pty_worker', 'spawn_claude_tmux']

READY_MARKER = 'shift+tab to cycle'
IN_FLIGHT_MARKER = 'esc to interrupt'
TRUST_MARKER = 'trust this folder'
BYPASS_MARKER = 'Bypass Permissions mode'

_ANSI = re.compile(
    r'\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][AB012]|[\x00-\x08\x0b\x0c\x0e-\x1f]')


def _strip(b: bytes) -> str:
    return _ANSI.sub('', b.decode('utf-8', 'replace')).replace('\r', '')


def _compact(b: bytes) -> str:
    """Whitespace-removed, lowercased view of the stream.

    The raw PTY render cursor-positions each segment instead of emitting literal
    spaces, so after ANSI-strip 'shift+tab to cycle' reads 'shift+tabtocycle'.
    Markers are matched against this normalized form."""
    return re.sub(r'\s+', '', _strip(b)).lower()


def _norm(marker: str) -> str:
    return re.sub(r'\s+', '', marker).lower()


def _has(b: bytes, marker: str) -> bool:
    return _norm(marker) in _compact(b)


def _latest_idle(b: bytes) -> bool:
    """True iff the most-recent footer rendered is the READY footer.

    Compares the last position of the ready marker vs the in-flight marker in the
    compacted stream. Robust to scrollback (stale 'esc to interrupt' frames do
    not win). Note: while working, claude renders BOTH markers in one footer with
    in-flight last, so this correctly reads as not-idle."""
    c = _compact(b)
    ri = c.rfind(_norm(READY_MARKER))
    fi = c.rfind(_norm(IN_FLIGHT_MARKER))
    return ri != -1 and ri > fi


@dataclass
class TmuxWorkerResult:
    started: bool
    idle: bool
    snapshot: str


class _ExitedProc:
    """A ``Popen``-compatible stand-in for an already-finished worker.

    ``spawn_claude_tmux`` runs synchronously (blocks until the deliverable is
    stable / idle / timeout), so the surrounding headless-oriented harness still
    gets a process handle reporting an immediate clean exit. ``_work_dir`` is
    assignable so callers can stamp where the work landed."""
    returncode: int = 0

    def __init__(self, work_dir: Optional[str] = None) -> None:
        self.returncode = 0
        self._work_dir: Optional[str] = work_dir

    def poll(self) -> int:
        return 0

    def wait(self, timeout: Optional[float] = None) -> int:
        return 0

    def kill(self) -> None:
        return None

    def terminate(self) -> None:
        return None

    def __repr__(self) -> str:
        return f'_ExitedProc(returncode=0, _work_dir={self._work_dir!r})'


def seed_from_prompt_file(prompt_filename: str = '.tmux_prompt.txt') -> str:
    """The short turn text that points claude at the full prompt on disk.

    Large worker prompts are written to a file in the work dir; the interactive
    seed (typed into the PTY) is just a short instruction to read and execute it,
    keeping the typed turn small and reliable."""
    return (f"Read the file {prompt_filename} in your current working directory "
            "and carry out its instructions exactly.")


def _default_spawn(argv: Sequence[str], cwd: str):
    """Fork a child attached to a fresh PTY; child execs ``argv`` in ``cwd``.

    Returns ``(pid, master_fd)``. In the child the PTY slave is already the
    controlling terminal (``pty.fork`` handles setsid + TIOCSCTTY), which is what
    makes the bwrap-jailed claude render its interactive TUI."""
    import pty
    pid, master_fd = pty.fork()
    if pid == 0:
        try:
            os.chdir(cwd)
            os.execvp(argv[0], list(argv))
        except Exception as exc:  # pragma: no cover - child branch
            try:
                os.write(2, f'exec failed: {exc}\n'.encode())
            except Exception:
                pass
        os._exit(127)
    return pid, master_fd


def _set_pty_geometry(master_fd: int, cols: int, rows: int) -> None:
    """Best-effort: size the PTY and make the master non-blocking.

    Wrapped so fake integer fds in tests (where ioctl/fcntl raise) are tolerated."""
    try:
        import fcntl
        import termios
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    except Exception:
        pass


def run_pty_worker(*, jailed_argv: Sequence[str], work_dir: str, seed: str,
                   deliverable: Optional[str] = None,
                   cols: int = 200, rows: int = 50,
                   startup_timeout: float = 90.0, idle_timeout: float = 1200.0,
                   poll: float = 1.0, settle_k: int = 3, min_work: float = 4.0,
                   grace: float = 25.0,
                   spawn: Optional[Callable[..., Any]] = None,
                   os_read: Optional[Callable[[int, int], bytes]] = None,
                   os_write: Optional[Callable[[int, bytes], int]] = None,
                   select_fn: Optional[Callable[..., Any]] = None,
                   os_kill: Optional[Callable[[int, int], Any]] = None,
                   os_waitpid: Optional[Callable[[int, int], Any]] = None,
                   os_close: Optional[Callable[[int], Any]] = None,
                   monotonic: Optional[Callable[[], float]] = None,
                   sleep: Optional[Callable[[float], Any]] = None,
                   exists: Optional[Callable[[str], bool]] = None,
                   getsize: Optional[Callable[[str], int]] = None,
                   set_geometry: Optional[Callable[[int, int, int], Any]] = None) -> TmuxWorkerResult:
    """Drive one interactive-claude turn over a PTY and report the result.

    Orchestration: spawn jailed claude on a PTY -> pump output until the READY
    footer appears (auto-answering the trust/bypass startup dialogs) -> type the
    ``seed`` turn + Enter -> wait until the deliverable is non-empty and stable
    for ``settle_k`` polls (primary) or the TUI returns to idle (fallback), or
    ``idle_timeout`` elapses -> tear the child down. Every real syscall is an
    injectable seam, so the unit oracle exercises this logic over fakes without a
    real PTY or claude. The child is always killed in the ``finally`` block.
    """
    import select as _select
    import signal as _signal
    spawn = spawn or _default_spawn
    os_read = os_read or os.read
    os_write = os_write or os.write
    select_fn = select_fn or _select.select
    os_kill = os_kill or os.kill
    os_waitpid = os_waitpid or os.waitpid
    os_close = os_close or os.close
    monotonic = monotonic or time.monotonic
    sleep = sleep or time.sleep
    exists = exists or os.path.exists
    getsize = getsize or os.path.getsize
    set_geometry = set_geometry or _set_pty_geometry
    if deliverable is None:
        deliverable = os.path.join(str(work_dir), 'outbox', 'submission.py')

    started = False
    idle = False
    buf = bytearray()
    pid = None
    master_fd = None

    def pump(window: float) -> bool:
        end = monotonic() + window
        while monotonic() < end:
            remaining = max(0.0, end - monotonic())
            try:
                r, _w, _x = select_fn([master_fd], [], [], remaining)
            except Exception:
                return False
            if not r:
                continue
            try:
                chunk = os_read(master_fd, 65536)
            except OSError:
                return False
            if not chunk:
                return False
            buf.extend(chunk)
            del buf[:-65536]
        return True

    try:
        pid, master_fd = spawn(jailed_argv, str(work_dir))
        started = True
        set_geometry(master_fd, cols, rows)

        # --- startup: auto-answer dialogs until the input box is ready ---
        answered = set()
        t0 = monotonic()
        ready = False
        while monotonic() - t0 < startup_timeout:
            pump(0.5)
            if _has(bytes(buf), READY_MARKER):
                ready = True
                break
            if _has(bytes(buf), TRUST_MARKER) and 'trust' not in answered:
                os_write(master_fd, b'\r')
                answered.add('trust')
                sleep(0.4)
            elif _has(bytes(buf), BYPASS_MARKER) and 'bypass' not in answered:
                os_write(master_fd, b'\x1b[B')
                sleep(0.2)
                os_write(master_fd, b'\r')
                answered.add('bypass')
                sleep(0.4)
        if not ready:
            return TmuxWorkerResult(started=started, idle=False, snapshot=_strip(bytes(buf)))

        # --- send the seed turn ---
        os_write(master_fd, seed.encode('utf-8'))
        sleep(0.5)
        os_write(master_fd, b'\r')

        # --- wait for completion ---
        consec = 0
        seen_work = False
        deliv_size = -1
        deliv_stable = 0
        work_start = monotonic()
        deadline = work_start + idle_timeout
        while monotonic() < deadline:
            pump(poll)
            at_idle = _latest_idle(bytes(buf))
            if not at_idle and _has(bytes(buf), IN_FLIGHT_MARKER):
                seen_work = True
            # PRIMARY: the deliverable the orchestrator harvests is stable.
            if exists(deliverable):
                try:
                    sz = int(getsize(deliverable))
                except OSError:
                    sz = 0
                if sz > 0 and sz == deliv_size:
                    deliv_stable += 1
                    if deliv_stable >= settle_k:
                        idle = True
                        break
                else:
                    deliv_stable = 0
                deliv_size = sz
            # FALLBACK: TUI returned to idle after the working phase.
            el = monotonic() - work_start
            if at_idle and el >= min_work and (seen_work or el >= grace):
                consec += 1
                if consec >= settle_k:
                    idle = True
                    break
            else:
                consec = 0
        return TmuxWorkerResult(started=started, idle=idle, snapshot=_strip(bytes(buf)))
    except Exception as exc:
        return TmuxWorkerResult(started=started, idle=idle,
                                snapshot=_strip(bytes(buf)) + f'\n<run_pty_worker error: {exc!r}>')
    finally:
        if pid is not None:
            try:
                os_kill(pid, _signal.SIGTERM)
                sleep(0.3)
                os_kill(pid, _signal.SIGKILL)
            except OSError:
                pass
            try:
                os_waitpid(pid, 0)
            except OSError:
                pass
        if master_fd is not None:
            try:
                os_close(master_fd)
            except OSError:
                pass


def _parse_model_tools(agent_cfg: dict) -> tuple:
    """Extract (model, tools) from the configured headless claude args.

    The factory's ``agents.claude`` entry carries ``--model``/``--tools`` for the
    headless backend; we reuse the same model and tool allowlist for the
    interactive PTY backend so containment (Read/Glob/Grep/Write, no Bash) holds."""
    args = list(agent_cfg.get('args') or [])
    model = 'opus'
    tools = ['Read', 'Glob', 'Grep', 'Write']
    if '--model' in args:
        i = args.index('--model')
        if i + 1 < len(args):
            model = str(args[i + 1])
    if '--tools' in args:
        i = args.index('--tools')
        if i + 1 < len(args):
            tools = [t for t in str(args[i + 1]).split(',') if t]
    return model, tools


def spawn_claude_tmux(agent: str, resolved_prompt: str, env: dict, config: dict, *,
                      dbus_sock: Optional[str] = None) -> _ExitedProc:
    """Real-wiring entrypoint: launch a bwrap-jailed interactive claude over a PTY.

    Builds the interactive argv (never ``-p``), seeds a per-task
    ``CLAUDE_CONFIG_DIR`` UNDER the jailed work_dir so claude reads its OAuth
    creds from inside the sandbox, jails the argv, writes the full prompt to a
    file the seed turn points at, and drives the turn to completion via
    :func:`run_pty_worker`. Returns an :class:`_ExitedProc` stamped with the work
    dir; the orchestrator then harvests ``outbox/submission.py`` as usual."""
    work_dir = env['JANUSMASK_WORK_DIR']
    state_dir = env['JANUSMASK_STATE_DIR']
    task_id = str(env.get('JANUSMASK_TASK_ID') or 'worker')
    agent_cfg = config['agents'][agent]
    claude_bin = agent_cfg['command']
    model, tools = _parse_model_tools(agent_cfg)

    config_dir = os.path.join(work_dir, '.tmuxcfg')
    tmux_seams.seed_config_dir(config_dir, home=os.environ['HOME'], copy=shutil.copy2,
                               exists=os.path.exists,
                               makedirs=lambda d: os.makedirs(d, exist_ok=True))
    interactive = tmux_seams.build_interactive_argv(claude_bin, config_dir, model=model, tools=tools)

    from harness.paths import _target_is_self, effective_target_root, PROJECT_ROOT as PROJECT_DIR
    working_dir = os.environ.get('JANUSMASK_WORKING_DIR')
    repo_root = str(PROJECT_DIR) if _target_is_self(working_dir) else str(effective_target_root(working_dir))
    jailed = agent_jail.build_jail_argv(interactive, repo_root=repo_root, work_dir=work_dir,
                                        state_dir=state_dir, dbus_proxy_socket=dbus_sock)

    Path(work_dir, '.tmux_prompt.txt').write_text(resolved_prompt or '')

    timeout = float((config.get('synthesis') or {}).get('timeout_seconds', 1200))
    run_pty_worker(jailed_argv=jailed, work_dir=work_dir, seed=seed_from_prompt_file(),
                   idle_timeout=timeout)
    return _ExitedProc(work_dir=str(work_dir))
