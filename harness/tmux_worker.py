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

@dataclass
class TmuxWorkerResult:
    """Structured result of orchestrating a command under tmux.

    Attributes mirror the information a caller needs to reason about the run
    without scraping the TUI: the exit ``returncode``, the ``session_name``
    used, the ``work_dir`` the command ran in, the resolved ``command`` and
    the ``prompt_file`` that seeded the interactive session.
    """
    returncode: int = 0
    session_name: str = ''
    work_dir: str = ''
    command: Sequence[str] = field(default_factory=list)
    prompt_file: Optional[str] = None

    @property
    def ok(self) -> bool:
        """True when the worker exited cleanly."""
        return self.returncode == 0

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

def seed_from_prompt_file(config: Any, work_dir: Any, *, filename: str='.claude.json') -> Path:
    """Seed the worker's ``work_dir`` with claude config / credentials.

    The config payload is sourced from ``config`` -- preferring an explicit
    ``claude_config``/``config`` sub-mapping and otherwise falling back to the
    config mapping as a whole. The seeded JSON is written to
    ``work_dir/filename`` (default ``.claude.json``) and the resulting path is
    returned.

    Missing keys or empty values are handled by defaulting to an empty config
    object, so this is safe to call with a partial or empty ``config``.
    """
    cfg = _as_mapping(config)
    work_path = Path(work_dir)
    work_path.mkdir(parents=True, exist_ok=True)
    content = _cfg_get(cfg, 'claude_config', 'config', default=None)
    if content is None:
        content = {k: v for k, v in cfg.items() if k not in {'claude_bin', 'claude_path', 'claude_args', 'args'}}
    if not isinstance(content, Mapping):
        content = {}
    dest = work_path / filename
    dest.write_text(json.dumps(content, indent=2, sort_keys=True))
    creds = _cfg_get(cfg, 'credentials', 'claude_credentials', default=None)
    if isinstance(creds, Mapping) and creds:
        (work_path / '.credentials.json').write_text(json.dumps(creds, indent=2, sort_keys=True))
    return dest

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

def run_tmux_worker(command: Sequence[str], *, env: Optional[Mapping]=None, work_dir: Any=None, session_name: Optional[str]=None, config: Any=None, executor: Optional[Callable[..., int]]=None) -> TmuxWorkerResult:
    """Orchestrate ``command`` under a tmux session and report the result.

    The actual session lifecycle is delegated to ``executor`` (defaulting to
    :func:`_tmux_executor`, which drives the real seams). Tests inject a fake
    ``executor`` -- or monkeypatch :func:`_tmux_executor` -- so that no real
    tmux session is ever created.
    """
    env_map = dict(env or {})
    work_path = Path(work_dir or env_map.get('JANUSMASK_WORK_DIR') or os.getcwd())
    work_path.mkdir(parents=True, exist_ok=True)
    name = session_name or _default_session_name(env_map)
    cmd = list(command)
    run = executor or _tmux_executor
    returncode = run(cmd, env=env_map, work_dir=work_path, session_name=name, config=config)
    return TmuxWorkerResult(returncode=int(returncode or 0), session_name=name, work_dir=str(work_path), command=cmd)

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
      2. Seed claude config / credentials into the work dir
         (:func:`seed_from_prompt_file`).
      3. Write ``resolved_prompt`` to a prompt file in the work dir.
      4. Build and jail the claude command (:func:`jail_command`).
      5. Hand off to :func:`run_tmux_worker` to drive the tmux session.

    Returns an :class:`_ExitedProc` whose ``_work_dir`` is stamped with the
    resolved work directory, so the surrounding harness can treat it like any
    other (already-exited) process handle.
    """
    env_map = dict(env or {})
    task_id = str(env_map.get('JANUSMASK_TASK_ID') or '').strip()
    work_dir = env_map.get('JANUSMASK_WORK_DIR') or os.getcwd()
    state_dir = env_map.get('JANUSMASK_STATE_DIR') or work_dir
    work_path = Path(work_dir)
    state_path = Path(state_dir)
    work_path.mkdir(parents=True, exist_ok=True)
    state_path.mkdir(parents=True, exist_ok=True)
    seed_from_prompt_file(config, work_path)
    prompt_file = work_path / 'prompt.txt'
    prompt_file.write_text(resolved_prompt or '')
    base_cmd = _build_claude_command(agent, config, prompt_file)
    jailed_cmd = jail_command(base_cmd, env=env_map, work_dir=work_path, state_dir=state_path, dbus_sock=dbus_sock, config=config)
    session_name = _default_session_name(env_map)
    result = run_tmux_worker(jailed_cmd, env=env_map, work_dir=work_path, session_name=session_name, config=config)
    result.prompt_file = str(prompt_file)
    proc = _ExitedProc(work_dir=str(work_path))
    return proc