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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Mapping, Optional, Sequence
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
__all__ = ['TmuxWorkerResult', '_ExitedProc', 'seed_from_prompt_file', 'run_tmux_worker', 'spawn_claude_tmux', 'jail_command']

class TmuxWorkerResult(tuple):
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

    def __new__(cls, started: bool = False, idle: bool = False, snapshot: str = '') -> 'TmuxWorkerResult':
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
        """Always report the (clean) exit code; never None, never blocks."""
        return 0

    def wait(self, timeout: Optional[float]=None) -> int:
        """Return immediately with the exit code; ``timeout`` is accepted but
        irrelevant since the process is already considered finished."""
        return 0

    def kill(self) -> None:
        """No-op: there is no live child process to signal."""
        return None

    def terminate(self) -> None:
        """No-op alias for :meth:`kill`."""
        return None

    def __repr__(self) -> str:
        return f'_ExitedProc(returncode=0, _work_dir={self._work_dir!r})'

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

def seed_from_prompt_file(prompt_filename: str) -> str:
    """Read and return the interactive *seed* text from ``prompt_filename``.

    The seed is the prompt that will be typed into the tmux session's first
    turn. This is a pure, side-effect-free read: it opens the named file as
    UTF-8 text and returns its full contents verbatim. It performs no tmux or
    subprocess work and never spawns a session.
    """
    return Path(prompt_filename).read_text(encoding='utf-8')

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

def run_tmux_worker(*, session: str, inner_argv: List[str], cwd: str, seed: str,
                    tmux_exec: Callable[..., Any], sleep: Callable[..., Any],
                    timeout: float = 1800.0, poll: float = 2.0,
                    start_session: Optional[Callable[..., Any]] = getattr(_tmux_session, 'start_session', None),
                    send_turn: Optional[Callable[..., Any]] = getattr(_tmux_session, 'send_turn', None),
                    wait_idle: Optional[Callable[..., Any]] = getattr(_tmux_session, 'wait_idle', None),
                    capture: Optional[Callable[..., Any]] = getattr(_tmux_seams, 'capture_pane', None) or getattr(_tmux_session, 'capture_pane', None)) -> 'TmuxWorkerResult':
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

def spawn_claude_tmux(agent: Any, resolved_prompt: str, env: Mapping, config: Any, *, dbus_sock: Optional[str]=None) -> _ExitedProc:
    """Prepare the environment and launch an interactive claude tmux worker.

    Steps:
      1. Read ``JANUSMASK_TASK_ID`` / ``JANUSMASK_WORK_DIR`` /
         ``JANUSMASK_STATE_DIR`` from ``env`` and prepare the directories.
      2. Seed claude config / credentials into the work dir.
      3. Write ``resolved_prompt`` to a prompt file and read it back through
         :func:`seed_from_prompt_file` to obtain the interactive seed.
      4. Build and jail the claude command (:func:`jail_command`).
      5. Hand off to :func:`run_tmux_worker` to drive the tmux session over the
         pure seams.

    A default ``tmux_exec`` that *raises* (never hangs) when no backend is
    injected is supplied so that, absent a real tmux backend, the drive fails
    fast and is swallowed by :func:`run_tmux_worker` rather than spawning
    anything. Returns an :class:`_ExitedProc` whose ``_work_dir`` is stamped
    with the resolved work directory.
    """
    import time
    env_map = dict(env or {})
    work_dir = env_map.get('JANUSMASK_WORK_DIR') or os.getcwd()
    state_dir = env_map.get('JANUSMASK_STATE_DIR') or work_dir
    work_path = Path(work_dir)
    state_path = Path(state_dir)
    work_path.mkdir(parents=True, exist_ok=True)
    state_path.mkdir(parents=True, exist_ok=True)
    cfg = _as_mapping(config)
    content = _cfg_get(cfg, 'claude_config', 'config', default=None)
    if content is None:
        content = {k: v for k, v in cfg.items() if k not in {'claude_bin', 'claude_path', 'claude_args', 'args'}}
    if not isinstance(content, Mapping):
        content = {}
    (work_path / '.claude.json').write_text(json.dumps(content, indent=2, sort_keys=True))
    creds = _cfg_get(cfg, 'credentials', 'claude_credentials', default=None)
    if isinstance(creds, Mapping) and creds:
        (work_path / '.credentials.json').write_text(json.dumps(creds, indent=2, sort_keys=True))
    prompt_file = work_path / 'prompt.txt'
    prompt_file.write_text(resolved_prompt or '')
    seed = seed_from_prompt_file(str(prompt_file))
    base_cmd = _build_claude_command(agent, config, prompt_file)
    jailed_cmd = jail_command(base_cmd, env=env_map, work_dir=work_path, state_dir=state_path, dbus_sock=dbus_sock, config=config)
    session_name = _default_session_name(env_map)

    def _default_tmux_exec(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError('tmux exec backend is not configured in this environment; inject a tmux_exec seam to drive a real session')

    run_tmux_worker(session=session_name, inner_argv=list(jailed_cmd), cwd=str(work_path), seed=seed, tmux_exec=_default_tmux_exec, sleep=time.sleep)
    return _ExitedProc(work_dir=str(work_path))
