"""tmux worker execution backend and process wrappers.

This module implements an *additive, flag-gated* backend for running an
interactive ``claude`` instance inside a ``tmux`` session as a worker. It is
deliberately built around small, injectable seams so that the leaf tests can
exercise the pure orchestration logic over fakes -- no real ``tmux`` session
or ``claude`` process is ever spawned by the unit tests.

The heavy lifting (creating sessions, sending keys, capturing panes) is
delegated to helpers in ``overseer/tmux_session.py`` and
``overseer/tmux_seams.py``; command jailing is delegated to
``harness/agent_jail.py``. All of those imports are optional: the module is
importable even when those backends are unavailable, and the default
executor *raises* (never hangs) when ``tmux``/``bwrap`` are not configured.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any
from typing import Callable
from typing import List
from typing import Mapping
from typing import Optional
from typing import Sequence
try:
    from overseer import tmux_session as _tmux_session
except Exception:
    _tmux_session = None
try:
    from overseer import tmux_seams as _tmux_seams
except Exception:
    _tmux_seams = None
try:
    from harness import agent_jail as _agent_jail
except Exception:
    _agent_jail = None
__all__ = ['TmuxWorkerResult', '_ExitedProc', 'seed_from_prompt_file', 'run_pty_worker', 'spawn_claude_tmux']

@dataclass
class TmuxWorkerResult:
    """Structured result of orchestrating a single tmux worker turn.

    The spec models this as a ``NamedTuple`` of ``(started, idle, snapshot)``.
    We implement it as a thin ``tuple`` subclass so the type is import-safe
    (it needs no extra ``typing`` import) while remaining fully NamedTuple
    compatible: it is an immutable 3-tuple, supports unpacking and equality,
    exposes ``started``/``idle``/``snapshot`` attributes and the familiar
    ``_fields`` / ``_asdict`` / ``_replace`` surface.

    Attributes:
        started: True when ``start_session`` reported a live session.
        idle: True when ``wait_idle`` observed the pane settle in time.
        snapshot: The final captured pane text (empty string when none).
    """
    __slots__ = ()
    _fields = ('started', 'idle', 'snapshot')

    def __new__(cls, started: bool=False, idle: bool=False, snapshot: str='') -> 'TmuxWorkerResult':
        return tuple.__new__(cls, (bool(started), bool(idle), snapshot if snapshot is not None else ''))

    @property
    def started(self) -> bool:
        """True when a tmux session was successfully started."""
        return self[0]

    @property
    def idle(self) -> bool:
        """True when the pane was observed to go idle within the timeout."""
        return self[1]

    @property
    def snapshot(self) -> str:
        """The final captured pane snapshot (possibly empty)."""
        return self[2]

    def _asdict(self) -> dict:
        """Return an ordered mapping of field name -> value (NamedTuple parity)."""
        return {'started': self[0], 'idle': self[1], 'snapshot': self[2]}

    def _replace(self, **kwargs: Any) -> 'TmuxWorkerResult':
        """Return a copy with the named fields replaced (NamedTuple parity)."""
        values = self._asdict()
        for key in kwargs:
            if key not in values:
                raise ValueError('Got unexpected field name: ' + repr(key))
        values.update(kwargs)
        return TmuxWorkerResult(**values)

    def __repr__(self) -> str:
        return 'TmuxWorkerResult(started={0!r}, idle={1!r}, snapshot={2!r})'.format(self[0], self[1], self[2])
    started: bool
    idle: bool
    snapshot: str

class _ExitedProc:
    """A ``Popen``-compatible stand-in for an already-finished process.

    ``spawn_claude_tmux`` hands control to a detached tmux session, so the
    surrounding (headless-oriented) harness still expects a process handle. We
    return this object, which presents the minimal ``subprocess.Popen``
    surface the harness polls on, reporting an immediate clean exit. The
    ``_work_dir`` attribute is assignable so callers can stamp where the work
    landed.
    """
    returncode: int = 0

    def __init__(self, work_dir: Optional[str]=None) -> None:
        self.returncode = 0
        self._work_dir: Optional[str] = work_dir

    def poll(self) -> int:
        return 0

    def wait(self, timeout: Optional[float]=None) -> int:
        return 0

    def kill(self) -> None:
        return None

    def terminate(self) -> None:
        return None

    def __repr__(self) -> str:
        return f'_ExitedProc(returncode=0, _work_dir={self._work_dir!r})'
    'A ``Popen``-compatible stand-in for an already-finished worker.\n\n    ``spawn_claude_tmux`` runs synchronously (blocks until the deliverable is\n    stable / idle / timeout), so the surrounding headless-oriented harness still\n    gets a process handle reporting an immediate clean exit. ``_work_dir`` is\n    assignable so callers can stamp where the work landed.'

def _as_mapping(config: Any) -> dict:
    """Coerce ``config`` into a plain ``dict``, tolerating None / objects.

    Handles the edge case of a missing or non-mapping config gracefully by
    returning an empty mapping rather than raising.
    """
    if config is None:
        return {}
    if isinstance(config, Mapping):
        return dict(config)
    if hasattr(config, '__dict__'):
        return {k: v for k, v in vars(config).items() if not k.startswith('__')}
    return {}

def _cfg_get(config: Mapping, *keys: str, default: Any=None) -> Any:
    """Return the first present, non-empty value among ``keys``.

    Empty values (``""``, ``[]``, ``{}``, ``None``) fall through to the next
    key and finally to ``default`` -- this is what lets callers pass partial
    config without tripping over empty placeholders.
    """
    for key in keys:
        if key in config:
            value = config[key]
            if value not in (None, '', [], {}):
                return value
    return default

def _default_session_name(env: Mapping) -> str:
    """Derive a stable, collision-resistant tmux session name."""
    task_id = str(env.get('JANUSMASK_TASK_ID') or 'worker').strip() or 'worker'
    safe = ''.join((c if c.isalnum() or c in '-_' else '_' for c in task_id))
    return f'janusmask-{safe}'

def seed_from_prompt_file(prompt_filename: str='.tmux_prompt.txt') -> str:
    """The short turn text that points claude at the full prompt on disk.

    Large worker prompts are written to a file in the work dir; the interactive
    seed (typed into the PTY) is just a short instruction to read and execute it,
    keeping the typed turn small and reliable."""
    return f'Read the file {prompt_filename} in your current working directory and carry out its instructions exactly.'

def jail_command(command: Sequence[str], *, env: Mapping, work_dir: Any, state_dir: Any, dbus_sock: Optional[str]=None, config: Any=None) -> List[str]:
    """Wrap ``command`` in a sandbox using ``harness/agent_jail.py``.

    The exact jailing entrypoint name varies across backend versions, so we
    probe a small set of common names. When no jail backend is available the
    command is returned unchanged -- callers (and the default executor) are
    responsible for refusing to spawn when bwrap is genuinely required.
    """
    if _agent_jail is None:
        return list(command)
    candidates = ('build_jail_command', 'jail_command', 'wrap_command', 'build_command', 'jail')
    for name in candidates:
        fn = getattr(_agent_jail, name, None)
        if not callable(fn):
            continue
        try:
            result = fn(list(command), env=dict(env), work_dir=str(work_dir), state_dir=str(state_dir), dbus_sock=dbus_sock)
        except TypeError:
            try:
                result = fn(list(command))
            except Exception:
                continue
        except Exception:
            continue
        if result:
            return list(result)
    return list(command)

def _resolve_tmux_seam() -> Optional[Callable[..., Any]]:
    """Locate a runnable tmux seam from the optional backends.

    Returns ``None`` when no backend is available -- the default executor uses
    this to raise a clear error instead of hanging on a missing ``tmux``.
    """
    for module in (_tmux_seams, _tmux_session):
        if module is None:
            continue
        for name in ('run_in_session', 'run_session', 'run_command', 'run'):
            fn = getattr(module, name, None)
            if callable(fn):
                return fn
    return None

def _tmux_executor(command: Sequence[str], *, env: Mapping, work_dir: Any, session_name: str, config: Any=None) -> int:
    """Default executor: drive the real tmux seams.

    Raises ``RuntimeError`` (rather than blocking) when neither ``tmux`` seams
    are importable, honoring the "no bwrap/tmux -> error, don't hang" contract.
    """
    seam = _resolve_tmux_seam()
    if seam is None:
        raise RuntimeError('tmux backend is not configured in this environment; cannot spawn an interactive tmux worker')
    result = seam(list(command), env=dict(env), work_dir=str(work_dir), session_name=session_name)
    if isinstance(result, int):
        return result
    return int(getattr(result, 'returncode', 0) or 0)

def run_tmux_worker(*, session: str, inner_argv: List[str], cwd: str, seed: str, tmux_exec: Callable[..., Any], sleep: Callable[..., Any], timeout: float=1800.0, poll: float=2.0, start_session: Optional[Callable[..., Any]]=getattr(_tmux_session, 'start_session', None), send_turn: Optional[Callable[..., Any]]=getattr(_tmux_session, 'send_turn', None), wait_idle: Optional[Callable[..., Any]]=getattr(_tmux_session, 'wait_idle', None), capture: Optional[Callable[..., Any]]=getattr(_tmux_seams, 'capture_pane', None) or getattr(_tmux_session, 'capture_pane', None)) -> 'TmuxWorkerResult':
    """Drive one tmux worker turn over injectable seams and report the result.

    Orchestration is strictly ``start_session -> send_turn -> wait_idle`` with a
    final pane snapshot. Every real action is delegated to an injected seam
    (``tmux_exec``, ``sleep``, ``start_session``, ``send_turn``, ``wait_idle``,
    ``capture``); this function itself spawns nothing. The default seams resolve
    to ``overseer.tmux_session`` helpers when that backend is importable and to
    ``None`` otherwise, so the module stays importable and inert until a caller
    injects working seams.

    Contract / edge cases:
      * If ``start_session`` reports a falsey value, ``send_turn``/``wait_idle``
        are skipped; the result is ``started=False``.
      * If ``wait_idle`` reports falsey, the result is ``started=True,
        idle=False``.
      * Any exception raised by a seam is caught (never re-raised); the result
        is ``started=False, idle=False``.

    In all paths the session is torn down via ``tmux_exec`` inside a ``finally``
    block, and a :class:`TmuxWorkerResult` is always returned.
    """
    started = False
    idle = False
    snapshot = ''
    try:
        if start_session is not None:
            started = bool(start_session(session, inner_argv, cwd=cwd, tmux_exec=tmux_exec))
        if started:
            if send_turn is not None:
                send_turn(session, seed, tmux_exec=tmux_exec, sleep=sleep)
            if wait_idle is not None:
                idle = bool(wait_idle(session, tmux_exec=tmux_exec, sleep=sleep, timeout=timeout, poll=poll))
            if capture is not None:
                try:
                    snapshot = str(capture(session, tmux_exec=tmux_exec) or '')
                except Exception:
                    snapshot = ''
    except Exception:
        started = False
        idle = False
    finally:
        try:
            tmux_exec(['kill-session', '-t', session])
        except Exception:
            pass
    return TmuxWorkerResult(started=started, idle=idle, snapshot=snapshot)

def _build_claude_command(agent: Any, config: Any, prompt_file: Path) -> List[str]:
    """Construct the base (unjailed) interactive claude invocation."""
    cfg = _as_mapping(config)
    claude_bin = _cfg_get(cfg, 'claude_bin', 'claude_path', default='claude')
    cmd: List[str] = [str(claude_bin)]
    extra = _cfg_get(cfg, 'claude_args', 'args', default=None)
    if extra:
        cmd.extend((str(a) for a in extra))
    return cmd

def spawn_claude_tmux(agent: str, resolved_prompt: str, env: dict, config: dict, *, dbus_sock: Optional[str]=None) -> _ExitedProc:
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
    tmux_seams.seed_config_dir(config_dir, home=os.environ['HOME'], copy=shutil.copy2, exists=os.path.exists, makedirs=lambda d: os.makedirs(d, exist_ok=True))
    interactive = tmux_seams.build_interactive_argv(claude_bin, config_dir, model=model, tools=tools)
    from harness.paths import _target_is_self, effective_target_root, PROJECT_ROOT as PROJECT_DIR
    working_dir = os.environ.get('JANUSMASK_WORKING_DIR')
    repo_root = str(PROJECT_DIR) if _target_is_self(working_dir) else str(effective_target_root(working_dir))
    jailed = agent_jail.build_jail_argv(interactive, repo_root=repo_root, work_dir=work_dir, state_dir=state_dir, dbus_proxy_socket=dbus_sock)
    Path(work_dir, '.tmux_prompt.txt').write_text(resolved_prompt or '')
    timeout = float((config.get('synthesis') or {}).get('timeout_seconds', 1200))
    run_pty_worker(jailed_argv=jailed, work_dir=work_dir, seed=seed_from_prompt_file(), idle_timeout=timeout)
    return _ExitedProc(work_dir=str(work_dir))
import re
import shutil
import struct
import time
from overseer import tmux_seams
from harness import agent_jail
READY_MARKER = 'shift+tab to cycle'
IN_FLIGHT_MARKER = 'esc to interrupt'
TRUST_MARKER = 'trust this folder'
BYPASS_MARKER = 'Bypass Permissions mode'
_ANSI = re.compile('\\x1b\\[[0-9;?]*[ -/]*[@-~]|\\x1b\\][^\\x07\\x1b]*(?:\\x07|\\x1b\\\\)|\\x1b[()][AB012]|[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f]')

def _strip(b: bytes) -> str:
    return _ANSI.sub('', b.decode('utf-8', 'replace')).replace('\r', '')

def _compact(b: bytes) -> str:
    """Whitespace-removed, lowercased view of the stream.

    The raw PTY render cursor-positions each segment instead of emitting literal
    spaces, so after ANSI-strip 'shift+tab to cycle' reads 'shift+tabtocycle'.
    Markers are matched against this normalized form."""
    return re.sub('\\s+', '', _strip(b)).lower()

def _norm(marker: str) -> str:
    return re.sub('\\s+', '', marker).lower()

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
        except Exception as exc:
            try:
                os.write(2, f'exec failed: {exc}\n'.encode())
            except Exception:
                pass
        os._exit(127)
    return (pid, master_fd)

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

def run_pty_worker(*, jailed_argv: Sequence[str], work_dir: str, seed: str, deliverable: Optional[str]=None, cols: int=200, rows: int=50, startup_timeout: float=90.0, idle_timeout: float=1200.0, poll: float=1.0, settle_k: int=3, min_work: float=4.0, grace: float=25.0, spawn: Optional[Callable[..., Any]]=None, os_read: Optional[Callable[[int, int], bytes]]=None, os_write: Optional[Callable[[int, bytes], int]]=None, select_fn: Optional[Callable[..., Any]]=None, os_kill: Optional[Callable[[int, int], Any]]=None, os_waitpid: Optional[Callable[[int, int], Any]]=None, os_close: Optional[Callable[[int], Any]]=None, monotonic: Optional[Callable[[], float]]=None, sleep: Optional[Callable[[float], Any]]=None, exists: Optional[Callable[[str], bool]]=None, getsize: Optional[Callable[[str], int]]=None, set_geometry: Optional[Callable[[int, int, int], Any]]=None) -> TmuxWorkerResult:
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
        os_write(master_fd, seed.encode('utf-8'))
        sleep(0.5)
        os_write(master_fd, b'\r')
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
        return TmuxWorkerResult(started=started, idle=idle, snapshot=_strip(bytes(buf)) + f'\n<run_pty_worker error: {exc!r}>')
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
    return (model, tools)
'PTY-driven jailed-interactive-claude worker backend (REFERENCE).\n\nLive-debugged before pipeline transcription. This is the CORRECTED module to\nreplace the co-hallucinated ``harness/tmux_worker.py``.\n\nTransport note: despite the module/entrypoint name (kept for the orchestrator\nwiring contract at ``orchestrator.spawn_agent``), the worker drives claude over a\ndirect **pseudo-terminal** (``pty.fork``), NOT a tmux pane. A bwrap-jailed\nINTERACTIVE claude (billed to Max/OAuth, never the headless ``-p`` API) renders\nits TUI fine under a PTY but dies in a tmux pane; the PTY is the working transport.\n\nDesign:\n  * ``run_pty_worker`` is a pure orchestrator over injectable seams (``spawn``,\n    ``os_read``, ``os_write``, ``select_fn``, ``os_kill``, ``os_waitpid``,\n    ``monotonic``, ``sleep``, ``exists``, ``getsize``) so the leaf oracle exercises\n    the real start->ready->send->complete logic over fakes -- no real PTY/claude.\n  * ``spawn_claude_tmux`` is the thin real-wiring entrypoint: build the interactive\n    argv (overseer.tmux_seams.build_interactive_argv -- never ``-p``), seed a\n    per-task CLAUDE_CONFIG_DIR under the jailed work_dir, jail via\n    ``agent_jail.build_jail_argv``, then drive via ``run_pty_worker``.\n\nTermination is gated on the DELIVERABLE the orchestrator itself harvests\n(``outbox/submission.py`` going non-empty and stable) -- robust, because an\ninteractive claude keeps its turn "active" (composing prose, retrying MCP) long\nafter it has written the file. TUI idle (ready footer is the most-recent footer)\nis a secondary fallback signal.\n'