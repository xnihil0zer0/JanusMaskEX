"""Main orchestrator loop for JanusMask dual-agent differential fuzzing."""
from __future__ import annotations
import argparse
import ast
import json
import logging
import os
import signal
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
from pathlib import Path
from typing import Any
from dataclasses import dataclass
import yaml
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from harness._journal import write_jsonl_row
from harness.ast_enforcer import validate_code
from harness.diff_fuzzer import fuzz_from_task
from harness.diff_fuzzer import FuzzResult
from harness.cross_examiner import prepare_exam_packets
from harness.cross_examiner import write_feedback_files
from harness.cross_examiner import clear_feedback_files
from harness.session_namer import generate_submission_filename
from harness.session_namer import generate_feedback_filename
from harness.depth_validator import check_true_depth
from harness.ast_retry import synthesize_with_retries
from harness.task_decomposer import decompose_task
from harness.task_decomposer import enqueue_subtasks
from harness.task_decomposer import update_parent_state
from harness.agent_streamer import start_stream_threads
from harness import git_integration
from harness.sandbox_smoke import smoke_import
from harness.embedded_test_runner import run_embedded_tests
from harness.narrow_fuzz import run_narrow_fuzz
from harness.paths import HARNESS_DIR
from harness.paths import PROJECT_ROOT as PROJECT_DIR
from harness.paths import CONFIG_DIR
from harness.paths import CONFIG_DIR_STR
from harness.paths import STATE_DIR as DEFAULT_STATE_DIR
from harness.paths import agent_work_dir
DEFAULT_CONFIG_PATH = HARNESS_DIR / 'config.yaml'
POLL_INTERVAL = 2
logger = logging.getLogger('janusmask.orchestrator')

def _emit_lifecycle(state_dir: Path, **fields) -> None:
    """Append a lifecycle row to state/impl_progress.jsonl. Swallows OSError per W113.

    META-D2a (manual implementation, dispatch-rejected): closes Agent-3 blind
    spots O1/O4/O5/O6/O8/O9/O12. Row schema extends the existing
    impl_progress.jsonl shape with an optional ``phase_transition`` field on
    phase rows. ``ts`` auto-stamped to time.time(); writes are best-effort and
    never propagate failures into the orchestrator's terminal state.
    """
    try:
        row = {'ts': time.time(), **fields}
        write_jsonl_row(state_dir / 'impl_progress.jsonl', row)
    except OSError as exc:
        logger.warning('lifecycle emit failed: %s', exc)

def _emit_pending(state_dir: Path, task_id: str, phase: str) -> None:
    """WUI-1b: emit a ``pending_approval`` lifecycle row the WebUI Approvals
    page (app.js) filters on. Best-effort; never raises."""
    _emit_lifecycle(state_dir, event='pending_approval', task_id=task_id, phase=phase, detail=phase)

def _emit_timeout(state_dir: Path, task_id: str, phase: str) -> None:
    """WUI-1b: emit an ``approval_timeout`` lifecycle row when await_decision
    deadlines out. Best-effort; never raises."""
    _emit_lifecycle(state_dir, event='approval_timeout', task_id=task_id, phase=phase, detail=phase)

def _configure_logging(log_dir: Path | None=None) -> None:
    """Set up logging to stderr and logs/harness.log."""
    log_dir = log_dir or PROJECT_DIR / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / 'harness.log'
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s', datefmt='%Y-%m-%dT%H:%M:%S')
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(formatter)
    root = logging.getLogger('janusmask')
    root.setLevel(logging.DEBUG)
    root.addHandler(stderr_handler)
    root.addHandler(file_handler)
from harness.state import init_state
from harness.state import locked_read_modify_write
from harness.state import read_state
from harness.state import set_agent_status
from harness.state import set_phase
from harness import control_gate

def _interpolate_config_paths(obj: Any) -> Any:
    """Recursively substitute ${CONFIG_DIR} / ${PROJECT_ROOT} / ${STATE_DIR}
    placeholders in string values with the host-specific absolute paths
    from ``harness.paths``. Keeps the YAML source portable across hosts
    and checkouts while preserving the downstream expectation that
    ``agents[agent]['args']`` contains absolute paths when spawning the
    Claude/Gemini CLIs."""
    if isinstance(obj, str):
        if '${CONFIG_DIR}' in obj:
            obj = obj.replace('${CONFIG_DIR}', CONFIG_DIR_STR)
        if '${PROJECT_ROOT}' in obj:
            obj = obj.replace('${PROJECT_ROOT}', str(PROJECT_DIR))
        if '${STATE_DIR}' in obj:
            obj = obj.replace('${STATE_DIR}', str(DEFAULT_STATE_DIR))
        return obj
    if isinstance(obj, dict):
        return {k: _interpolate_config_paths(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_interpolate_config_paths(x) for x in obj]
    return obj

def load_config(config_path: Path=DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Load harness configuration from YAML."""
    logger.info('Loading configuration from %s', config_path)
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    if not isinstance(config, dict):
        raise ValueError(f'Config root must be a YAML mapping, got {type(config)}')
    config = _interpolate_config_paths(config)
    if 'synthesis' in config and config['synthesis'].get('antigravity_mode', True):
        config.setdefault('control', {})['autobrief_default_agent'] = 'antigravity'
    return config

class _C:
    RESET = '\x1b[0m'
    BOLD = '\x1b[1m'
    DIM = '\x1b[2m'
    CLAUDE = '\x1b[38;5;33m'
    GEMINI = '\x1b[38;5;208m'
    OK = '\x1b[38;5;82m'
    WARN = '\x1b[38;5;220m'
    ERR = '\x1b[38;5;196m'
    INFO = '\x1b[38;5;245m'
    ORCH = '\x1b[38;5;141m'
import datetime

def _con(msg: str) -> None:
    """Write a formatted line to the operator console (stderr)."""
    ts = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    sys.stderr.write(f'{ts} {msg}\n')
    sys.stderr.flush()

def _agent_tag(agent: str) -> str:
    color = _C.CLAUDE if agent == 'claude' else _C.GEMINI
    task_id = os.environ.get('JANUSMASK_TASK_ID', '')
    prefix = f'[{task_id}] ' if task_id else ''
    return f'{color}{_C.BOLD}{prefix}{agent.upper()}{_C.RESET}'

def _orch_tag() -> str:
    task_id = os.environ.get('JANUSMASK_TASK_ID', '')
    prefix = f'[{task_id}] ' if task_id else ''
    return f'{_C.ORCH}{_C.BOLD}{prefix}ORCH{_C.RESET}'
_HOOK_CONFIG_REWIRE_SYNTHESIS = {str(CONFIG_DIR / 'claude_worker.json'): str(CONFIG_DIR / 'claude_worker_hooks.json')}
_HOOK_CONFIG_REWIRE_PLANNING = {str(CONFIG_DIR / 'claude_worker.json'): str(CONFIG_DIR / 'claude_worker_planning_hooks.json'), str(CONFIG_DIR / 'gemini_worker_policy.toml'): str(CONFIG_DIR / 'gemini_worker_policy_planning.toml')}

def _build_agent_command(agent: str, prompt: str, config: dict[str, Any]) -> list[str]:
    """Build the CLI command list for an agent from config.

    HOOK-41 table-rewrite: ``config.yaml`` still references the MCP-era
    worker configs (``claude_worker.json``, ``gemini_worker_policy.toml``)
    for parity-shadow runs; every orchestrator spawn rewires those paths
    here to the hook-declaring configs P2/P3 landed. Gemini's policy TOML
    is unchanged — its hooks register via ``config/gemini_settings.json``
    which HOOK-40 exports as ``JANUSMASK_GEMINI_SETTINGS``.
    """
    agent_cfg = config['agents'][agent]
    command = agent_cfg['command']
    raw_args: list[str] = list(agent_cfg['args'])
    mode = os.environ.get('JANUSMASK_MODE', 'synthesis')
    rewire = _HOOK_CONFIG_REWIRE_SYNTHESIS if mode == 'synthesis' else _HOOK_CONFIG_REWIRE_PLANNING
    raw_args = [rewire.get(a, a) for a in raw_args]
    if agent == 'claude' and '--permission-mode' not in raw_args:
        raw_args = raw_args + ['--permission-mode', 'acceptEdits']
    try:
        p_index = raw_args.index('-p')
        cmd = [command] + raw_args[:p_index + 1] + [prompt] + raw_args[p_index + 1:]
    except ValueError:
        cmd = [command] + raw_args + ['-p', prompt]
    return cmd

def _assert_claude_hook_config(cmd: list[str]) -> None:
    """CONTAIN C5: fail-closed if the effective claude --settings file does not
    declare a PreToolUse hook.

    The PreToolUse hook is the (audit-grade) submission-confinement layer; C2 (the
    bwrap jail) and C4 (--tools) are the load-bearing barriers, but a missing or
    malformed settings file is a misconfiguration we REFUSE to launch into rather
    than spawn an agent with no gate at all. Reads the effective (post-rewire)
    --settings path out of the built argv. Raises RuntimeError on any failure so the
    caller's spawn-exception handling turns it into a safe rejected/error outcome.
    """
    try:
        i = cmd.index('--settings')
        settings_path = Path(cmd[i + 1])
    except (ValueError, IndexError):
        raise RuntimeError('CONTAIN C5: claude spawn has no --settings argument; refusing to launch un-gated.')
    if not settings_path.is_file():
        raise RuntimeError(f'CONTAIN C5: claude --settings file not found: {settings_path}; refusing to launch.')
    try:
        data = json.loads(settings_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f'CONTAIN C5: claude --settings unreadable ({settings_path}): {exc}; refusing to launch.')
    if not (isinstance(data, dict) and data.get('hooks', {}).get('PreToolUse')):
        raise RuntimeError(f'CONTAIN C5: claude --settings {settings_path} declares no PreToolUse hook; refusing to launch un-gated.')

def _apply_agy_pool_env(agent, env, config=None):
    """Pool a private $HOME onto an agy agent's spawn env when the worker pool
    is enabled and this worker was assigned a slot (JANUSMASK_AGY_SLOT). Only
    agy-command agents are pooled; disabled / non-agy / absent or invalid slot
    returns env unchanged (never mutated). The overseer never reaches this path."""
    if config is None:
        config = load_config()
    try:
        cmd = config['agents'][agent]['command']
    except (KeyError, TypeError):
        return env
    if os.path.basename(cmd) != 'agy':
        return env
    pool = (config.get('workers') or {}).get('agy_pool') or {}
    if not pool.get('enabled'):
        return env
    try:
        slot = int(os.environ.get('JANUSMASK_AGY_SLOT'))
    except (TypeError, ValueError):
        return env
    from harness import agy_pool
    home = os.environ.get('HOME') or os.path.expanduser('~')  # home-free: allow
    try:
        agy_pool.ensure_seeded(str(PROJECT_DIR), slot, home=home, copy=shutil.copy2, exists=os.path.exists, makedirs=lambda d: os.makedirs(d, exist_ok=True))
    except OSError:
        pass
    return agy_pool.worker_env(str(PROJECT_DIR), slot, env)

def _build_agent_env(agent: str, state_dir: str, round_number: int=1) -> dict[str, str]:
    """Build the environment for an agent process.

    Every ``JANUSMASK_*`` key the worker-side hooks read is set explicitly
    so that an upstream caller that wipes one of these variables does not
    silently downgrade the worker to an un-gated fallback. See sub-plan 04
    §3.11 and the HOOK-30 authoritative-settings contract at
    ``harness/hooks/gemini/session_start.py:80-92``.

    Post-migration: we also pin ``JANUSMASK_WORK_DIR`` to a deterministic,
    per-spawn path so the Write-based submission flow has a stable outbox
    to target. The worker configs interpolate ``${SESSION_ID}`` by default
    but that id is only known at Claude CLI startup — by pre-setting
    ``JANUSMASK_WORK_DIR`` here we override the template and the outbox
    path is known to both the agent prompt and the PostToolUse hook at
    spawn time.

    Filesystem side-effects: env-building is pure — the outbox directory
    is created by ``spawn_agent`` at actual spawn time so callers can
    build env against arbitrary ``state_dir`` paths (e.g. tmp_path,
    non-existent, read-only) without tripping mkdir permission errors.
    """
    mode = os.environ.get('JANUSMASK_MODE', 'synthesis')
    task_id = os.environ.get('JANUSMASK_TASK_ID', '')
    import uuid as _uuid
    session_slug = f'{agent}-r{round_number}-{task_id or 'notask'}-{_uuid.uuid4().hex[:8]}'
    work_dir = agent_work_dir(agent, session_slug)
    _existing_pp = os.environ.get('PYTHONPATH', '')
    _pythonpath = str(PROJECT_DIR) if not _existing_pp else str(PROJECT_DIR) + os.pathsep + _existing_pp
    _ENV_ALLOW_EXACT = frozenset(('PATH', 'HOME', 'LANG', 'LANGUAGE', 'LC_ALL', 'TERM', 'SHELL', 'USER', 'LOGNAME', 'TZ', 'TMPDIR', 'PWD', 'DBUS_SESSION_BUS_ADDRESS', 'GOOGLE_GENAI_USE_GCA', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'NODE_EXTRA_CA_CERTS', 'CURL_CA_BUNDLE', 'NO_PROXY', 'no_proxy', 'HTTP_PROXY', 'http_proxy', 'HTTPS_PROXY', 'https_proxy'))
    _ENV_ALLOW_PREFIXES = ('JANUSMASK_', 'XDG_', 'NVM_', 'NODE_', 'GEMINI_', 'GOOGLE_', 'ANTHROPIC_', 'CLAUDE_', 'LC_')
    base_env = {k: v for k, v in os.environ.items() if k in _ENV_ALLOW_EXACT or any((k.startswith(p) for p in _ENV_ALLOW_PREFIXES))}
    env: dict[str, str] = {**base_env, 'PYTHONHASHSEED': '0', 'CLAUDE_PROJECT_DIR': str(work_dir), 'JANUSMASK_PROJECT_DIR': str(PROJECT_DIR), 'PYTHONPATH': _pythonpath, 'GEMINI_CLI_TRUST_WORKSPACE': 'true', 'JANUSMASK_AGENT': agent, 'JANUSMASK_STATE_DIR': state_dir, 'JANUSMASK_ROUND': str(round_number), 'JANUSMASK_MODE': mode, 'JANUSMASK_TASK_ID': task_id, 'JANUSMASK_WORK_DIR': str(work_dir)}
    if agent == 'gemini':
        env['JANUSMASK_GEMINI_SETTINGS'] = os.environ.get('JANUSMASK_GEMINI_SETTINGS', str(PROJECT_DIR / 'config' / 'gemini_settings.json'))
    env = _apply_agy_pool_env(agent, env)
    return env

def _boost_antigravity_mcp_config(state_dir: Path) -> None:
    home_dir = os.environ['HOME']  # home-free: allow
    mcp_path = Path(home_dir) / '.gemini' / 'antigravity-cli' / 'mcp_config.json'
    mcp_path.parent.mkdir(parents=True, exist_ok=True)
    py_exe = sys.executable
    server_script = Path(__file__).resolve().parent / 'mcp_server.py'
    config_entry = {'mcpServers': {'janusmask': {'command': py_exe, 'args': [str(server_script), 'antigravity', str(state_dir.resolve())]}}}
    tmp_path = mcp_path.with_suffix('.tmp')
    try:
        if mcp_path.exists():
            try:
                with open(mcp_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                data = {}
        else:
            data = {}
        data.setdefault('mcpServers', {})['janusmask'] = config_entry['mcpServers']['janusmask']
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write('\n')
        tmp_path.rename(mcp_path)
    except Exception as e:
        logger.error(f'Failed to boost antigravity MCP config: {e}')

def _external_jail_extra_ro(jail_repo_root):
    """Extra ro-bind paths for a synthesis jail whose repo_root is EXTERNAL.

    When the jail repo_root is not the JM PROJECT_DIR (an external-target build),
    also ro-bind PROJECT_DIR so the VENDORED claude binary
    (${PROJECT_ROOT}/.agents/claude-code/node_modules/.bin/claude) and the
    `python3 -m harness.hooks.*` entrypoints -- both under the JM repo -- resolve
    inside the jail. Returns [] for a self build (repo_root == PROJECT_DIR), where
    PROJECT_DIR is already ro-bound as repo_root. Never raises.
    """
    try:
        if Path(jail_repo_root).resolve() != PROJECT_DIR.resolve():
            return [str(PROJECT_DIR)]
    except Exception:
        pass
    return []

def spawn_agent(agent: str, prompt: str, config: dict[str, Any], round_number: int=1) -> subprocess.Popen:
    """Spawn an agent CLI as a managed subprocess with live output streaming.

    Returns the Popen handle. The caller is responsible for monitoring
    and killing the process (via kill_agent).

    Agent stdout/stderr are streamed in real time via daemon threads
    (see agent_streamer.py). stdout is parsed as NDJSON (stream-json
    format for both Claude and Gemini).

    GH1 (2026-05-18): between outbox creation and prompt resolution,
    ``_stage_inbox`` populates ``<work_dir>/inbox/<expected-name>`` so
    the Gemini SessionStart hook's inbox-ready gate stops denying every
    planning + reconciliation spawn. Exactly one new call site;
    public signature unchanged.

    TMUX-BACKEND (additive, flag-gated): when ``workers.claude_backend`` is
    ``tmux`` and ``agent`` is the claude worker, delegate the spawn to the tmux
    worker backend (``harness.tmux_worker.spawn_claude_tmux``). The import is
    LAZY (inside the gated branch) so the default ``headless`` path never
    imports ``tmux_worker`` and stays byte-for-byte unchanged. The delegated
    ``_ExitedProc`` honors the existing proc-handling contract
    (poll/returncode/wait/kill/_work_dir) and is returned to the caller as-is.
    """
    state_dir = config.get('state_dir', str(DEFAULT_STATE_DIR))
    if agent == 'antigravity':
        _boost_antigravity_mcp_config(Path(state_dir))
    env = _build_agent_env(agent, state_dir, round_number)
    outbox_path = Path(env['JANUSMASK_WORK_DIR']) / 'outbox'
    outbox_path.mkdir(parents=True, exist_ok=True)
    _stage_inbox(Path(env['JANUSMASK_WORK_DIR']), env['JANUSMASK_MODE'], state_dir)
    resolved_prompt = prompt.replace('{STATE_DIR}', str(state_dir)).replace('{OUTBOX_PATH}', str(outbox_path)).replace('{WORK_DIR}', str(Path(env['JANUSMASK_WORK_DIR'])))
    from harness.interceptors import registry as interceptor_registry
    try:
        interceptor_registry.pre_invocation(agent, resolved_prompt, env)
    except Exception as exc:
        logger.error('Error in pre_invocation interceptor: %s', exc, exc_info=True)
    cmd = _build_agent_command(agent, resolved_prompt, config)
    if agent == 'claude':
        _assert_claude_hook_config(cmd)
    from harness import agent_jail
    _dbus_stack = None
    _dbus_sock = None
    if agent_jail.sandbox_enabled(config):
        import contextlib
        _dbus_stack = contextlib.ExitStack()
        try:
            from harness.dbus_proxy import proxied_session_bus
            _dbus_sock = _dbus_stack.enter_context(proxied_session_bus())
        except Exception:
            import shutil
            if agent_jail.sandbox_enabled(config) and shutil.which('xdg-dbus-proxy') is not None:
                raise RuntimeError('agent_sandbox is enabled and xdg-dbus-proxy is present but the filtered D-Bus proxy failed to start; refusing to spawn an agent on the unfiltered host bus (fail-closed).')
            _dbus_sock = None
        working_dir = os.environ.get('JANUSMASK_WORKING_DIR')
        from harness.paths import _target_is_self, effective_target_root
        if not _target_is_self(working_dir):
            _jail_repo_root = effective_target_root(working_dir)
        else:
            _jail_repo_root = PROJECT_DIR
        cmd = agent_jail.build_jail_argv(cmd, repo_root=_jail_repo_root, work_dir=env['JANUSMASK_WORK_DIR'], state_dir=env['JANUSMASK_STATE_DIR'], dbus_proxy_socket=_dbus_sock, extra_ro=_external_jail_extra_ro(_jail_repo_root))
    if _use_tmux_claude(agent, config):
        import harness.tmux_worker
        return harness.tmux_worker.spawn_claude_tmux(agent, resolved_prompt, env, config, dbus_sock=_dbus_sock)
    _con(f'  {_orch_tag()} {_agent_tag(agent)} {_C.OK}spawning{_C.RESET} {_C.DIM}{cmd[0]}{_C.RESET}')
    logger.info('Spawning %s: %s', agent, ' '.join(cmd[:6]) + ' ...')
    _is_agy = os.path.basename(config['agents'][agent]['command']) in ('agy', 'codex')
    if _is_agy:
        try:
            agy_cmd = list(cmd)
            try:
                _p_index = agy_cmd.index('-p')
                del agy_cmd[_p_index:_p_index + 2]
            except ValueError:
                pass
            _no_write_tail = '\n\nDo NOT write, create, or edit any file. Do NOT use any file-editing or shell tool. Output ONLY the complete solution as a single fenced ```python code block — the full contents of the target file — no prose before or after.'
            stdin_prompt = resolved_prompt + _no_write_tail
            proc = subprocess.Popen(agy_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, start_new_session=True, cwd=str(Path(env['JANUSMASK_WORK_DIR'])))
            proc._work_dir = Path(env['JANUSMASK_WORK_DIR'])
            _timeout = config.get('synthesis', {}).get('timeout_seconds', 1200)
            try:
                out, _err = proc.communicate(input=stdin_prompt, timeout=_timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
                try:
                    proc.kill()
                except (ProcessLookupError, PermissionError, OSError):
                    pass
                try:
                    proc.wait(timeout=5)
                except (subprocess.TimeoutExpired, ProcessLookupError, PermissionError, OSError):
                    pass
                return proc
            from harness.test_author import _extract_python_block
            block = _extract_python_block(out)
            if block.strip() and block.strip() != '# Placeholder':
                sub_path = outbox_path / 'submission.py'
                try:
                    tmp = sub_path.with_suffix(sub_path.suffix + '.tmp')
                    tmp.write_text(block)
                    tmp.replace(sub_path)
                except OSError:
                    logger.warning('AGY-FIX: outbox submission write failed for %s', sub_path)
            return proc
        finally:
            if _dbus_stack is not None:
                _dbus_stack.close()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, start_new_session=True, cwd=str(Path(env['JANUSMASK_WORK_DIR'])))
    proc._dbus_stack = _dbus_stack
    proc._work_dir = Path(env['JANUSMASK_WORK_DIR'])
    _con(f'  {_orch_tag()} {_agent_tag(agent)} {_C.DIM}pid={proc.pid}{_C.RESET}')
    log_dir = Path(state_dir).parent / 'logs'
    proc._stream_threads = start_stream_threads(proc, agent, log_dir=log_dir)
    try:
        control_gate.record_agent_pid(state_dir, agent, proc.pid)
    except Exception:
        logger.debug('record_agent_pid failed (non-fatal)', exc_info=True)
    return proc

def kill_agent(proc: subprocess.Popen, agent: str, reason: str='handoff') -> None:
    """Kill an agent and its entire process group. Clears context."""
    if proc.poll() is not None:
        _con(f'  {_orch_tag()} {_agent_tag(agent)} {_C.DIM}already exited (code {proc.returncode}){_C.RESET}')
        _join_stream_threads(proc)
        _dbus_stack = getattr(proc, '_dbus_stack', None)
        if _dbus_stack is not None:
            try:
                _dbus_stack.close()
            except Exception:
                pass
            proc._dbus_stack = None
        return
    _con(f'  {_orch_tag()} {_agent_tag(agent)} {_C.WARN}killing ({reason}){_C.RESET}')
    logger.info('Killing %s agent pid=%d reason=%s', agent, proc.pid, reason)
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()
        try:
            proc.wait(timeout=3)
        except (subprocess.TimeoutExpired, ProcessLookupError, PermissionError, OSError):
            pass
    _join_stream_threads(proc)
    _con(f'  {_orch_tag()} {_agent_tag(agent)} {_C.DIM}terminated{_C.RESET}')
    _dbus_stack = getattr(proc, '_dbus_stack', None)
    if _dbus_stack is not None:
        try:
            _dbus_stack.close()
        except Exception:
            pass
        proc._dbus_stack = None

def _resolve_stateful_class_name(task, code_a):
    """Resolve the target CLASS name for stateful fuzzing from task
    constraints, falling back to the first class defined in ``code_a``.

    ``stateful_differential_fuzz`` keys on a class name (not the function name
    ``fuzz_from_task`` resolves), so this is a dedicated resolver (MD-ROUTING)."""
    import ast as _ast
    import re as _re
    constraints = {}
    if isinstance(task, dict):
        constraints = task.get('constraints') or {}
        if not isinstance(constraints, dict):
            constraints = {}
    for key in ('class_name', 'target_class', 'className'):
        val = constraints.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    sig = constraints.get('function_signature')
    if isinstance(sig, str):
        m = _re.search('class\\s+(\\w+)', sig)
        if m:
            return m.group(1)
    try:
        tree = _ast.parse(code_a)
        for node in tree.body:
            if isinstance(node, _ast.ClassDef):
                return node.name
    except Exception:
        pass
    return None

def _route_stateful_fuzz(task, code_a, code_b, config, session_id='default'):
    """MD-ROUTING seam: drive stateful differential fuzzing for a
    ``state_machine`` task. Returns a ``FuzzResult`` (equivalent True/False) or,
    when no class name can be resolved, a skipped-equivalent ``FuzzResult`` so
    callers can fall through safely. Never raises."""
    try:
        class_name = _resolve_stateful_class_name(task, code_a)
        if not class_name:
            return FuzzResult(equivalent=True, skipped_reason='stateful routing: no class name resolved')
        return stateful_differential_fuzz(code_a, code_b, class_name, config, session_id)
    except Exception as exc:
        return FuzzResult(equivalent=True, skipped_reason='stateful routing error: %s' % (exc,))

def stateful_differential_fuzz(code_a, code_b, class_name, config, session_id):
    """Drive end-to-end stateful differential fuzzing of two implementations.

    Generates symbolic action sequences for ``class_name`` (via the
    d_01/d_02/d_03 helpers ``extract_class_interface`` /
    ``build_stateful_strategy`` (from :mod:`harness.diff_fuzzer`) and
    ``execute_stateful_trace`` (defined in :mod:`harness.sandbox`)), replays
    each sequence against ``code_a`` and ``code_b`` in sandboxed instances, and
    looks for the first step whose A/B outputs disagree (return values *and*
    exceptions). On divergence the Hypothesis shrinking engine minimises the
    failing action sequence; the minimal counterexample is packaged into a
    ``FuzzFailure`` carried by the returned :class:`FuzzResult`.

    Strictly additive: it touches no existing orchestrator function and adds no
    module-level import (``FuzzResult`` is reused from the module-level import
    at the top of this file; everything else is imported lazily here). It never
    raises: a passing/skipped FuzzResult is returned when the class/interface
    cannot be parsed, when Hypothesis is unavailable, or when the example budget
    is exhausted without a divergence. A sandbox execution error on exactly one
    side (or differing exception types) is surfaced as a divergence rather than
    being silently treated as a match; nondeterminism/credential gates are left
    entirely to the existing diff_fuzzer helpers (not relaxed here).
    """
    import inspect as _inspect

    def _mk(cls, **kwargs):
        """Construct a (dataclass-ish) ``cls`` tolerant of unknown field sets."""
        if cls is None:
            return None
        try:
            params = _inspect.signature(cls).parameters
            accepted = {k: v for k, v in kwargs.items() if k in params}
            return cls(**accepted)
        except Exception:
            try:
                obj = cls.__new__(cls)
            except Exception:
                return None
            for k, v in kwargs.items():
                try:
                    setattr(obj, k, v)
                except Exception:
                    pass
            return obj

    def _result(equivalent, total, matching, failures, error=None, skipped=None):
        return _mk(FuzzResult, equivalent=equivalent, total_inputs=int(total), matching_inputs=int(matching), failures=list(failures or []), error=error, skipped_reason=skipped)
    try:
        from harness.diff_fuzzer import FuzzFailure as _FuzzFailure
    except Exception:
        _FuzzFailure = None
    try:
        from harness.diff_fuzzer import extract_class_interface as _extract_iface
        from harness.diff_fuzzer import build_stateful_strategy as _build_strategy
        from harness.sandbox import execute_stateful_trace as _exec_trace
        from harness.diff_fuzzer import outputs_match as _outputs_match
    except Exception as _imp_exc:
        return _result(True, 0, 0, [], skipped='stateful helpers unavailable: %s' % (_imp_exc,))
    try:
        from hypothesis import given, settings, assume, HealthCheck
    except Exception as _hyp_exc:
        return _result(True, 0, 0, [], skipped='hypothesis unavailable: %s' % (_hyp_exc,))

    def _call_adaptive(fn, *arg_shapes):
        last = None
        for shape in arg_shapes:
            try:
                return fn(*shape)
            except TypeError as te:
                last = te
                continue
        if last is not None:
            raise last
        return None
    try:
        interface = _call_adaptive(_extract_iface, (code_a, class_name), (code_a,))
    except Exception as exc:
        return _result(True, 0, 0, [], skipped='interface extraction failed: %s' % (exc,))
    if not interface:
        return _result(True, 0, 0, [], skipped='class %r not found / empty interface' % (class_name,))
    try:
        strategy = _call_adaptive(_build_strategy, (interface,), (interface, config))
    except Exception as exc:
        return _result(True, 0, 0, [], skipped='strategy build failed: %s' % (exc,))
    if strategy is None:
        return _result(True, 0, 0, [], skipped='no strategy for %r' % (class_name,))

    def _cfg_get(*keys):
        cur = config
        for k in keys:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                return None
        return cur
    max_examples = _cfg_get('fuzzing', 'stateful', 'max_examples') or _cfg_get('fuzzing', 'max_examples') or _cfg_get('synthesis', 'fuzz_max_examples') or 100
    try:
        max_examples = max(1, int(max_examples))
    except Exception:
        max_examples = 100

    def _split_seq(seq):
        if seq is None:
            return ((), [])
        if isinstance(seq, dict):
            ia = seq.get('init_args', seq.get('initargs', ()))
            mc = seq.get('method_calls', seq.get('calls', seq.get('steps', [])))
            return (ia or (), mc or [])
        ia = getattr(seq, 'init_args', None)
        mc = getattr(seq, 'method_calls', None)
        if ia is not None or mc is not None:
            return (ia or (), mc or [])
        if isinstance(seq, (tuple, list)) and len(seq) == 2 and isinstance(seq[1], (list, tuple)):
            return (seq[0], list(seq[1]))
        if isinstance(seq, (list, tuple)):
            return ((), list(seq))
        return ((), [])
    try:
        _exec_pnames = [p.name for p in _inspect.signature(_exec_trace).parameters.values() if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    except (TypeError, ValueError):
        _exec_pnames = []

    def _run_trace(code, seq):
        """Adaptively invoke execute_stateful_trace for one implementation."""
        init_args, method_calls = _split_seq(seq)
        if _exec_pnames:
            kw = {}
            for name in _exec_pnames:
                low = name.lower()
                if low in ('code', 'source', 'src', 'code_str', 'impl'):
                    kw[name] = code
                elif low in ('class_name', 'classname', 'cls_name', 'name'):
                    kw[name] = class_name
                elif low in ('action_sequence', 'actionsequence', 'actions', 'sequence', 'seq', 'trace'):
                    kw[name] = seq
                elif low in ('init_args', 'initargs', 'ctor_args', 'constructor_args'):
                    kw[name] = init_args
                elif low in ('method_calls', 'methodcalls', 'calls', 'steps'):
                    kw[name] = method_calls
                elif low in ('session_id', 'session', 'sessionid', 'sid'):
                    kw[name] = session_id
                elif low in ('config', 'cfg'):
                    kw[name] = config
                elif low in ('interface', 'iface'):
                    kw[name] = interface
            if kw:
                try:
                    return _exec_trace(**kw)
                except TypeError:
                    pass
        for args in ((code, class_name, seq, session_id), (code, class_name, seq), (code, class_name, init_args, method_calls, session_id), (code, class_name, init_args, method_calls)):
            try:
                return _exec_trace(*args)
            except TypeError:
                continue
        raise TypeError('could not adapt execute_stateful_trace call signature')

    def _compare(ta, tb):
        """Return (diverged, index, step_a, step_b) for two step traces.

        Compares JSON step-dicts as returned by ``execute_stateful_trace``
        (NOT ``ExecutionResult`` objects): per-step ``exception`` dict by type
        then message; otherwise the authoritative ``value_repr`` (``value`` is
        ``None`` for non-JSON returns such as set/bytes/Path); a ``skipped``
        step is equal iff both sides skipped. Differing step kinds (raise vs
        value vs skip) are a divergence. The non-deterministic default object
        repr ``<Cls object at 0x...>`` is normalised so two structurally
        identical instances are not flagged purely on memory address.
        """

        def _norm_repr(r):
            if not isinstance(r, str):
                return r
            marker = ' object at 0x'
            idx = r.find(marker)
            if idx != -1 and r.endswith('>'):
                return r[:idx + len(marker)] + '...>'
            return r

        def _step_kind(s):
            if not isinstance(s, dict):
                return 'value'
            if s.get('skipped'):
                return 'skip'
            if 'exception' in s and s.get('exception') is not None:
                return 'raise'
            return 'value'

        def _steps_equal(sa, sb):
            if not isinstance(sa, dict) or not isinstance(sb, dict):
                return sa == sb
            ka = _step_kind(sa)
            kb = _step_kind(sb)
            if ka != kb:
                return False
            if ka == 'skip':
                return True
            if ka == 'raise':
                ea = sa.get('exception') or {}
                eb = sb.get('exception') or {}
                if not isinstance(ea, dict) or not isinstance(eb, dict):
                    return ea == eb
                if ea.get('type') != eb.get('type'):
                    return False
                return ea.get('message') == eb.get('message')
            return _norm_repr(sa.get('value_repr')) == _norm_repr(sb.get('value_repr'))
        la = list(ta) if ta is not None else []
        lb = list(tb) if tb is not None else []
        n = min(len(la), len(lb))
        for i in range(n):
            try:
                same = _steps_equal(la[i], lb[i])
            except Exception:
                same = False
            if not same:
                return (True, i, la[i], lb[i])
        if len(la) != len(lb):
            sa = la[n] if n < len(la) else None
            sb = lb[n] if n < len(lb) else None
            return (True, n, sa, sb)
        return (False, -1, None, None)
    holder = {'found': False, 'index': None, 'reason': None, 'init_args': None, 'method_calls': None, 'out_a': None, 'out_b': None}
    counters = {'total': 0, 'matching': 0}

    @settings(max_examples=max_examples, deadline=None, suppress_health_check=list(HealthCheck))
    @given(strategy)
    def _check(seq):
        counters['total'] += 1
        err_a = err_b = None
        ta = tb = None
        try:
            ta = _run_trace(code_a, seq)
        except Exception as exc:
            err_a = exc
        try:
            tb = _run_trace(code_b, seq)
        except Exception as exc:
            err_b = exc
        if err_a is not None or err_b is not None:
            if err_a is not None and err_b is not None and (type(err_a) is type(err_b)):
                assume(False)
                return
            init_args, method_calls = _split_seq(seq)
            holder.update(found=True, index=0, reason='sandbox execution diverged (A=%r, B=%r)' % (err_a, err_b), init_args=init_args, method_calls=method_calls, out_a=('error', repr(err_a)) if err_a is not None else 'ok', out_b=('error', repr(err_b)) if err_b is not None else 'ok')
            raise AssertionError(holder['reason'])
        diverged, idx, step_a, step_b = _compare(ta, tb)
        if not diverged:
            counters['matching'] += 1
            return
        init_args, method_calls = _split_seq(seq)
        holder.update(found=True, index=idx, reason='stateful divergence at step %d' % idx, init_args=init_args, method_calls=method_calls, out_a=step_a, out_b=step_b)
        raise AssertionError(holder['reason'])
    fuzz_error = None
    try:
        _check()
    except AssertionError:
        pass
    except Exception as exc:
        fuzz_error = exc

    def _seq_summary(init_args, method_calls):
        try:
            calls = []
            for mc in method_calls or []:
                if isinstance(mc, (tuple, list)) and mc:
                    mname = mc[0]
                    margs = mc[1] if len(mc) > 1 else ()
                    calls.append('%s(%s)' % (mname, ', '.join((repr(a) for a in margs or ()))))
                elif isinstance(mc, dict):
                    mname = mc.get('method', mc.get('name', '?'))
                    margs = mc.get('args') or ()
                    calls.append('%s(%s)' % (mname, ', '.join((repr(a) for a in margs))))
                else:
                    calls.append(repr(mc))
            init_repr = ', '.join((repr(a) for a in init_args or ()))
            return '__init__(%s); %s' % (init_repr, ' -> '.join(calls))
        except Exception:
            return repr((init_args, method_calls))

    def _build_failure(h):
        reason = '%s | sequence: %s' % (h['reason'], _seq_summary(h['init_args'], h['method_calls']))
        ia = h['init_args']
        input_args = tuple(ia) if isinstance(ia, (list, tuple)) else (ia,)
        fail = _mk(_FuzzFailure, input_args=input_args, input_kwargs={}, reason=reason, result_a=h['out_a'], result_b=h['out_b'])
        if fail is None:
            return None
        for attr, val in (('init_args', h['init_args']), ('method_calls', h['method_calls']), ('action_sequence', (h['init_args'], h['method_calls'])), ('divergent_step_index', h['index']), ('first_divergent_step', h['index']), ('output_a', h['out_a']), ('output_b', h['out_b'])):
            try:
                setattr(fail, attr, val)
            except Exception:
                pass
        return fail
    if holder['found']:
        failure = _build_failure(holder)
        failures = [failure] if failure is not None else []
        return _result(False, counters['total'], counters['matching'], failures)
    if fuzz_error is not None:
        return _result(False, counters['total'], counters['matching'], [], error='stateful fuzz harness error: %s' % (fuzz_error,))
    return _result(True, counters['total'], counters['matching'], [])

def _join_stream_threads(proc: subprocess.Popen, timeout: float=2.0) -> None:
    """Join the stdout/stderr stream threads if they exist."""
    threads = getattr(proc, '_stream_threads', None)
    if threads:
        for t in threads:
            t.join(timeout=timeout)

def _path_b_outbox_fallback(work_dir: Path, sub_path: Path, task_id: str) -> str | None:
    work_dir = Path(work_dir)
    outbox_path = work_dir / 'outbox' / 'submission.py'
    if not outbox_path.is_file():
        return None
    try:
        content = outbox_path.read_text()
    except (OSError, UnicodeDecodeError):
        return None
    if not content.strip():
        return None
    target_is_py = True
    try:
        state_dir = sub_path.parent.parent
        task_file = state_dir / 'tasks' / f'current_task_{task_id}.json'
        if task_file.is_file():
            with open(task_file, 'r') as _f:
                _task = json.load(_f)
            _ft = _task.get('files_touched') or []
            if _ft and (not str(_ft[0]).endswith('.py')):
                target_is_py = False
    except (OSError, json.JSONDecodeError):
        pass
    if target_is_py:
        try:
            ast.parse(content)
        except SyntaxError:
            return None
    try:
        sub_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = sub_path.with_suffix(sub_path.suffix + '.tmp')
        tmp.write_text(json.dumps({'code': content, 'task_id': task_id}))
        tmp.replace(sub_path)
    except OSError:
        logger.warning('Path-B fallback: outbox promote write failed for %s', sub_path)
    return content
_MODE_OUTBOX_ARTIFACT: dict[str, str] = {'planning': 'plan_draft.json', 'reconciliation': 'reconciliation.json'}

def _poll_mode_artifact(work_dir: Path | None, mode: str) -> str | None:
    """Return the planning/reconciliation outbox artifact text, or None.

    A1: without this, ``poll_for_submission`` only recognizes the synthesis
    submission, so a planning/reconciliation agent that correctly wrote
    ``outbox/plan_draft.json`` / ``outbox/reconciliation.json`` is reported
    "died without submitting" -> ``run_both_agents`` fires the agy
    ``claude_fallback`` (Antigravity / Google credits) needlessly. The JSON
    artifact is NOT Python code and was already gate-validated on the agent's
    Write (hooks/claude/pre_tool.py), so it deliberately bypasses the
    ``submit_code`` interceptor (which would AST-deny JSON). The planner
    re-validates the draft via ``collect_agent_draft``; this return value is
    only used to keep the needless fallback from firing.
    """
    if work_dir is None:
        return None
    filename = _MODE_OUTBOX_ARTIFACT.get(mode)
    if not filename:
        return None
    artifact = Path(work_dir) / 'outbox' / filename
    if not artifact.is_file():
        return None
    try:
        text = artifact.read_text()
    except (OSError, UnicodeDecodeError):
        return None
    return text if text.strip() else None

def _submission_target_path(state_dir: Path, task_id: str) -> str | None:
    """Return the task's primary target file (``files_touched[0]``) so the
    submission interceptors can apply their non-``.py`` AST-validation exemption
    (interceptors.py: ``if path and not path.endswith('.py'): return None``).

    P-UNB3: without this, ``poll_for_submission`` calls the interceptor for
    ``submit_code`` with no ``path`` -> the non-``.py`` exemption is skipped ->
    a whole-file non-``.py`` submission (e.g. config.yaml) is ast-parsed as
    Python and wrongly denied (``SyntaxError`` L1). Mirrors the target-type
    resolution already in ``_path_b_outbox_fallback``. Returns ``None`` when the
    task/target cannot be resolved, in which case callers default to
    ``.py``-style AST validation (the strict/safe behavior).
    """
    try:
        task_file = state_dir / 'tasks' / f'current_task_{task_id}.json'
        if task_file.is_file():
            with open(task_file, 'r') as _f:
                _task = json.load(_f)
            _ft = _task.get('files_touched') or []
            if _ft:
                return str(_ft[0])
    except (OSError, json.JSONDecodeError):
        pass
    return None

def poll_for_submission(agent: str, state_dir: Path, round_number: int, proc: subprocess.Popen, timeout: int) -> str | None:
    """Poll for an agent's submission file. Returns the code or None.

    Watches for the submission file (name from session_namer.generate_submission_filename) while the agent
    process is alive. Returns as soon as the submission appears — the
    agent doesn't need to exit first.
    """
    sessions_dir = state_dir / 'sessions'
    task_id = os.environ.get('JANUSMASK_TASK_ID', 'default')
    filename = generate_submission_filename(agent, round_number, task_id)
    sub_path = sessions_dir / filename
    target_path = _submission_target_path(state_dir, task_id)
    work_dir = getattr(proc, '_work_dir', None)
    mode = os.environ.get('JANUSMASK_MODE', 'synthesis')
    deadline = time.monotonic() + timeout
    poll_start_wall = time.time()
    poll_interval = 0.5
    _con(f'  {_orch_tag()} {_agent_tag(agent)} {_C.INFO}waiting for submission...{_C.RESET}')
    while time.monotonic() < deadline:
        from harness.interceptors import registry as interceptor_registry
        if mode in _MODE_OUTBOX_ARTIFACT:
            artifact = _poll_mode_artifact(work_dir, mode)
            if artifact is not None:
                _con(f'  {_orch_tag()} {_agent_tag(agent)} {_C.OK}{mode} artifact received{_C.RESET} {_C.DIM}({len(artifact)} chars){_C.RESET}')
                return artifact
        if sub_path.is_file():
            try:
                with open(sub_path, 'r') as f:
                    data = json.load(f)
                code = data.get('code')
                if code and isinstance(code, str):
                    inter_res = interceptor_registry.pre_tool_use(agent, 'submit_code', {'code': code, 'path': target_path})
                    if inter_res and inter_res.get('decision') == 'deny':
                        _con(f'  {_orch_tag()} {_agent_tag(agent)} {_C.ERR}submission denied by interceptor: {inter_res.get('reason')}{_C.RESET}')
                        try:
                            sub_path.unlink()
                        except OSError:
                            pass
                        continue
                    interceptor_registry.post_tool_use(agent, 'submit_code', {'code': code, 'status': 'success'})
                    _con(f'  {_orch_tag()} {_agent_tag(agent)} {_C.OK}submission received{_C.RESET} {_C.DIM}({len(code)} chars){_C.RESET}')
                    return code
            except (json.JSONDecodeError, OSError):
                pass
        if work_dir is not None:
            code = _path_b_outbox_fallback(work_dir, sub_path, task_id)
            if code and isinstance(code, str):
                inter_res = interceptor_registry.pre_tool_use(agent, 'submit_code', {'code': code, 'path': target_path})
                if inter_res and inter_res.get('decision') == 'deny':
                    _con(f'  {_orch_tag()} {_agent_tag(agent)} {_C.ERR}fallback submission denied by interceptor: {inter_res.get('reason')}{_C.RESET}')
                    code = None
                else:
                    interceptor_registry.post_tool_use(agent, 'submit_code', {'code': code, 'status': 'success'})
                    _con(f'  {_orch_tag()} {_agent_tag(agent)} {_C.WARN}submission via outbox fallback{_C.RESET} {_C.DIM}({len(code)} chars){_C.RESET}')
                    return code
        if proc.poll() is not None:
            rc = proc.returncode
            for _attempt in range(3):
                if mode in _MODE_OUTBOX_ARTIFACT:
                    artifact = _poll_mode_artifact(work_dir, mode)
                    if artifact is not None:
                        _con(f'  {_orch_tag()} {_agent_tag(agent)} {_C.OK}exited (code {rc}); {mode} artifact found{_C.RESET}')
                        return artifact
                if sub_path.is_file():
                    try:
                        with open(sub_path, 'r') as f:
                            data = json.load(f)
                        code = data.get('code')
                        if code:
                            inter_res = interceptor_registry.pre_tool_use(agent, 'submit_code', {'code': code, 'path': target_path})
                            if inter_res and inter_res.get('decision') == 'deny':
                                _con(f'  {_orch_tag()} {_agent_tag(agent)} {_C.ERR}exited submission denied by interceptor: {inter_res.get('reason')}{_C.RESET}')
                                code = None
                            else:
                                interceptor_registry.post_tool_use(agent, 'submit_code', {'code': code, 'status': 'success'})
                                _con(f'  {_orch_tag()} {_agent_tag(agent)} {_C.WARN}exited (code {rc}) but submission found{_C.RESET}')
                                return code
                    except (json.JSONDecodeError, OSError):
                        pass
                if work_dir is not None:
                    code = _path_b_outbox_fallback(work_dir, sub_path, task_id)
                    if code and isinstance(code, str):
                        inter_res = interceptor_registry.pre_tool_use(agent, 'submit_code', {'code': code, 'path': target_path})
                        if inter_res and inter_res.get('decision') == 'deny':
                            _con(f'  {_orch_tag()} {_agent_tag(agent)} {_C.ERR}exited fallback submission denied by interceptor: {inter_res.get('reason')}{_C.RESET}')
                            code = None
                        else:
                            interceptor_registry.post_tool_use(agent, 'submit_code', {'code': code, 'status': 'success'})
                            _con(f'  {_orch_tag()} {_agent_tag(agent)} {_C.WARN}exited (code {rc}) but outbox fallback recovered submission{_C.RESET}')
                            return code
                time.sleep(0.2)
            _con(f'  {_orch_tag()} {_agent_tag(agent)} {_C.ERR}died without submitting (code {rc}){_C.RESET}')
            logger.error('%s agent died (rc=%d) without submitting', agent, rc)
            return None
        try:
            current_state = read_state(state_dir)
            agent_status = current_state.get(f'{agent}_status')
            updated_at = current_state.get('status_updated_at_epoch') or current_state.get('status_updated_at')
            if agent_status == 'running' and updated_at is not None and (updated_at >= poll_start_wall):
                if time.time() - updated_at > timeout:
                    set_agent_status(state_dir, agent=agent, status='timeout')
                    _emit_lifecycle(state_dir, event='agent_status', agent=agent, status='timeout', task_id=os.environ.get('JANUSMASK_TASK_ID'))
                    _con(f'  {_orch_tag()} {_agent_tag(agent)} {_C.ERR}watchdog timeout (>{timeout}s){_C.RESET}')
                    logger.error('%s agent watchdog timed out after %ds', agent, timeout)
                    return None
        except Exception as e:
            logger.debug('Watchdog error: %s', e)
        time.sleep(poll_interval)
    _con(f'  {_orch_tag()} {_agent_tag(agent)} {_C.ERR}timed out after {timeout}s{_C.RESET}')
    logger.error('%s agent timed out after %ds', agent, timeout)
    if read_state(state_dir).get(f'{agent}_status') == 'running':
        set_agent_status(state_dir, agent=agent, status='timeout')
        _emit_lifecycle(state_dir, event='agent_status', agent=agent, status='timeout', task_id=os.environ.get('JANUSMASK_TASK_ID'))
    return None

def run_agent_phase(agent: str, prompt: str, config: dict[str, Any], state_dir: Path, round_number: int, phase_name: str, max_retries: int=3) -> str | None:
    """Run one agent through one phase: spawn → poll → kill.

    This is the core handoff unit. Each call gives the agent a fresh
    process with only the prompt for this phase — no prior context.

    Returns the submitted code, or None if the agent failed/timed out.
    """
    timeout = config['synthesis']['timeout_seconds']
    _con(f'\n  {_orch_tag()} {_agent_tag(agent)} {_C.BOLD}phase: {phase_name}{_C.RESET}')
    for attempt in range(max_retries):
        if attempt > 0:
            _con(f'  {_orch_tag()} {_agent_tag(agent)} {_C.WARN}retry {attempt + 1}/{max_retries}{_C.RESET}')
            time.sleep(min(60, 2 ** attempt))
        proc = spawn_agent(agent, prompt, config, round_number)
        try:
            code = poll_for_submission(agent, state_dir, round_number, proc, timeout)
            if code is not None:
                return code
        finally:
            kill_agent(proc, agent, reason='phase complete' if code else 'no submission')
    return None

def run_both_agents(prompt_claude: str, prompt_gemini: str, config: dict[str, Any], state_dir: Path, round_number: int, phase_name: str) -> tuple[str | None, str | None]:
    """Run both agents through a phase.

    If antigravity_mode is enabled, runs them sequentially.
    Otherwise, runs them in parallel.
    """
    active_agents = config.get('synthesis', {}).get('active_agents', ['claude', 'gemini'])
    agent_a = active_agents[0]
    agent_b = active_agents[1] if len(active_agents) > 1 else active_agents[0]
    _con(f'\n{'─' * 60}')
    _con(f'  {_orch_tag()} {_C.BOLD}phase: {phase_name}{_C.RESET}')
    _con(f'{'─' * 60}')
    if config.get('synthesis', {}).get('antigravity_mode', True):
        _con(f'  {_orch_tag()} Running agents sequentially (Antigravity Mode)')
        code_a = run_agent_phase(agent_a, prompt_claude, config, state_dir, round_number, phase_name)
        if 'claude' == agent_a and code_a is None:
            _con(f'  {_orch_tag()} {_C.WARN}Claude failed or returned None. Running fallback: claude_fallback{_C.RESET}')
            try:
                code_a = run_agent_phase('claude_fallback', prompt_claude, config, state_dir, round_number, phase_name)
            except Exception:
                logger.exception('Error in claude_fallback agent phase')
                code_a = None
        code_b = run_agent_phase(agent_b, prompt_gemini, config, state_dir, round_number, phase_name)
        if 'claude' == agent_b and code_b is None:
            _con(f'  {_orch_tag()} {_C.WARN}Claude failed or returned None (slot b). Running fallback: claude_fallback{_C.RESET}')
            try:
                code_b = run_agent_phase('claude_fallback', prompt_gemini, config, state_dir, round_number, phase_name)
            except Exception:
                logger.exception('Error in claude_fallback agent phase')
                code_b = None
        return (code_a, code_b)
    with ThreadPoolExecutor(max_workers=2) as executor:
        claude_future = executor.submit(run_agent_phase, agent_a, prompt_claude, config, state_dir, round_number, phase_name)
        gemini_future = executor.submit(run_agent_phase, agent_b, prompt_gemini, config, state_dir, round_number, phase_name)
        timeout = config['synthesis']['timeout_seconds'] + 30
        results: dict[str, str | None] = {agent_a: None, agent_b: None}
        futures_map = {claude_future: agent_a, gemini_future: agent_b}
        for future in as_completed(futures_map, timeout=timeout):
            agent_name = futures_map[future]
            try:
                results[agent_name] = future.result()
            except Exception:
                logger.exception('Error in %s agent phase', agent_name)
                results[agent_name] = None
    if 'claude' == agent_a and results[agent_a] is None:
        _con(f'  {_orch_tag()} {_C.WARN}Claude failed or returned None (parallel). Running fallback: claude_fallback{_C.RESET}')
        try:
            results[agent_a] = run_agent_phase('claude_fallback', prompt_claude, config, state_dir, round_number, phase_name)
        except Exception:
            logger.exception('Error in claude_fallback agent phase')
            results[agent_a] = None
    if 'claude' == agent_b and results[agent_b] is None:
        _con(f'  {_orch_tag()} {_C.WARN}Claude failed or returned None (parallel, slot b). Running fallback: claude_fallback{_C.RESET}')
        try:
            results[agent_b] = run_agent_phase('claude_fallback', prompt_gemini, config, state_dir, round_number, phase_name)
        except Exception:
            logger.exception('Error in claude_fallback agent phase')
            results[agent_b] = None
    _con(f'  {_orch_tag()} {agent_a}={('submitted' if results[agent_a] else 'NONE')}  {agent_b}={('submitted' if results[agent_b] else 'NONE')}')
    return (results[agent_a], results[agent_b])

def await_both(claude_future: Any, gemini_future: Any, timeout: int) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Wait for both agent futures (legacy interface for tests)."""
    results: dict[str, dict[str, Any] | None] = {'claude': None, 'gemini': None}
    futures_map = {claude_future: 'claude', gemini_future: 'gemini'}
    for future in as_completed(futures_map, timeout=timeout):
        agent_name = futures_map[future]
        try:
            completed = future.result()
            try:
                parsed = json.loads(completed.stdout)
            except (json.JSONDecodeError, TypeError, AttributeError):
                if isinstance(completed, str):
                    parsed = {'code': completed}
                else:
                    parsed = {'raw': str(completed)}
            results[agent_name] = parsed
        except subprocess.TimeoutExpired:
            results[agent_name] = None
        except Exception:
            logger.exception('Error collecting result from %s', agent_name)
            results[agent_name] = None
    return (results['claude'], results['gemini'])

def scan_blocked_rollbacks(blocked_dir: Path) -> list[dict[str, Any]]:
    """Scan ``blocked_dir`` for ROLLBACK-*.md stubs and return task dicts.

    Each returned dict carries ``meta_task_type: harness_plumbing`` and the
    frontmatter fields (trigger, timestamp, previous_mode) preserved from
    the stub so the planner can surface the failed task for human review.

    Implements the planner-side half of sub-plan 06 §3 item 3 (M19): the
    rollback path writes ROLLBACK-<ts>.md via emit_rollback_blocked_report;
    this scanner is the intake seam that folds those stubs into the task
    queue as harness_plumbing work.
    """
    blocked_path = Path(blocked_dir)
    if not blocked_path.is_dir():
        return []
    tasks: list[dict[str, Any]] = []
    for md in sorted(blocked_path.glob('ROLLBACK-*.md')):
        try:
            text = md.read_text(encoding='utf-8')
        except OSError:
            continue
        lines = text.splitlines()
        if not lines or lines[0].strip() != '---':
            continue
        try:
            end_idx = lines.index('---', 1)
        except ValueError:
            continue
        frontmatter: dict[str, str] = {}
        for fm_line in lines[1:end_idx]:
            if ':' in fm_line:
                key, _, value = fm_line.partition(':')
                frontmatter[key.strip()] = value.strip()
        if frontmatter.get('meta_task_type') != 'harness_plumbing':
            continue
        task: dict[str, Any] = {'task_id': md.stem, 'meta_task_type': 'harness_plumbing', 'source': 'rollback_blocked_report', 'source_path': str(md), 'specification': 'Human review required: a rollback signal fired and hooks.mode was flipped to off. Investigate the trigger captured in the frontmatter and the stub body before re-enabling the canary.'}
        for key in ('trigger', 'timestamp', 'previous_mode'):
            if key in frontmatter:
                task[key] = frontmatter[key]
        tasks.append(task)
    return tasks

def _reemit_blocked_rollbacks(state_dir: Path) -> None:
    """Materialise ROLLBACK-*.md stubs as JSON tasks in ``state_dir/tasks/``.

    Idempotent: a stub whose JSON sibling already exists in tasks/ or
    tasks/processed/ is skipped. Sub-plan 06 §3 item 3 (M19) re-emission
    seam — invoked from get_next_task so blocked rollbacks surface on the
    next planner poll without requiring a separate cron/sweeper.
    """
    blocked_dir = state_dir / 'tasks' / 'blocked'
    if not blocked_dir.is_dir():
        return
    tasks_dir = state_dir / 'tasks'
    processed_dir = tasks_dir / 'processed'
    for task in scan_blocked_rollbacks(blocked_dir):
        task_id = task['task_id']
        target = tasks_dir / f'{task_id}.json'
        if target.exists():
            continue
        if (processed_dir / f'{task_id}.json').exists():
            continue
        try:
            target.write_text(json.dumps(task, indent=2), encoding='utf-8')
            logger.info('Re-emitted blocked rollback %s as harness_plumbing task', task_id)
        except OSError as e:
            logger.warning('Failed to re-emit blocked rollback %s: %s', task_id, e)

def _clear_stale_submissions(state_dir: Path, task_id: str) -> None:
    """Unlink session submission files left from a prior dispatch of ``task_id``.

    Without this, ``poll_for_submission`` accepts cached submissions on
    re-dispatch and skips agent synthesis (W85b ledger note). Invoked at
    single-task ``orchestrator_worker`` startup before synthesis so a
    re-dispatched task_id never reuses a previous run's submission.
    """
    sessions_dir = state_dir / 'sessions'
    if not sessions_dir.is_dir():
        return
    for stale in sessions_dir.glob(f'*_{task_id}_submission.json'):
        try:
            stale.unlink()
            logger.debug('Cleared stale submission %s', stale.name)
        except OSError:
            pass

def get_next_task(state_dir: Path) -> dict[str, Any] | None:
    """Read the next task from state_dir/tasks/.

    Tasks are JSON files.  The oldest unprocessed one (by filename sort)
    is selected, atomically claimed (via rename), and copied to
    ``state_dir/tasks/current_task.json``.

    Tasks whose true lineage depth (via parent_task chain, see
    harness.depth_validator) exceeds the validator's max are moved straight
    to ``processed/`` and skipped -- this breaks the decomposer recomposition
    loop pathology (P0.1; see hooks-implementation-sub-plan-05.md).

    Before selecting a task, any ROLLBACK-*.md stubs in
    ``state_dir/tasks/blocked/`` are re-emitted as JSON tasks carrying
    ``meta_task_type: harness_plumbing`` (sub-plan 06 §3 item 3 / M19) so
    a human reviewer can pick them up through the normal planner queue.

    G19b: the G19 multi-file dispatch rejection block has been removed.
    With G19a-1 (agent emits ``__JANUSMASK_MANIFEST__``) and G19a-2
    (commit_accepted_output consumes ``state/output/<task_id>.files.json``)
    landed, multi-file tasks now claim normally. The soft sanity check for
    a missing sidecar lives in ``_auto_commit_accepted`` rather than the
    claim path -- a missing sidecar is treated as an agent regression and
    falls back to a singular commit instead of rejecting the task at queue
    time.
    """
    tasks_dir = state_dir / 'tasks'
    if not tasks_dir.is_dir():
        logger.debug('No tasks directory at %s', tasks_dir)
        return None
    processed_dir = tasks_dir / 'processed'
    processed_dir.mkdir(parents=True, exist_ok=True)
    _reemit_blocked_rollbacks(state_dir)
    processed_names = {p.name for p in processed_dir.iterdir()}
    accepted_names = set()
    try:
        with open(state_dir / 'impl_progress.jsonl', 'r') as _lf:
            for _line in _lf:
                try:
                    row = json.loads(_line)
                    if row.get('phase') == 'accepted' and row.get('event') == 'auto_commit':
                        accepted_names.add(f'{row['task_id']}.json')
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass
    except OSError:
        pass
    candidates = sorted((p for p in tasks_dir.glob('*.json') if not p.name.startswith('current_task') and p.name not in processed_names))
    if not candidates:
        logger.debug('No unprocessed tasks found in %s', tasks_dir)
        return None
    chosen = None
    for candidate in candidates:
        try:
            with open(candidate, 'r') as _f:
                task_data = json.load(_f)
        except (json.JSONDecodeError, OSError):
            continue
        deps = task_data.get('dependencies', task_data.get('depends_on', []))
        if deps:
            unmet = [d for d in deps if f'{d}.json' not in accepted_names]
            if unmet:
                terminal = _terminally_failed_task_ids(state_dir)
                failed_deps = [d for d in unmet if d in terminal]
                if failed_deps:
                    logger.warning('Task %s depends on terminally-failed %s; routing to blocked/ (dependency_failed)', candidate.stem, failed_deps)
                    _mark_dependency_failed(state_dir, candidate.stem, failed_deps)
                    processed_names.add(candidate.name)
                    continue
                logger.debug('Skipping %s: unmet dependencies %s', candidate.name, unmet)
                continue
        candidate_task_id = candidate.stem
        if not check_true_depth(candidate_task_id, tasks_dir):
            dest = processed_dir / candidate.name
            try:
                candidate.rename(dest)
                processed_names.add(candidate.name)
                logger.warning('Task %s exceeded max lineage depth (or invalid chain); moved to processed/ unrun', candidate_task_id)
            except FileNotFoundError:
                pass
            continue
        processing_path = candidate.with_suffix('.json.processing')
        try:
            candidate.rename(processing_path)
            chosen = processing_path
            _emit_lifecycle(state_dir, event='task_claim', task_id=candidate_task_id)
            _clear_stale_submissions(state_dir, candidate_task_id)
            break
        except FileNotFoundError:
            continue
    if chosen is None:
        logger.debug('No ready tasks (all have unmet dependencies or were claimed)')
        return None
    orig_name = chosen.name.replace('.json.processing', '.json')
    logger.info('Next task: %s', orig_name)
    try:
        with open(chosen, 'r') as f:
            task = json.load(f)
    except json.JSONDecodeError as e:
        logger.error('JSONDecodeError reading %s: %s. Quarantining.', chosen, e)
        corrupted_dir = tasks_dir / 'corrupted'
        try:
            corrupted_dir.mkdir(parents=True, exist_ok=True)
            chosen.rename(corrupted_dir / chosen.name)
        except OSError as oe:
            logger.error('Failed to quarantine %s: %s', chosen, oe)
        return None
    task_id = task.get('task_id', orig_name.replace('.json', ''))
    current_task_path = tasks_dir / f'current_task_{task_id}.json'
    try:
        current_task_path.write_text(json.dumps(task, indent=2))
    except OSError as e:
        logger.warning('Failed to write current_task_%s.json: %s', task_id, e)
    return task

def _requires_verbatim_manifest(files_touched) -> bool:
    """Return True when *files_touched* must use the verbatim whole-file
    ``__JANUSMASK_MANIFEST__`` dispatch instead of the Python-only
    ``__JANUSMASK_PATCHES__`` symbol-patch dispatch.

    The symbol-patch path applies one ``.py`` file at a time via
    ``ast.parse`` (``git_integration._apply_symbol_patch``), so it cannot
    handle a multi-file bundle or a non-Python target. Those leaves must be
    routed to the verbatim whole-file apply (the manifest path).

    Returns False when *files_touched* is not a non-empty list (the
    single-py / no-op case preserves the symbol-patch path), otherwise True
    when the leaf touches more than one file OR any target does not end with
    ``.py``. A single ``.py`` target returns False.
    """
    if not isinstance(files_touched, list) or not files_touched:
        return False
    return len(files_touched) > 1 or any((not str(f).endswith('.py') for f in files_touched))

def prepare_task_prompt(task: dict[str, Any]) -> str:
    """Format a task dict into the prompt string sent to agents.

    Post-migration flow: agent reads the task spec from the on-disk
    current_task.json and submits code by writing ``submission.py`` under
    its own outbox dir. The PostToolUse (Claude) / AfterTool (Gemini) hook
    intercepts the Write and routes it to ``rpc_submit_code.persist``,
    which lands the submission at ``state/sessions/<filename>`` where the
    orchestrator's ``poll_for_submission`` picks it up. The ``{STATE_DIR}``
    and ``{OUTBOX_PATH}`` placeholders are substituted per-agent inside
    ``spawn_agent`` once we know which session work-dir the agent owns.

    The prompt intentionally does NOT reveal the existence of a second agent
    or that differential fuzzing will be applied.

    G19a-1 (2026-05-18): when ``task['files_touched']`` is a list of length
    > 1, append a multi-file instruction block that asks the agent to emit a
    single top-level ``__JANUSMASK_MANIFEST__`` dict literal mapping each
    relative path to its whole-file source. The block is appended AFTER the
    base prompt body and BEFORE the optional spec_summary tail. Single-file
    dispatches (len <= 1, empty list, missing key, or non-list value) emit
    the pre-G19a-1 prompt unchanged.

    G19a-3 (2026-05-18): the manifest block now spells out a VERBATIM
    file-content rule, includes a concrete docstring-bearing example, and
    enumerates common error modes under a DO NOT section. Closes the
    Gemini-strips-module-docstring failure observed on G16 round 1.

    G19a-4 (2026-05-18): Recommends raw-triple-single-quote wrapping
    for manifest values so embedded backslash escape sequences survive
    verbatim.
    """
    tsq = "'" * 3
    task_id = task.get('task_id', 'unknown')
    spec_summary = task.get('specification', task.get('description', ''))
    prompt = f'You are a code synthesis agent. Your goal is to write correct, clean Python code that satisfies the given specification.\n\nFollow these steps exactly:\n\n1. Read the task specification from: {{WORK_DIR}}/inbox/task.json\n   Pay attention to the spec, acceptance_criteria, and test_spec fields.\n   The current on-disk contents of any file you must edit are staged read-only under {{WORK_DIR}}/inbox/targets/<relative-path>.\n\n2. Write Python code that satisfies ALL requirements. The code must be self-contained and importable -- define functions as specified, include type hints, and handle edge cases.\n\n3. Submit your final code by writing a single Python file at:\n   {{OUTBOX_PATH}}/submission.py\n   Writing this file IS how you submit; do not invoke any other submission mechanism. The harness intercepts the write via a PostToolUse/AfterTool hook and persists the submission for the orchestrator to pick up.\n\nImportant:\n- Only file read/write operations are available; the MCP janusmask execute tool is NOT registered in this worker session.\n- Make sure your code is syntactically valid Python.\n\nTask reference: {task_id}\n'
    files_touched = task.get('files_touched') or []
    mtt = task.get('meta_task_type') or task.get('constraints', {}).get('meta_task_type')
    use_manifest = _requires_verbatim_manifest(files_touched)
    _pe_candidates = files_touched if isinstance(files_touched, list) else [files_touched]
    from harness.paths import effective_target_root
    _target_root = effective_target_root(task.get('working_dir'))
    _targets_exist = bool(_pe_candidates) and all((isinstance(p, str) and (_target_root / p).exists() for p in _pe_candidates))
    if (task.get('partial_edit') or mtt in BYPASS_FUZZER_TYPES) and (not use_manifest) and _targets_exist:
        pe_files = files_touched if isinstance(files_touched, list) else [files_touched]
        pe_repr = ', '.join((repr(p) for p in pe_files)) if pe_files else '<see current_task.json>'
        prompt += '\nPARTIAL-EDIT DISPATCH (__JANUSMASK_PATCHES__) for ' + pe_repr + f":\n\nThis task edits one or more LARGE existing files IN PLACE. DO NOT\nreproduce the whole file. Read each target's CURRENT on-disk content\n(read-only) from {{WORK_DIR}}/inbox/targets/<rel> -- do not look for the\nfiles by repo-relative path. Emit a single top-level Python list assigned\nto ``__JANUSMASK_PATCHES__`` whose elements each replace exactly ONE\nnamed block. Two entry kinds:\n\n  # replace a top-level def/async def/class (or dotted Outer.method):\n  {{'file': '<rel/path>', 'kind': 'symbol', 'name': '<qualified.Name>',\n   'code': r{tsq}<full replacement def/class source>{tsq}}}\n\n  # replace only the lines between a pair of sentinel comments:\n  {{'file': '<rel/path>', 'kind': 'region', 'marker': '<SENTINEL>',\n   'code': r{tsq}<replacement region body>{tsq}}}\n\nThe exact shape:\n\n    __JANUSMASK_PATCHES__ = [\n        {{'file': '...', 'kind': 'symbol', 'name': '...', 'code': r{tsq}...{tsq}}},\n    ]\n\nRules:\n- Use raw triple-quoted strings (r{tsq}...{tsq}) for ``code`` so newlines,\n  quotes, and backslash escape sequences survive verbatim.\n- For kind 'symbol', ``code`` MUST be exactly ONE def/async def/class\n  whose name matches the leaf of ``name``; every byte outside that block\n  is preserved by the harness.\n- For kind 'region', the file must already contain the sentinel pair\n  ``# JANUSMASK_REGION:<SENTINEL>`` ... ``# JANUSMASK_ENDREGION:<SENTINEL>``;\n  only the lines strictly between them are replaced (sentinels kept).\n- The submission file MUST contain ONLY this ``__JANUSMASK_PATCHES__``\n  assignment at top level (no other statements, imports, or decorators).\n- Replace ONLY the named symbols/regions you must change. Never emit a\n  whole-file manifest for a partial edit.\n\nADDING A NEW TOP-LEVEL SYMBOL (R-ANCHOR):\n- A 'symbol' patch can ONLY replace a top-level def/async def/class that\n  must already exist in the file; naming a symbol that does not yet exist\n  fails the patch-apply path with KeyError. To ADD brand-new top-level\n  symbol(s), use the R-ANCHOR additive pattern: pick an EXISTING top-level\n  symbol as the anchor and emit ONE 'symbol' entry whose ``name`` is that\n  anchor and whose ``code`` reproduces the anchor VERBATIM plus the new\n  symbol(s) as extras. The harness inserts the extras immediately before\n  the anchor and preserves the rest of the file.\n- Worked example -- add brand-new functions foo and bar by anchoring them\n  on the existing top-level symbol baz:\n\n    __JANUSMASK_PATCHES__ = [\n        {{'file': '<rel/path>', 'kind': 'symbol', 'name': 'baz',\n         'code': r{tsq}def foo() -> int:\n    return 1\n\ndef bar() -> int:\n    return 2\n\ndef baz() -> int:  # existing anchor, reproduced verbatim\n    return 3\n{tsq}}},\n    ]\n"
    elif use_manifest:
        files_repr = ', '.join((repr(p) for p in files_touched))
        prompt += f'''\nMULTI-FILE DISPATCH ({len(files_touched)} files: {files_repr}):\n\nThis task touches more than one file. The CURRENT on-disk content of each\nexisting target is staged read-only at {{WORK_DIR}}/inbox/targets/<rel>;\nread it there rather than by repo-relative path. Instead of writing\nsingle-file source, emit a single top-level Python dict literal assigned to\n``__JANUSMASK_MANIFEST__`` that maps each rel-path above to that file's\nfull source as a string. The exact shape:\n\n    __JANUSMASK_MANIFEST__ = {{\n        '<rel/path/to/file>': r{tsq}<file source here>{tsq},\n        '<rel/path/to/other>': r{tsq}<file source here>{tsq},\n    }}\n\nVERBATIM file content rule:\n- Each value MUST be the VERBATIM file content as it currently appears on\n  disk -- not a paraphrase, not a summary, not a fragment.\n- {tsq} (triple-single-quote) and """ (triple-double-quote) are DIFFERENT\n  Python string-delimiter tokens; they do NOT conflict with each other.\n  When you wrap the file content in r{tsq}...{tsq}, any """ inside the file\n  (e.g. the module docstring markers at the top of the file) MUST be\n  preserved byte-for-byte. Do not strip, rewrite, or convert them.\n\nRaw-string wrapping rule:\n- The recommended wrapping is r{tsq}...{tsq} (raw triple-single-quote). The r\n  prefix makes the string LITERAL, so backslash escape sequences inside\n  the file content (e.g. \\n, \\t, \\\\, \\x41, \\u0041, and regex literals\n  such as r'\\d+\\.\\d+') survive verbatim instead of being re-interpreted\n  by the Python lexer when the orchestrator parses the manifest. Using a\n  non-raw {tsq} would silently convert each \\n in the file content into a\n  real newline and reject \\d / \\. as invalid escape sequences, corrupting\n  the round-tripped source.\n\nConcrete example (a short file beginning with a Module docstring and a\nregex literal whose pattern contains backslash escape sequences):\n\n    __JANUSMASK_MANIFEST__ = {{\n        'pkg/example.py': r{tsq}"""Module docstring."""\\nimport re\\n\\nVERSION_RE = re.compile(r'\\d+\\.\\d+')\\n\\ndef f() -> int:\\n    return 1\\n{tsq},\n    }}\n\nNote how the inner """Module docstring.""" markers AND the backslash\nescape sequences inside the regex literal r'\\d+\\.\\d+' appear INSIDE the\nraw triple-single-quote manifest value, completely unchanged from the\nsource file -- the outer r{tsq} raw-string prefix keeps every backslash\nbyte-for-byte, so the orchestrator parses the manifest into the exact\nbytes that are on disk.\n\nDO NOT (common error modes that will fail validation):\n- DO NOT strip or rewrite the file's existing triple-double-quote (""")\n  docstring markers. They are part of the file's content and must round-trip\n  verbatim inside the raw triple-single-quote manifest value.\n- DO NOT wrap a file that contains backslash escape sequences in a non-raw\n  {tsq} value (i.e. plain triple-single-quote without the leading r prefix).\n  Without the r prefix, Python's string lexer interprets every backslash at\n  parse time -- \\n collapses to a real newline, \\d raises an invalid escape\n  sequence warning / error, and the manifest source itself can become\n  unparseable. Use r{tsq}...{tsq} instead so the backslashes survive.\n- DO NOT add an f-string prefix f{tsq}, concatenate multiple string fragments\n  with ``+``, manually escape inner quotes with backslashes, or truncate the\n  file with ellipses (``...``) instead of including the whole source.\n- If the file's source itself contains a literal triple-single-quote ({tsq})\n  sequence at module scope, fall back to r"""...""" (raw triple-double-quote)\n  for that one entry so the outer delimiter does not clash with the inner\n  {tsq} tokens.\n\nRequirements:\n- Provide WHOLE-FILE source for every entry (no diffs, no fragments).\n- Use raw triple-quoted strings (r{tsq}...{tsq} or r"""...""") for values so\n  embedded newlines, quotes, and backslash escape sequences survive\n  verbatim.\n- The submission file MUST contain only this assignment at top level\n  (no other top-level statements, no imports, no decorators).\n- Include every path listed above as a manifest key, using the exact\n  relative paths shown.\n'''
    if mtt == 'test_authoring':
        prompt += '\nTEST-AUTHORING DISPATCH:\n\nYou are authoring a pytest TEST FILE (a verification oracle), NOT an implementation function. Write the COMPLETE contents of the test file as ordinary Python source to the submission.py path given above -- a whole .py file. DO NOT emit a __JANUSMASK_PATCHES__ list and DO NOT emit a __JANUSMASK_MANIFEST__ dict; submit the test file source directly.\n\nThe test MUST import the module(s) under test by name and exercise their REAL observable behaviour per the spec. It MUST be NON-VACUOUS: the harness re-runs it against a deliberately broken mutant of the code and REJECTS it unless it FAILS on the mutant -- so a test that asserts trivially (e.g. assert True) or never exercises the behaviour will be rejected. Follow EVERY required test property and safety constraint in the spec / acceptance_criteria (fixtures, monkeypatch + teardown, redirected paths, skip markers, negative and positive controls) exactly, and name each test function test_<unit>_<behaviour>.\n'
    if spec_summary:
        prompt += f'\nBrief overview (full details in current_task.json):\n{spec_summary}\n'
    repair_feedback = task.get('repair_feedback')
    if isinstance(repair_feedback, str) and repair_feedback:
        prompt += '\n\nPRIOR ATTEMPT FAILED VERIFICATION. Do NOT repeat the same mistake; fix exactly this:\n' + repair_feedback + '\n'
    return prompt

def collect_submissions(state_dir: Path, round_number: int) -> tuple[str | None, str | None]:
    """Read the code submissions written by the MCP server.

    The MCP server writes JSON files named by session_namer.generate_submission_filename
    containing a "code" field.  Returns (claude_code, gemini_code) or None for
    a missing submission.
    """
    sessions_dir = state_dir / 'sessions'
    claude_code: str | None = None
    gemini_code: str | None = None
    task_id = os.environ.get('JANUSMASK_TASK_ID', 'default')
    for agent in ('claude', 'gemini'):
        path = sessions_dir / generate_submission_filename(agent, round_number, task_id)
        if path.is_file():
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                code = data.get('code', '')
                if code.strip():
                    if agent == 'claude':
                        claude_code = code
                    else:
                        gemini_code = code
                    logger.info('Collected %s submission (%d bytes)', agent, len(code))
                else:
                    logger.warning('Empty code in submission from %s', agent)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.error('Corrupt submission file from %s: %s', agent, exc)
        else:
            logger.warning('No submission file for %s at %s', agent, path)
    return (claude_code, gemini_code)

def _load_declared_signature(task: dict[str, Any]) -> str | None:
    """Return the brief-declared function signature for *task*, or ``None``.

    W76b: the brief's ``function_signature`` (when present) carries the
    contract-level ``-> T`` return-type promise that ``validate_return_type``
    needs to detect Future-vs-dict-style regressions. The signature lives in
    ``task["constraints"]["function_signature"]`` per the established schema
    (live_test.py, send-task.sh, tests/test_configuration.py:182). Tasks
    without a constraint dict, or with no ``function_signature`` field, return
    ``None`` -- in which case validate_code's wire-in is a no-op.

    Contract: returns either a non-empty signature string (caller passes it
    to validate_code's ``declared_signature`` kwarg) or ``None`` (skip).
    Empty strings are coerced to None so downstream callers only need a
    truthiness check.
    """
    constraints = task.get('constraints') or {}
    sig = constraints.get('function_signature')
    if not sig or not str(sig).strip():
        return None
    return str(sig)

def _validate_submission(code: str, agent: str, task: dict[str, Any]) -> tuple[bool, list]:
    """Run AST validation on a submission.  Returns (valid, violations).

    W76b: when the task carries a brief ``function_signature``, the
    return-type contract check is wired into ``validate_code`` so a
    mismatched ``-> T`` annotation surfaces as a ``return_type_mismatch``
    violation (severity=error) and rejects the submission. This closes the
    silent-canary gap documented in brief_hooks_silent_canary_signals row 3.

    META-WEBUI-AUTOBRIEF-V2 (2026-05-15): when files_touched[0] is not a
    .py file, skip AST validation entirely. The submission is then the
    literal target-file content (markdown / YAML / JS / etc.); attempting
    ``ast.parse()`` on it yields a spurious ``syntax`` violation that
    rejects every non-Python deliverable.

    G2 (2026-05-17): mirrors U2's hook-layer carve-out -- any
    ``meta_task_type`` beginning with ``test_`` gets ``allow_nondet =
    True``. Closes the gap where Claude's valid uuid4()-using F5c
    submissions were rejected by this standalone validator even though
    the hook-layer decider at ``_decide_common.py`` already permitted
    them.

    G19a-1 (2026-05-18): if ``_parse_manifest(code)`` recognises the
    submission as a ``__JANUSMASK_MANIFEST__`` dict, iterate its entries
    and per-entry-validate every ``.py`` rel-path's source via
    ``validate_code`` with the same ``allow_nondet`` / ``declared_signature``
    resolution. Non-py entries skip per-entry AST per the F3 contract.
    Aggregate all violations into a single list; reject (False) iff any
    violation has ``severity == 'error'``. Manifest detection precedes the
    files_touched-first-non-py short-circuit so a multi-file dispatch whose
    ``files_touched[0]`` happens to be a non-py file still validates its
    .py entries instead of returning (True, []) prematurely.

    G12-principled (2026-05-18): replaces the G12v2 mtt-allowlist band-aid
    with per-target baseline diffing. Both the manifest branch (per rel-path)
    and the singular branch (against ``files_touched[0]``) compute
    ``_compute_target_baseline_violations(rel, declared_signature)`` and
    filter the submission's own violations by (rule, message) membership.
    The mtt allowlist + constraints.deterministic + test_* carve-outs are
    retained as defense-in-depth -- especially the test_* path, whose new
    code legitimately introduces brand-new nondeterminism.

    G28 (2026-05-19): close the silent-acceptance class where a
    single-file submission on a multi-file task (manifest is None AND
    len(files_touched) > 1) passed validation and then hit
    multi_file_missing_sidecar at commit time, committing only
    files_touched[0] before V2 rollback fired. Now: emit a
    manifest_missing error violation between the manifest-present branch
    and the single-file fallback so the AST-retry loop forces the agent
    to resubmit as a __JANUSMASK_MANIFEST__ dict.

    VALIDATOR_SIG (2026-06-01): the task's return-typed
    ``declared_signature`` names exactly one function, so in a partial-edit
    ``__JANUSMASK_PATCHES__`` submission it must only gate the patch entry
    whose replaced symbol shares that name. Previously every ``.py`` patch
    block was validated against ``declared_signature``, so a non-matching
    symbol (e.g. ``bar`` when the signature describes ``foo``) was rejected
    with a spurious ``return_type_mismatch``. We now extract the signature's
    function name via ``_extract_func_name_from_signature`` (lazy import) and
    pass ``declared_signature`` only to the matching ``kind == 'symbol'``
    entry; all other entries (including non-symbol region patches, which
    carry no name) receive ``None`` and are never return-type-checked.

    DEDENT_NORMALIZE: each ``__JANUSMASK_PATCHES__`` entry's ``code`` block
    is run through ``textwrap.dedent`` before ``validate_code``. A column-0
    top-level def/class is left byte-identical (no common leading
    whitespace), while an indented class-method body (the symbol code copied
    verbatim with its class-level indentation) is normalized to column 0 so
    it parses cleanly instead of failing with ``SyntaxError: unexpected
    indent``. This mirrors the dedent at the apply site
    (git_integration._apply_symbol_patch).

    G2_RELAX (REV22 §4-3, CR-1/CR-2/CR-3): external targets relax
    eval/exec/__import__ at commit-time too -- threaded into all three
    ``validate_code`` calls (manifest, partial-edit, single-file).
    RELAX_PREDICATE: the shared ``relax_external_for`` predicate decides this,
    additionally requiring every resolved target to land OUTSIDE PROJECT_ROOT
    so a non-self working_dir cannot relax validation for an inside-repo
    write. Fail-safe to self: absent/None working_dir => relax False, so
    self/default stays fully strict. Credentials/os_system/bare_except/
    nondeterminism stay strict for all targets.
    """
    import textwrap
    mtt = task.get('meta_task_type') or task.get('constraints', {}).get('meta_task_type')
    allow_nondet = task.get('constraints', {}).get('deterministic') is False
    if not allow_nondet:
        if mtt in {'io_adapter', 'logging_observability', 'harness_plumbing', 'harness_self_fix', 'orchestration', 'planner_tooling', 'hooks_integration', 'validation', 'sandbox_infra', 'mcp_plumbing', 'mcp_server_change'}:
            allow_nondet = True
        elif isinstance(mtt, str) and mtt.startswith('test_'):
            allow_nondet = True
    declared_signature = _load_declared_signature(task)
    from harness.paths import relax_external_for
    relax_external = relax_external_for(task, content=code)
    manifest = _parse_manifest(code)
    if manifest is not None:
        _ft_raw = task.get('files_touched')
        _declared = [str(f) for f in _ft_raw] if isinstance(_ft_raw, list) else []
        def _norm_manifest_path(p):
            n = os.path.normpath(str(p)).replace('\\', '/')
            return n[2:] if n.startswith('./') else n
        _manifest_norm = {_norm_manifest_path(k) for k in manifest}
        _missing = [f for f in _declared if _norm_manifest_path(f) not in _manifest_norm]
        if (not manifest) or _missing:
            _need = _missing or _declared or ['<none declared>']
            msg = ('__JANUSMASK_MANIFEST__ is empty or missing declared files '
                   f'{_need}: every files_touched entry must appear as a manifest '
                   'key mapped to its full source. Resubmit a complete manifest.')
            logger.warning('%s manifest submission empty/incomplete (declared=%r, manifest_keys=%r)', agent, _declared, list(manifest.keys()))
            return (False, [Violation(rule='manifest_incomplete', severity='error', line=0, message=msg)])
        all_violations: list = []
        for rel, src in manifest.items():
            if not rel.endswith('.py'):
                logger.info('%s manifest entry %s: skipping AST validation (non-py target)', agent, rel)
                continue
            entry_violations = validate_code(src, allow_nondeterminism=allow_nondet, declared_signature=declared_signature, relax_external_constructs=relax_external)
            baseline = _compute_target_baseline_violations(rel, declared_signature)
            filtered = [v for v in entry_violations if (v.rule, v.message) not in baseline]
            suppressed_count = len(entry_violations) - len(filtered)
            if suppressed_count:
                logger.info('%s manifest entry %s: suppressed %d pre-existing violations (target baseline)', agent, rel, suppressed_count)
            all_violations.extend(filtered)
        errors = [v for v in all_violations if v.severity == 'error']
        if errors:
            logger.warning('%s manifest submission (%d files) has %d AST errors: %s', agent, len(manifest), len(errors), '; '.join((f'{v.rule}@L{v.line}: {v.message}' for v in errors[:5])))
            return (False, all_violations)
        logger.info('%s manifest submission (%d files) passed AST validation (%d warnings)', agent, len(manifest), len(all_violations))
        return (True, all_violations)
    if task.get('partial_edit') or mtt in BYPASS_FUZZER_TYPES:
        patches = git_integration._parse_patches(code)
        if patches is not None:
            from harness.ast_enforcer import _extract_func_name_from_signature
            sig_func = _extract_func_name_from_signature(declared_signature) if declared_signature else None
            pv: list = []
            for entry in patches:
                if not isinstance(entry, dict):
                    continue
                if not str(entry.get('file', '')).endswith('.py'):
                    continue
                blk = entry.get('code', '')
                blk = textwrap.dedent(blk)
                entry_name = entry.get('name') if entry.get('kind') == 'symbol' else None
                blk_sig = declared_signature if sig_func is not None and entry_name == sig_func else None
                pv.extend(validate_code(blk, allow_nondeterminism=allow_nondet, declared_signature=blk_sig, relax_external_constructs=relax_external))
            errors = [v for v in pv if v.severity == 'error']
            if errors:
                logger.warning('%s partial-edit submission (%d patches) has %d AST errors: %s', agent, len(patches), len(errors), '; '.join((f'{v.rule}@L{v.line}: {v.message}' for v in errors[:5])))
                return (False, pv)
            logger.info('%s partial-edit submission (%d patches) passed AST validation (%d warnings)', agent, len(patches), len(pv))
            return (True, pv)
        if task.get('partial_edit'):
            msg = 'partial_edit task requires a top-level __JANUSMASK_PATCHES__ = [ {file, kind, name|marker, code}, ... ] assignment, but the submission contained no parseable __JANUSMASK_PATCHES__ block. Resubmit as a __JANUSMASK_PATCHES__ list (one entry per replaced symbol/region) so the patch encoding is deterministic.'
            logger.warning('%s partial_edit submission missing __JANUSMASK_PATCHES__ block (task_id=%r)', agent, task.get('task_id'))
            return (False, [Violation(rule='patches_required', severity='error', line=0, message=msg)])
    files_touched_raw = task.get('files_touched')
    if isinstance(files_touched_raw, list) and len(files_touched_raw) > 1:
        file_list_str = ', '.join((str(f) for f in files_touched_raw))
        msg = f'multi-file task declares files_touched of length {len(files_touched_raw)} ([{file_list_str}]) but the submission contains no __JANUSMASK_MANIFEST__ block. Wrap every file in a __JANUSMASK_MANIFEST__ = {{rel_path: source_code, ...}} dict at module top-level so all {len(files_touched_raw)} files commit atomically.'
        logger.warning('%s submission missing __JANUSMASK_MANIFEST__ on multi-file task (files_touched=%r)', agent, files_touched_raw)
        return (False, [Violation(rule='manifest_missing', severity='error', line=0, message=msg)])
    files_touched = files_touched_raw or []
    if files_touched:
        target = str(files_touched[0])
        if not target.endswith('.py'):
            logger.info('%s submission for non-py target %s: skipping AST validation', agent, target)
            return (True, [])
    violations = validate_code(code, allow_nondeterminism=allow_nondet, declared_signature=declared_signature, relax_external_constructs=relax_external)
    if files_touched:
        baseline = _compute_target_baseline_violations(str(files_touched[0]), declared_signature)
        filtered = [v for v in violations if (v.rule, v.message) not in baseline]
        suppressed_count = len(violations) - len(filtered)
        if suppressed_count:
            logger.info('%s submission: suppressed %d pre-existing violations (target baseline %s)', agent, suppressed_count, files_touched[0])
        violations = filtered
    errors = [v for v in violations if v.severity == 'error']
    if errors:
        logger.warning('%s submission has %d AST errors: %s', agent, len(errors), '; '.join((f'{v.rule}@L{v.line}: {v.message}' for v in errors[:5])))
        return (False, violations)
    logger.info('%s submission passed AST validation (%d warnings)', agent, len(violations))
    return (True, violations)

def _persist_fuzz_results(state_dir: Path, task_id: str, round_label: str, result: FuzzResult) -> None:
    """Write fuzz results to logs/fuzz_results/ for auditing.

    Atomic write (W112): mirror _save_final_output / state._write_state_to_disk
    so a mid-write crash leaves the prior file intact rather than a truncated
    JSON that downstream auditing tools would fail on.
    """
    fuzz_dir = state_dir.parent / 'logs' / 'fuzz_results'
    fuzz_dir.mkdir(parents=True, exist_ok=True)
    summary = {'task_id': task_id, 'round': round_label, 'equivalent': result.equivalent, 'total_inputs': result.total_inputs, 'matching_inputs': result.matching_inputs, 'failure_count': len(result.failures), 'error': result.error, 'skipped_reason': result.skipped_reason, 'failures': [{'args': repr(f.input_args)[:200], 'reason': f.reason} for f in result.failures[:20]]}
    path = fuzz_dir / f'{task_id}_{round_label}.json'
    tmp_path = path.with_suffix('.json.tmp')
    with open(tmp_path, 'w') as f:
        json.dump(summary, f, indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    tmp_path.replace(path)

def _save_final_output(state_dir: Path, task_id: str, code: str) -> None:
    """Save the final accepted code to the permanent output directory.

    G19a-1 (2026-05-18): the legacy ``state/output/<task_id>.py`` write is
    unchanged (atomic ``.py.tmp`` -> ``.py`` rename, fsync inside the
    open-context). When ``_parse_manifest(code)`` recognises the code as a
    ``__JANUSMASK_MANIFEST__`` multi-file submission, also emit a sidecar
    JSON file at ``state/output/<task_id>.files.json`` (atomic
    ``.json.tmp`` -> ``.json`` rename, fsync inside the open-context)
    containing ``json.dump(manifest, fh, indent=2, sort_keys=True)`` plus a
    trailing newline. ``commit_accepted_output`` (G19a-2) will read this
    sidecar to stage every rel-path; for now the orchestrator's
    ``_auto_commit_accepted`` still picks ``files_touched[0]``.
    """
    output_dir = state_dir / 'output'
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f'{task_id}.py'
    tmp_path = out_path.with_suffix('.py.tmp')
    with open(tmp_path, 'w') as f:
        f.write(code)
        f.flush()
        os.fsync(f.fileno())
    tmp_path.replace(out_path)
    logger.info('Saved final output to %s', out_path)
    manifest = _parse_manifest(code)
    if manifest is not None:
        sidecar_path = output_dir / f'{task_id}.files.json'
        sidecar_tmp = sidecar_path.with_suffix('.json.tmp')
        with open(sidecar_tmp, 'w') as f:
            json.dump(manifest, f, indent=2, sort_keys=True)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        sidecar_tmp.replace(sidecar_path)
        logger.info('Saved manifest sidecar to %s (%d files)', sidecar_path, len(manifest))
    else:
        patches = git_integration._parse_patches(code)
        if patches is not None:
            patches_sidecar = output_dir / f'{task_id}.patches.json'
            patches_tmp = patches_sidecar.with_suffix('.json.tmp')
            with open(patches_tmp, 'w') as f:
                json.dump(patches, f, indent=2, sort_keys=True)
                f.write('\n')
                f.flush()
                os.fsync(f.fileno())
            patches_tmp.replace(patches_sidecar)
            logger.info('Saved patches sidecar to %s (%d entries)', patches_sidecar, len(patches))

def _mark_processed(state_dir: Path, task_id: str) -> None:
    """Move the task file to processed/ and clean up current_task.json."""
    tasks_dir = state_dir / 'tasks'
    processed_dir = tasks_dir / 'processed'
    processed_dir.mkdir(parents=True, exist_ok=True)
    processing_files = list(tasks_dir.glob(f'*{task_id}.json.processing'))
    original_files = list(tasks_dir.glob(f'*{task_id}.json'))
    if processing_files:
        dest = processed_dir / f'{task_id}.json'
        try:
            shutil.move(str(processing_files[0]), str(dest))
        except OSError as e:
            logger.critical('CRITICAL: Failed to move processing file %s for task %s: %s', processing_files[0], task_id, e)
            return
        logger.info('Moved task %s to processed/', task_id)
    elif original_files:
        dest = processed_dir / f'{task_id}.json'
        try:
            shutil.move(str(original_files[0]), str(dest))
        except OSError as e:
            logger.critical('CRITICAL: Failed to move original file %s for task %s: %s', original_files[0], task_id, e)
            return
        logger.info('Moved task %s to processed/', task_id)
    current_task_path = tasks_dir / f'current_task_{task_id}.json'
    if current_task_path.exists():
        try:
            current_task_path.unlink()
        except OSError as e:
            logger.warning('Failed to remove current_task_%s.json: %s', task_id, e)

def _last_failure_tail(state_dir: Path, task_id: str) -> str:
    """Return a compact tail of the LAST captured failure for *task_id*.

    Reads the same ``state_dir/impl_progress.jsonl`` ledger that
    ``_auto_commit_accepted`` appends verification / mutation failure rows to,
    scans every row, and keeps the LAST one whose ``task_id`` matches AND whose
    ``event`` is one of the recognised failure events
    {verification_failed, mutation_gate_failed, mutation_gate_error,
    mutation_gate_missing}. From that row it assembles a compact,
    human-readable string out of ``stdout_tail`` / ``stderr_tail`` (plus
    ``event`` and ``reason`` / ``exit`` when present), truncated to the last
    ~2000 chars so a re-dispatched worker can see exactly why the prior attempt
    failed instead of reproducing the same mistake.

    Pure and fail-soft: returns '' when the file is missing, unreadable, or no
    matching failure row exists, and never raises (OSError/ValueError caught).
    """
    failure_events = {'verification_failed', 'mutation_gate_failed', 'mutation_gate_error', 'mutation_gate_missing'}
    path = state_dir / 'impl_progress.jsonl'
    last_row = None
    try:
        if not path.exists():
            return ''
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get('task_id') == task_id and (row.get('event') in failure_events):
                    last_row = row
    except (OSError, ValueError):
        return ''
    if not isinstance(last_row, dict):
        return ''
    parts: list[str] = []
    event = last_row.get('event')
    if event:
        parts.append(f'event={event}')
    exit_code = last_row.get('exit')
    if exit_code is not None:
        parts.append(f'exit={exit_code}')
    reason = last_row.get('reason')
    if reason:
        parts.append(f'reason={reason}')
    stdout_tail = last_row.get('stdout_tail')
    if stdout_tail:
        parts.append('stdout_tail:\n' + str(stdout_tail))
    stderr_tail = last_row.get('stderr_tail')
    if stderr_tail:
        parts.append('stderr_tail:\n' + str(stderr_tail))
    if not parts:
        return ''
    return '\n'.join(parts)[-2000:]
def _write_retry_sidecar(blocked_dir: Path, task_id: str, outcome: str) -> int:
    """Bump the {attempts,last_outcome,ts} retry sidecar for a blocked task.

    Read-modify-write preserves the running attempt count across re-blocks so
    the autowork daemon's retry budget (G-BLOCKED) stays monotonic. Returns the
    new attempt count.
    """
    sidecar = blocked_dir / f'{task_id}.retry.json'
    attempts = 0
    if sidecar.exists():
        try:
            prev = json.loads(sidecar.read_text(encoding='utf-8'))
            if isinstance(prev, dict) and isinstance(prev.get('attempts'), int):
                attempts = prev['attempts']
        except (OSError, ValueError):
            attempts = 0
    attempts += 1
    try:
        sidecar.write_text(json.dumps({'attempts': attempts, 'last_outcome': outcome, 'ts': time.time()}, sort_keys=True), encoding='utf-8')
    except OSError as e:
        logger.warning('Failed to write retry sidecar for %s: %s', task_id, e)
    return attempts

def _mark_blocked(state_dir: Path, task_id: str, outcome: str='rejected') -> None:
    """Route a NON-ACCEPT terminal to blocked/ (NOT processed/) + retry sidecar.

    G-ZOMBIE-RT: parking a non-accepting task in processed/ made it a permanent
    "zombie" (compute_brief_status counts processed/ as staged, so the autowork
    daemon never re-stages it). Routing to blocked/ with a
    {attempts,last_outcome,ts} sidecar lets the daemon re-stage it under a retry
    budget (G-BLOCKED) and emits a task_blocked ledger row for observability.
    """
    tasks_dir = state_dir / 'tasks'
    blocked_dir = tasks_dir / 'blocked'
    blocked_dir.mkdir(parents=True, exist_ok=True)
    processing_files = list(tasks_dir.glob(f'*{task_id}.json.processing'))
    original_files = list(tasks_dir.glob(f'*{task_id}.json'))
    src = processing_files[0] if processing_files else original_files[0] if original_files else None
    if src is not None:
        dest = blocked_dir / f'{task_id}.json'
        try:
            shutil.move(str(src), str(dest))
            logger.info('Routed task %s to blocked/ (outcome=%s)', task_id, outcome)
        except OSError as e:
            logger.critical('CRITICAL: Failed to route %s to blocked/: %s', task_id, e)
            return
    attempts = _write_retry_sidecar(blocked_dir, task_id, outcome)
    try:
        write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'autowork', 'task_id': task_id, 'event': 'task_blocked', 'detail': f'non-accept terminal ({outcome}) routed to blocked/ (attempt {attempts})', 'outcome': outcome, 'attempts': attempts})
    except OSError:
        pass
    try:
        _rf_tail = _last_failure_tail(state_dir, task_id)
        if _rf_tail:
            _blocked_spec_path = blocked_dir / f'{task_id}.json'
            _blocked_spec = json.loads(_blocked_spec_path.read_text(encoding='utf-8'))
            if isinstance(_blocked_spec, dict):
                _blocked_spec['repair_feedback'] = _rf_tail
                _blocked_spec_path.write_text(json.dumps(_blocked_spec, indent=2), encoding='utf-8')
    except (OSError, ValueError):
        pass
    current_task_path = tasks_dir / f'current_task_{task_id}.json'
    if current_task_path.exists():
        try:
            current_task_path.unlink()
        except OSError as e:
            logger.warning('Failed to remove current_task_%s.json: %s', task_id, e)

def _terminally_failed_task_ids(state_dir: Path) -> set[str]:
    """A3: task ids that have TERMINALLY failed.

    A blocked task whose retry budget is exhausted gets a
    ``blocked/<id>.exhausted`` marker (autowork_daemon._retry_blocked_tasks);
    per D-RETRY-CFG it is never re-staged again. A candidate that depends on
    such a task can therefore never have its dependency accepted, so it must be
    routed to blocked rather than skipped forever (the dep gate only treats
    ACCEPTED deps as met)."""
    blocked_dir = state_dir / 'tasks' / 'blocked'
    out: set[str] = set()
    if not blocked_dir.is_dir():
        return out
    try:
        for p in blocked_dir.glob('*.exhausted'):
            out.add(p.name[:-len('.exhausted')])
    except OSError:
        pass
    return out

def _mark_dependency_failed(state_dir: Path, task_id: str, failed_deps: list[str]) -> None:
    """A3: terminally block a task whose dependency has terminally failed.

    Routes the task to blocked/ (via _mark_blocked) AND writes its own
    ``blocked/<id>.exhausted`` marker so ``_retry_blocked_tasks`` never
    re-stages it (retrying is futile -- the dep is permanently dead) and the
    autobrief escalation (which would try to fix THIS task) does not fire.
    Without this, a dependent of an exhausted dep is neither runnable nor
    blocked, so the dispatch loop skips it forever / the single-task worker
    times out."""
    _mark_blocked(state_dir, task_id, outcome='dependency_failed')
    blocked_dir = state_dir / 'tasks' / 'blocked'
    try:
        blocked_dir.mkdir(parents=True, exist_ok=True)
        (blocked_dir / f'{task_id}.exhausted').write_text('1', encoding='utf-8')
    except OSError as e:
        logger.warning('Failed to write .exhausted for dependency_failed %s: %s', task_id, e)
    try:
        write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'autowork', 'task_id': task_id, 'event': 'dependency_failed', 'detail': f'terminally blocked: dependency terminally failed ({failed_deps})'})
    except OSError:
        pass

def _resolve_files_touched(state_dir: Path, task: dict[str, Any], task_id: str) -> list[str]:
    """Return the files_touched list for a task.

    Decomposed child tasks carry only (task_id, parent_task, specification, ...);
    the parent's files_touched is not propagated. Walk backward through
    state/tasks/processed/<parent>.json until we find an ancestor that has it,
    or the chain ends / cycles.
    """
    touched = task.get('files_touched')
    if touched:
        return list(touched)
    seen: set[str] = {task_id}
    current_parent = task.get('parent_task')
    processed_dir = state_dir / 'tasks' / 'processed'
    while current_parent and current_parent not in seen:
        seen.add(current_parent)
        parent_file = processed_dir / f'{current_parent}.json'
        if not parent_file.exists():
            return []
        try:
            with open(parent_file, 'r', encoding='utf-8') as f:
                parent_task = json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
        parent_touched = parent_task.get('files_touched')
        if parent_touched:
            return list(parent_touched)
        current_parent = parent_task.get('parent_task')
    return []

def _resolve_verification_command(state_dir: Path, task: dict[str, Any], task_id: str) -> str | None:
    """Return the verification_command for a task, resolving from parent task chain if needed."""
    vcmd = task.get('verification_command')
    if vcmd:
        return vcmd
    seen: set[str] = {task_id}
    current_parent = task.get('parent_task')
    processed_dir = state_dir / 'tasks' / 'processed'
    while current_parent and current_parent not in seen:
        seen.add(current_parent)
        parent_file = processed_dir / f'{current_parent}.json'
        if not parent_file.exists():
            return None
        try:
            with open(parent_file, 'r', encoding='utf-8') as f:
                parent_task = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
        parent_vcmd = parent_task.get('verification_command')
        if parent_vcmd:
            return parent_vcmd
        current_parent = parent_task.get('parent_task')
    return None
from harness.wire_up import check_wired
from harness.wire_up import WireResult

def _new_module_red_by_absence(task, worktree_root, verify_exit, verify_out) -> bool:
    """Return True iff this is a test_authoring RED-by-absence oracle.

    A RED-by-absence oracle authors a NEW test for a module that does NOT yet
    exist on disk: the verification_command fails specifically because importing
    the not-yet-built target raises ModuleNotFoundError / ImportError /
    AttributeError referencing it. For such a task the vcmd-exit-0 gate and the
    mutant non-vacuity gate are INAPPLICABLE (you cannot make a test pass
    against, nor mutate, a module that does not exist), so they are bypassed for
    this case ONLY -- the oracle's non-vacuity is established by construction
    (it cannot pass without the real module).

    Narrowly scoped and fail-closed. Returns True iff ALL hold (else False;
    never raises):
      (a) (task.meta_task_type or task.constraints.meta_task_type) ==
          'test_authoring';
      (b) mutation_target is a non-empty BARE dotted module name (reject any
          value containing '/', '\\', '..', or ending in '.py');
      (c) the target module file is ABSENT under ``worktree_root``;
      (d) ``verify_exit`` is not None and != 0;
      (e) ``verify_out`` contains one of ModuleNotFoundError / ImportError /
          AttributeError AND mentions the target top-level package
          (``mutation_target.split('.')[0]``).
    """
    try:
        import re as _re
        _mtt = task.get('meta_task_type') or (task.get('constraints') or {}).get('meta_task_type')
        if _mtt != 'test_authoring':
            return False
        mt = task.get('mutation_target')
        if not isinstance(mt, str) or not mt:
            return False
        if '/' in mt or '\\' in mt or '..' in mt or mt.endswith('.py'):
            return False
        if _re.fullmatch('[A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*)*', mt) is None:
            return False
        target_file = Path(worktree_root) / (mt.replace('.', '/') + '.py')
        if target_file.exists():
            return False
        if verify_exit is None or verify_exit == 0:
            return False
        out = verify_out or ''
        if not any((_e in out for _e in ('ModuleNotFoundError', 'ImportError', 'AttributeError'))):
            return False
        if mt.split('.')[0] not in out:
            return False
        return True
    except Exception:
        return False
def _wire_up_gate_enabled(state_dir=None) -> bool:
    """WIRE_UP_GATE: return ``config['autowork']['wire_up_gate']`` (default False).

    Reads the flag via the existing ``load_config()``. Ships default-OFF and
    fail-safe: ANY error (config missing / not a mapping / key absent) yields
    False so the existing accept path is preserved byte-for-byte when the flag
    is not set.
    """
    try:
        cfg = load_config()
        if not isinstance(cfg, dict):
            return False
        autowork = cfg.get('autowork')
        if not isinstance(autowork, dict):
            return False
        return bool(autowork.get('wire_up_gate', False))
    except Exception:
        return False

def _run_wire_up_gate(task, files_touched, state_dir, task_id, staging_path, worktree_root, result, working_dir) -> bool:
    """WIRE_UP_GATE: reject an orphan new module at the accept chokepoint.

    For each NEWLY-CREATED module in ``files_touched`` -- a path ending ``.py``
    not under a ``tests/`` directory and not tracked in the parent HEAD before
    this commit -- consult the module-global ``check_wired`` against
    ``staging_path``. The gate runs AFTER the staged commit and BEFORE the
    staging->parent merge, so the just-committed module lives in the staging
    worktree, NOT yet in ``working_dir``/``worktree_root``; checking the parent
    tree would always miss the file and mis-report every new module as an
    orphan. If any returns a result whose ``.wired`` is False the staging commit
    is rolled back, the staging worktree removed, an ``orphan_unwired`` ledger
    row written, the task routed to blocked/, and True (reject) is returned.
    Otherwise returns False (proceed). Only ever invoked when
    ``_wire_up_gate_enabled`` is True, so the gate is a strict no-op when the
    flag is OFF.
    """
    repo_root = staging_path

    def _tracked_in_parent(rel: str) -> bool:
        try:
            probe = subprocess.run(['git', 'cat-file', '-e', f'HEAD:{rel}'], cwd=str(worktree_root), capture_output=True, text=True, timeout=30)
            return probe.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return True
    for rel in files_touched or []:
        if not isinstance(rel, str) or not rel.endswith('.py'):
            continue
        if 'tests' in Path(rel).parts:
            continue
        _bn = Path(rel).name
        if _bn.startswith('test_') or _bn.endswith('_test.py'):
            continue
        if _tracked_in_parent(rel):
            continue
        wire_result = check_wired(repo_root, rel)
        if wire_result is not None and (not getattr(wire_result, 'wired', True)):
            logger.warning('orphan_unwired: task=%s new module %s is not reachable by any live importer -- staging rolled back fail-closed', task_id, rel)
            _rollback_rejected_commit(staging_path, result.get('sha'), rel, task_id, 'orphan_unwired')
            git_integration.remove_staging_worktree(str(staging_path), parent_root=worktree_root)
            try:
                write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'rejected', 'task_id': task_id, 'event': 'orphan_unwired', 'commit_sha': result.get('sha'), 'files': files_touched, 'file': rel, 'reason': getattr(wire_result, 'reason', '') or 'new module unreachable by any live importer'})
            except OSError as _exc:
                logger.warning('orphan_unwired: ledger append failed for %s: %s', task_id, _exc)
            _mark_blocked(state_dir, task_id, outcome='orphan_unwired')
            return True
    return False

def _rollback_rejected_commit(worktree_root: Path, sha: str | None, target_rel: str, task_id: str, kind: str) -> None:
    """Undo a rejected auto-commit without destroying a peer worker's commit.

    G-RESET-RACE: the AW3 ``git_commit.lock`` is released right after
    ``commit_accepted_output`` and BEFORE the verification_command runs, so
    between this worker's commit and its rejection-rollback a parallel worker
    can acquire the lock, commit, and advance HEAD. A blind
    ``git reset --hard HEAD~1`` would then discard the PEER's commit. This guards
    on HEAD: when this worker's ``sha`` is still the tip it hard-resets +
    checks out HEAD (byte-identical to the legacy path); otherwise it
    ``git revert --no-edit <sha>`` to surgically undo only this worker's commit,
    preserving everything committed on top. Best-effort, never raises.
    """
    try:
        head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=str(worktree_root), capture_output=True, text=True, timeout=30)
        head_sha = (head.stdout or '').strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.error('%s rollback: git rev-parse HEAD failed for %s: %s; worktree may be in inconsistent state', kind, task_id, exc)
        return
    if not head_sha:
        logger.error('%s rollback: empty HEAD for %s; skipping rollback to avoid corrupting worktree', kind, task_id)
        return
    if not sha:
        logger.error('%s rollback: no sha recorded for %s; skipping rollback to avoid a destructive HEAD~1 reset', kind, task_id)
        return
    if sha and head_sha != sha:
        try:
            rev = subprocess.run(['git', 'revert', '--no-edit', sha], cwd=str(worktree_root), capture_output=True, text=True, timeout=30)
            if rev.returncode != 0:
                subprocess.run(['git', 'revert', '--abort'], cwd=str(worktree_root), check=False, timeout=30)
                logger.error('%s rollback: git revert %s failed (a peer commit landed on top) for %s: %s; rejected commit LEFT for operator review to avoid clobbering the peer commit', kind, sha[:12], task_id, (rev.stderr or '').strip()[-200:])
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as rexc:
            try:
                subprocess.run(['git', 'revert', '--abort'], cwd=str(worktree_root), check=False, timeout=30)
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                pass
            logger.error('%s rollback: git revert raised for %s: %s; worktree may be in inconsistent state', kind, task_id, rexc)
        return
    try:
        subprocess.run(['git', 'reset', '--hard', 'HEAD~1'], cwd=str(worktree_root), check=False, timeout=30)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as rexc:
        logger.error('%s rollback: git reset --hard HEAD~1 failed for %s: %s; worktree may be in inconsistent state', kind, task_id, rexc)
    try:
        subprocess.run(['git', 'checkout', 'HEAD', '--', target_rel], cwd=str(worktree_root), check=False, timeout=30)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as cexc:
        logger.error('%s rollback: git checkout HEAD -- %s failed for %s: %s; worktree may be in inconsistent state', kind, target_rel, task_id, cexc)

def perform_process_handover(state_dir: Path) -> None:
    """Hot-swaps the running process image with the newly updated script."""
    import os
    import sys
    import logging
    import shutil
    logger = logging.getLogger('janusmask.orchestrator')
    from harness.state import serialize_orchestrator_state
    try:
        serialize_orchestrator_state(state_dir)
        logger.info('Preserved orchestrator state for handover.')
    except Exception as e:
        logger.error(f'Failed to preserve state: {e}')
    try:
        from tools.webui_server import release_for_handover
        release_for_handover()
        logger.info('Released WebUI socket/port.')
    except Exception as e:
        logger.debug(f'WebUI release not required or failed: {e}')
    executable = sys.executable or shutil.which('python3') or shutil.which('python') or '/usr/bin/python3'
    cmd_args = sys.argv
    if not cmd_args:
        cmd_args = ['-m', 'harness.orchestrator', '--state-dir', str(state_dir)]
    args = [executable] + cmd_args
    logger.info(f'Triggering os.execv with command: {args}')
    sys.stdout.flush()
    sys.stderr.flush()
    for handler in logging.root.handlers:
        handler.flush()
    try:
        os.execv(executable, args)
    except Exception as e:
        logger.critical(f'os.execv handover failed! {e}')
        raise

def _auto_approve_sensitive_eligible(state_dir, task, task_id, rel_paths, config, repo_root=None) -> bool:
    """P10-A2: pure, side-effect-free eligibility gate for auto-approving a
    self-heal harness submission that touches sensitive (harness/**) paths.

    Returns True ONLY IF ALL of the following hold; otherwise False. The whole
    body is wrapped in a broad try/except so the helper fails closed (returns
    False) on any malformed/None/missing input or config and NEVER raises:

      1. ``config['autowork']['auto_approve_sensitive_harness']`` is truthy
         (default-deny when config is None / not a mapping / key absent).
      2. ``task.get('meta_task_type') == 'harness_self_fix'``.
      3. The task is self-heal-originated: derive ``slug`` (``task_id`` itself
         if already prefixed with ``selfheal_``, else ``selfheal_<task_id>``)
         and a valid §2c marker via
         ``harness.selfheal._selfheal_provenance_valid(slug, brief_path,
         state_dir)`` where ``brief_path = repo_root / f'brief_hooks_{slug}.md'``.
         If ``repo_root`` is None, fail closed.
      4. Narrow scope: ``rel_paths`` is non-empty and EVERY rel (a) has no raw
         ``..`` path component (checked on the RAW string before any
         normalization, since ``_matches_sensitive``'s normpath would collapse
         ``harness/agent_jail.py/../test_author.py`` to an innocent-looking
         ``harness/test_author.py`` and defeat both the deny-list and the
         harness/ check), (b) does not match any pattern in
         ``_NEVER_AUTO_APPROVE``, and (c) at least one rel is a ``harness/**``
         path; sensitive-but-non-harness rels (config/**, scripts/**,
         services/**) are rejected, while non-sensitive rels (tests/**, docs,
         ...) ride along.
      5. The persisted approval count (state/control/autowork/
         auto_approve_count.json, default 0 when absent) is strictly below the
         configured ceiling (``auto_approve_sensitive_ceiling``, default 3).
         P10-B is responsible for INCREMENTING this counter; this helper only
         reads it and never mutates it.
    """
    try:
        if not isinstance(config, dict):
            return False
        autowork = config.get('autowork')
        if not isinstance(autowork, dict):
            return False
        if not autowork.get('auto_approve_sensitive_harness'):
            return False
        if not isinstance(task, dict):
            return False
        if not isinstance(task_id, str) or not task_id:
            return False
        from pathlib import Path as _Path
        _widened = bool(autowork.get('enabled'))
        if not _widened:
            if task.get('meta_task_type') != 'harness_self_fix':
                return False
            if repo_root is None:
                return False
            slug = task_id if task_id.startswith('selfheal_') else f'selfheal_{task_id}'
            brief_path = _Path(repo_root) / f'brief_hooks_{slug}.md'
            from harness.selfheal import _selfheal_provenance_valid
            if not _selfheal_provenance_valid(slug, brief_path, state_dir):
                return False
        import os as _os
        if not rel_paths:
            return False
        from harness.git_integration import _matches_sensitive, _SENSITIVE_APPLY_GLOBS
        saw_harness = False
        for rel in rel_paths:
            if not isinstance(rel, str) or not rel:
                return False
            components = []
            for piece in rel.split('/'):
                components.extend(piece.split(_os.sep))
            if '..' in components:
                return False
            if _matches_sensitive(rel, _NEVER_AUTO_APPROVE):
                return False
            if _matches_sensitive(rel, ('harness/**',)):
                saw_harness = True
            elif _matches_sensitive(rel, _SENSITIVE_APPLY_GLOBS):
                return False
            # else: non-sensitive path (tests/**, docs, ...) rides along
        if not saw_harness:
            return False
        if not _widened:
            ceiling = autowork.get('auto_approve_sensitive_ceiling', 3)
            if ceiling is None:
                ceiling = 3
            if isinstance(ceiling, bool) or not isinstance(ceiling, int):
                return False
            count = 0
            count_path = _Path(state_dir) / 'control' / 'autowork' / 'auto_approve_count.json'
            if count_path.exists():
                raw = count_path.read_text(encoding='utf-8', errors='replace')
                data = json.loads(raw)
                if isinstance(data, bool):
                    return False
                if isinstance(data, int):
                    count = data
                elif isinstance(data, dict):
                    value = data.get('count')
                    if isinstance(value, bool) or not isinstance(value, int):
                        return False
                    count = value
                else:
                    return False
            if count >= ceiling:
                return False
        return True
    except Exception:
        return False
_NEVER_AUTO_APPROVE: tuple[str, ...] = ('harness/agent_jail.py', 'harness/dbus_proxy.py', 'harness/paths.py', 'harness/git_integration.py', 'harness/orchestrator.py', 'harness/interceptors.py', 'harness/selfheal.py', 'harness/autowork_daemon.py', 'services/**')

def _apply_approval_granted(state_dir: Path, task_id: str) -> bool:
    """AGENT-ISOLATION §1b: True iff an operator approved this task's apply.

    Non-blocking read of ``state/control/decisions/<task_id>.json`` (the same
    operator-decision channel ``control_gate.await_decision`` consumes). A
    record whose ``decision`` is ``approve``/``approved`` authorizes committing
    an accepted submission that targets a protected path (harness/**,
    config/**, scripts/**). Absent/corrupt/any-other decision -> False, so a
    sensitive-path apply fails closed until the operator explicitly opts in.
    """
    path = state_dir / 'control' / 'decisions' / f'{task_id}.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8', errors='replace'))
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    return str(data.get('decision', '')).strip().lower() in ('approve', 'approved')

def _auto_approve_content_safe(state_dir, task_id) -> bool:
    """INV9: AST capability gate over the staged artifact an auto-approve grant will apply.

    Pure + side-effect free. Mirrors ``commit_accepted_output``'s artifact
    precedence so the bytes inspected here are EXACTLY the bytes that will be
    applied: (1) ``state/output/<task_id>.patches.json`` (a JSON list of
    ``{file, kind, name|marker, code}`` entries -- each entry's ``code`` string
    is collected); else (2) ``state/output/<task_id>.files.json`` (a JSON
    whole-file map ``{relpath: source}`` -- each VALUE is collected); else (3)
    ``state/output/<task_id>.py`` (a single whole-file source). Only the FIRST
    form that exists is used (forms are never merged).

    Policy:
      * No recognized artifact at all -> True. Absence of an INSPECTABLE
        artifact is NOT a capability violation; the deny-list + apply-scope
        gate already bind the grant, and blocking solely on absence would
        regress legitimate flows that stage an unanticipated artifact form.
      * Recognized artifact present but its JSON is invalid, an entry is
        malformed, or any collected source fails ``ast.parse`` -> False
        (fail-closed).
      * A collected source containing a prohibited capability -> False.
      * Otherwise (including an empty list/map with no sources to scan) -> True.

    Detection is AST-based (``ast.walk``), never substring/regex, so the bare
    names appearing inside comments or string literals never trip the gate.
    Rejected capability node shapes: an ``ast.Call`` whose func is an
    ``ast.Name`` in {eval, exec, compile, __import__}; an ``ast.Call`` on
    ``os.system`` / ``os.popen`` / ``pty.spawn``; any ``ast.Call`` on the
    ``subprocess`` module carrying a ``shell=True`` keyword.
    """
    output_dir = Path(state_dir) / 'output'
    patches_path = output_dir / f'{task_id}.patches.json'
    files_path = output_dir / f'{task_id}.files.json'
    py_path = output_dir / f'{task_id}.py'
    sources: list[str] = []
    if patches_path.exists():
        try:
            data = json.loads(patches_path.read_text(encoding='utf-8', errors='replace'))
        except Exception:
            return False
        if not isinstance(data, list):
            return False
        for entry in data:
            if not isinstance(entry, dict):
                return False
            code = entry.get('code')
            if not isinstance(code, str):
                return False
            sources.append(code)
    elif files_path.exists():
        try:
            data = json.loads(files_path.read_text(encoding='utf-8', errors='replace'))
        except Exception:
            return False
        if not isinstance(data, dict):
            return False
        for value in data.values():
            if not isinstance(value, str):
                return False
            sources.append(value)
    elif py_path.exists():
        try:
            sources.append(py_path.read_text(encoding='utf-8', errors='replace'))
        except Exception:
            return False
    else:
        return True
    _dangerous_names = {'eval', 'exec', 'compile', '__import__'}
    for src in sources:
        try:
            tree = ast.parse(src)
        except Exception:
            return False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name):
                if func.id in _dangerous_names:
                    return False
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                base = func.value.id
                attr = func.attr
                if base == 'os' and attr in {'system', 'popen'}:
                    return False
                if base == 'pty' and attr == 'spawn':
                    return False
                if base == 'subprocess':
                    for kw in node.keywords:
                        if kw.arg == 'shell' and isinstance(kw.value, ast.Constant) and (kw.value.value is True):
                            return False
    return True
_RO_GATE_TESTS = ('tests/adversarial/test_sec_inv2_trustroot.py', 'tests/adversarial/test_p10b_denylist_widen.py')
_GIT_COMMIT_LOCK_DEADLINE_SEC = 60.0

def _acquire_git_commit_lock_bounded(lock_fd, deadline_sec: float | None=None) -> bool:
    """Bounded LOCK_NB acquisition of the shared AW3 ``git_commit.lock`` (§4b, 2026-06-10).

    A *dead* prior holder's flock is auto-released by the kernel, but a LIVE
    hung holder (e.g. a wedged push) used to block the worker-side blocking
    ``LOCK_EX`` forever. Mirror the daemon's bounded posture
    (``autowork_daemon._acquire_commit_lock_or_reclaim``): retry
    ``LOCK_NB | LOCK_EX`` until *deadline_sec* elapses, then return False so
    the caller fails the commit attempt cleanly (``auto_commit_failed`` retry
    machinery) instead of hanging. On acquire the holder PID is stamped into
    the lock file (best-effort, observability only) and True is returned; the
    caller remains responsible for ``LOCK_UN``.
    """
    import fcntl
    if deadline_sec is None:
        deadline_sec = _GIT_COMMIT_LOCK_DEADLINE_SEC
    deadline = time.monotonic() + max(0.0, float(deadline_sec))
    while True:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_NB | fcntl.LOCK_EX)
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
            continue
        try:
            lock_fd.truncate(0)
            lock_fd.write(str(os.getpid()))
            lock_fd.flush()
        except OSError:
            pass
        return True

def _auto_commit_accepted(state_dir: Path, task: dict[str, Any], task_id: str) -> bool:
    """Copy accepted output to its target and create a scoped git commit.

    Delegates AST merge + git operations to
    :func:`harness.git_integration.commit_accepted_output` (ported W66 from
    this file's former inline implementation, pinned by the adversarial
    battery in ``tests/adversarial/test_git_integration_acceptance_adversarial.py``
    and ``tests/adversarial/test_ast_merge_regression_adversarial.py``).

    STAGING_REROOT: EXTERNAL tasks (``not _target_is_self(working_dir)``) now
    re-root their staging worktree under the JanusMask-owned external staging
    root: ``worktree_root`` is derived via
    ``harness.paths.effective_target_root(working_dir)`` and ``staging_path`` via
    ``harness.target_bootstrap.external_staging_root() / f'{worktree_root.name}_{task_id}'``
    (both helpers imported lazily in-body). The SELF path (when
    ``_target_is_self(working_dir)`` is True) resolves ``worktree_root`` /
    ``staging_path`` exactly as before, byte-identical to its pre-reroot form.

    Resolves ``files_touched`` via the task/parent chain and constructs an
    absolute target path rooted at the worktree top-level before calling the
    module -- the module resolves its ``target_file`` argument against CWD, so
    passing a bare relative path would escape the tmp worktree used by tests.

    F3: the prior ``.py``-only short-circuit is split into two guards. A
    non-string ``target_rel`` still early-returns ``False`` (preserves the
    None / missing-key behaviour). A non-``.py`` string falls through to
    :func:`commit_accepted_output`, which already routes those through its
    direct-copy branch per commit 3b29687.

    G19b: when ``len(files_touched) > 1`` and the manifest sidecar at
    ``state_dir/'output'/f'{task_id}.files.json'`` is absent, emit a
    ``multi_file_missing_sidecar`` warning + ledger row (best-effort;
    ``OSError`` on the row write is caught and logged) and fall through
    to the singular commit path. The agent was supposed to emit
    ``__JANUSMASK_MANIFEST__`` per the G19a-1 prompt extension; absence
    indicates a regression. The fallback is the pre-G19a behavior: commit
    ``files_touched[0] // commit is reverted via ``git reset --hard HEAD~1``
    ``files_touched[0]`` only.

    U3: after a successful commit, if ``task.get('verification_command')`` is
    a non-empty string, run it under ``shell=True`` in the worktree root with
    a 600s timeout. On non-zero exit (or ``subprocess.TimeoutExpired``), the
    commit is reverted via ``git reset --hard HEAD~1``, a ``verification_failed``
    row is appended to ``state_dir/'impl_progress.jsonl'`` (with the tails of
    stdout/stderr truncated to the last 2000 chars), a ``logger.warning`` is
    emitted, and the function returns ``False`` -- closing the silent-failure
    class that let F2's commit d419ed4 land as a no-op AST merge.

    V2: after a successful commit, if ``task.get('verification_command')`` is
    missing, None, empty, whitespace-only, or non-string, the commit is
    reverted via ``git reset --hard HEAD~1``, a ``verification_missing`` row
    is appended to ``state_dir/'impl_progress.jsonl'``, a ``logger.warning`` is
    emitted, and the function returns ``False`` -- closes the
    design-time-missing half of the U1 silent-NOOP class as defense-in-depth
    when a task bypasses the planner-side V1 enforcement.

    G3a: the vcmd subprocess.run now receives ``env=_vcmd_scrubbed_env()`` so
    JANUSMASK_* identity vars don't leak from the orchestrator's environment
    into a child pytest that imports ``harness.orchestrator``. Only the vcmd
    shell=True call is scrubbed -- the git rev-parse / reset --hard calls
    still inherit full os.environ since git relies on standard env (HOME,
    PATH, etc.).

    AW3: the ``git_integration.commit_accepted_output`` call (which
    internally runs git add/commit/rev-parse-HEAD) is wrapped in an
    ``fcntl.flock(LOCK_EX)`` over
    ``state_dir/'control'/'autowork'/'git_commit.lock'`` so concurrent
    orchestrator_worker processes (autowork daemon, Task 2) and racing
    operator-driven META commits cannot interleave git writes. Lock is
    released in a ``finally`` so any exception inside the commit call
    still releases (no permanent deadlock). Lock file is opened in 'a'
    mode (mirrors ``harness/state.py:locked_read_modify_write`` lines
    139-146) so multiple processes can share the inode reference. Lock
    is held ONLY around the commit critical section -- the verification
    subprocess and any rollback can run unlocked per the brief's
    directive (verification is parallelism-safe; git-writes are not).

    G25: the vcmd subprocess.run is now invoked under ``/bin/bash`` with the
    command string wrapped as ``set -o pipefail; {vcmd}`` so a failing
    left-hand-side of a pipeline (e.g. ``pytest ... | tail -20``)
    propagates a non-zero exit through the tail and triggers the V2
    rollback. /bin/sh on Linux is dash, which does not support
    ``set -o pipefail``, so ``executable='/bin/bash'`` is required for the
    prefix to have any effect.

    H2A (JAIL_VERIFY_MUTANT): when ``agent_jail.sandbox_enabled(load_config())``
    is True, the verify run, the mutant ``apply`` run, and the mutant rerun
    are each wrapped via ``agent_jail.build_jail_argv`` into a bubblewrap argv
    list and executed WITHOUT ``shell=True`` (the inner ``/bin/bash -c`` carries
    the ``set -o pipefail; ...`` wrapper). Each jailed call passes
    ``extra_ro=[sys.base_prefix, sys.prefix]`` so the real interpreter tree
    (miniconda) AND the active environment prefix -- which the staging
    ``.venv/bin/python`` symlinks into and which may live outside ``repo_root``
    + every ``_SYSTEM_RO`` dir -- are mounted into the jail. Without
    ``sys.base_prefix`` the jailed verify exits 127 (``python: command not
    found``); adding ``sys.prefix`` (SEC-2) keeps the verify resolvable even
    when the venv lives outside the repository root (base_prefix == prefix is a
    harmless duplicate). The vcmd interpreter token stays byte-identical (bare
    ``python -m pytest ...``); the jail resolves it from the bound prefix bin
    still on PATH (``_vcmd_scrubbed_env`` preserves PATH). When sandboxing is
    disabled, all three runs fall back to the ORIGINAL ``shell=True`` /
    ``executable='/bin/bash'`` behavior byte-for-byte.

    CRED-EXFIL (EXECUTE PATH): all four sandboxed ``build_jail_argv`` calls
    here (verify, baseline-in-copy, mutant-apply, mutant rerun) run on the
    EXECUTE path and now pass ``bind_credentials=False`` -- the jail drops the
    ~/.gemini / ~/.claude credential surface (dir binds, ~/.claude.json copy,
    project-memory + global-config overlays) and unshares the network/IPC
    namespaces so any residual credential cannot be exfiltrated off-host. The
    SEC-1 dbus_proxy_socket= kwarg, the proxied_session_bus() try/except, and
    the fail-close raise are untouched.

    SEC-3 (FAIL_CLOSED_VERIFY): the verify try/except previously caught only
    ``subprocess.TimeoutExpired``, so when sandboxing is ENABLED but bwrap is
    ABSENT the ``build_jail_argv`` / ``subprocess.run`` raised
    ``FileNotFoundError`` that escaped UNCAUGHT and crashed the worker. The
    verify run now ALSO catches ``FileNotFoundError`` (only when
    ``agent_jail.sandbox_enabled(load_config())`` is True): it logs a clear
    ``verification_sandbox_error`` warning, rolls back the staging commit via
    ``_rollback_rejected_commit``, removes the staging worktree via
    ``git_integration.remove_staging_worktree``, writes a rejected ledger row,
    and returns ``False`` CLEANLY -- it NEVER re-raises and NEVER falls through
    to an unjailed run. When sandboxing is DISABLED a FileNotFoundError is
    re-raised so the historical (no-handler) behavior of the unjailed
    shell=True branch is preserved byte-for-byte.

    SEC-1 (FAILCLOSED_VERIFY_ORCHACC): each of the four sandboxed
    ``subprocess.run`` sites (verify, baseline-in-copy, mutant-apply, mutant
    rerun) now narrows its try/except to the ``proxied_session_bus()`` CONTEXT
    ENTRY ONLY, captures the socket, and runs ``subprocess.run`` OUTSIDE that
    try (so an unrelated subprocess.run exception -- FileNotFoundError /
    TimeoutExpired -- is NOT swallowed by the proxy-entry handler and reaches
    the correct verification-stage handling). If the proxy context entry
    raises while ``agent_jail.sandbox_enabled(load_config())`` is True AND
    ``shutil.which('xdg-dbus-proxy')`` resolves a binary on PATH, the runner
    FAILS CLOSED: it raises ``RuntimeError`` (message contains 'fail-closed')
    and refuses to spawn the verify/mutant child on the unfiltered host session
    bus (which would re-expose systemd1 StartTransientUnit -- a sandbox
    escape). When ``xdg-dbus-proxy`` is simply NOT installed
    (``shutil.which`` returns None), the prior graceful degrade to
    ``dbus_proxy_socket=None`` is preserved. The proxy ExitStack is reaped in a
    ``finally`` around the synchronous ``subprocess.run`` so the filtered bus
    is torn down on every exit path.

    SEC-5c (VERIFY_EXTRA_BINDS): on top of the SEC-2 prefix binds, every jailed
    ``build_jail_argv`` call now widens ``extra_ro`` with the config-driven
    ``agent_sandbox.verify_extra_ro`` allowlist and gains an ``extra_rw`` from
    ``agent_sandbox.verify_extra_rw`` (the keyword-only param added in
    PHASE_SEC5A_JAIL_RW_AND_EMBEDDED). Both lists are read once via the
    already-available ``load_config`` using safe ``.get(..., [])`` defaults so
    configs that omit the keys remain backward compatible (empty allowlists
    leave ``extra_ro == [sys.base_prefix, sys.prefix]`` and ``extra_rw == []``
    at every site). The ``[sys.base_prefix, sys.prefix]`` SEC-2 prefix is
    NEVER dropped -- ``verify_extra_ro`` is appended after it.

    G3_VENV (VENV_JAIL): for EXTERNAL tasks the four jailed verify/mutant runs
    are pinned to the TARGET repository's own virtualenv. A local
    ``_ext_venv_ro`` list binds ``<worktree_root>/.venv`` read-only into every
    jail (appended after the SEC-2 prefix + SEC-5c allowlist so neither is
    dropped) and a nested ``_venv_jail_env()`` helper returns the
    ``_vcmd_scrubbed_env()`` copy with ``<worktree_root>/.venv/bin`` PREFIXED
    onto PATH so the verification_command resolves the TARGET interpreter, not
    whatever python the harness environment happens to expose. The helper FAILS
    CLOSED: if the EXTERNAL target's ``.venv/bin/python`` is absent it raises a
    ``RuntimeError`` rather than silently inheriting the harness python. SELF
    tasks are byte-identical to the pre-G3_VENV behavior -- ``_ext_venv_ro`` is
    empty and ``_venv_jail_env()`` returns the scrubbed env unmodified (no PATH
    mutation, default interpreter), and ``bind_credentials=False`` plus the
    net/ipc namespace unshare are preserved at every site.

    ROLLBACK_WORKTREE_CHECKOUT: both ``git reset --hard HEAD~1`` rollback
    sites (verification_missing and verification_failed) are followed by a
    best-effort ``git checkout HEAD -- <target_rel>`` to scrub any stray
    working-copy drift left over from the rejected commit. The checkout is
    wrapped in the same ``(subprocess.TimeoutExpired, FileNotFoundError,
    OSError)`` try/except as the reset and logs at ERROR on failure; it
    does not change the function's return value or affect the ledger emit.

    ROLLBACK_COMPLETENESS: the non-``no_diff:`` err branch now scrubs staged +
    tracked-worktree drift. ``commit_accepted_output`` writes the merged
    file(s) and ``git add``-stages them BEFORE the failing git step, so a
    generic-exception failure (index.lock contention, commit timeout) leaves
    staged content with NO commit to ``reset --hard HEAD~1``. The branch now
    iterates the resolved ``files_touched`` list and runs a best-effort,
    non-destructive ``git reset -q -- <rel>`` + ``git checkout HEAD -- <rel>``
    per string path, wrapped in a single ``(subprocess.TimeoutExpired,
    FileNotFoundError, OSError)`` try/except that logs at ERROR and never
    raises. ``no_diff:`` is self-cleaning (staged == HEAD) and is NOT
    scrubbed. Brand-new untracked files are intentionally left for operator
    review (no ``git clean``). The branch still returns False.

    H1 (MUTATION_GATE_HARDENING): the Phase-B mutation-gate body is now wrapped
    in a try/except so any unexpected exception (copytree ENOSPC/PermissionError,
    git failure, mutant application crash) is caught fail-closed: the staging
    commit is rolled back via ``_rollback_rejected_commit`` +
    ``git_integration.remove_staging_worktree``, a ``mutation_gate_error``
    rejected ledger row is written, and the function returns ``False`` without
    re-raising. ``mutation_target`` (and any per-mutant ``stub_target``) is
    validated and normalized to a bare dotted module name BEFORE a path is built
    from it -- a value containing ``/``, ``..``, ending in ``.py``, or not a
    bare dotted module name is rejected fail-closed (same rollback +
    ``mutation_gate_error`` row) instead of crashing path operations. The
    throwaway-copy ``shutil.copytree`` ignore set is widened to also skip
    ``state``, ``samples``, ``.pytest_cache``, and ``*.egg-info``.

    MUT-MASK (MUTANT_INFRA_VS_ASSERTION): a mutant rerun can exit NON-ZERO for
    an INFRA reason rather than a genuine assertion failure -- the
    verification_command may touch a path the throwaway ``copytree`` DROPPED
    (e.g. ``samples/`` or ``state/`` per the H1-widened ignore set). The bare
    ``_mvacuous = (_mproc.returncode == 0)`` interpretation would MISREAD that
    infra fluke as 'mutant caught' and silently ACCEPT a vacuous test. To
    distinguish infra-fail from genuine assertion-fail, a BASELINE-IN-COPY
    guard (Option A, prep-validated) re-runs the UNMUTATED ``vcmd`` inside the
    fresh ``_mcopy`` -- through the SAME jail/shell discipline, pipefail
    wrapper, ``cwd``, ``extra_ro``, and scrubbed env as the mutant rerun --
    immediately after the ``copytree`` and BEFORE the mutant is applied. If
    that baseline-in-copy run exits NON-ZERO the copy is structurally unable to
    run the unmutated verify (a path dropped by the ignore set), so the mutant
    rerun cannot be trusted: a ``RuntimeError`` is raised, caught by the
    existing H1 try/except, rolled back, and recorded as
    ``mutation_gate_error`` -- it is NEVER credited as a mutant catch. When the
    baseline-in-copy passes (exit 0), behavior is byte-identical to before:
    the mutant is applied and ``_mvacuous = (_mproc.returncode == 0)`` still
    decides catch-vs-vacuous.

    ROLLB-A (TASK-SCOPED STAGING): the staging worktree path is now scoped by
    ``task_id`` -- ``worktree_root.parent / f"{worktree_root.name}_{task_id}_staging"``
    -- so concurrent pipeline runs on distinct task IDs derive distinct
    staging directories and can no longer collide on a single shared
    ``{name}_staging`` worktree. The path stays a sibling of the parent
    worktree root (under ``worktree_root.parent``) so the
    ``git_integration.create_staging_worktree`` sibling-placement constraint
    still holds, and every downstream lifecycle usage (create, .venv symlink,
    commit, verify, mutation-gate copy, rollback, merge, cleanup) operates on
    the same task-scoped ``staging_path``.

    INV9 (CONTENT_GATE): when (and only when) the apply is granted via the
    auto-approve consult (``_granted_via_auto_approve`` True) -- never on the
    operator-decision path -- the staged artifact bytes that
    ``commit_accepted_output`` will actually apply are first run through the
    pure ``_auto_approve_content_safe`` capability gate. The gate inspects the
    SAME artifact resolved in the SAME precedence the commit uses
    (.patches.json > .files.json > .py) and refuses dangerous dynamic-execution
    / shell capabilities. On a refusal both ``_approval_ok`` AND
    ``_granted_via_auto_approve`` are reset to False so the sensitive apply is
    blocked AND the ceiling counter below is NOT incremented (fail-closed). The
    operator-approval path and the flag-off path are UNTOUCHED.

    INV5 (TOCTOU_PIN): the eligibility + content gates above run BEFORE the
    ``git_commit.lock`` flock, opening a TOCTOU window in which the staged
    artifact bytes (or the parent HEAD) could be tampered between the checks
    and the actual git write. To close it, once an auto-approve grant is
    FINALIZED (after the content gate) we PIN ``_pinned_artifact_sha`` (sha256
    of the staged artifact resolved .patches.json > .files.json > .py, first
    that exists) and ``_pinned_parent_head`` (``git rev-parse HEAD`` in
    ``worktree_root``). Then INSIDE the flock, IMMEDIATELY before
    ``commit_accepted_output``, the artifact sha + parent HEAD are re-read and
    compared; on ANY mismatch the auto-approve commit is ABORTED -- the commit
    is NOT performed, ``_approval_ok`` and ``_granted_via_auto_approve`` are
    dropped to False, a telemetry line is emitted, and an error result is
    synthesized so the not-committed handler scrubs staging and returns False
    (the ceiling counter is NOT incremented). hashlib is imported lazily
    in-body (no module-level import). The operator-approval path and the
    flag-off path are UNTOUCHED -- neither pins nor compares.

    Never raises (except the SEC-1 fail-closed RuntimeError above). Returns
    True only if a new commit was produced and the required verification
    command exited zero.
    """
    from harness import agent_jail
    from harness.dbus_proxy import proxied_session_bus
    from harness import git_integration
    from harness._journal import write_jsonl_row
    from harness.orchestrator import _resolve_files_touched, _resolve_verification_command, _vcmd_scrubbed_env, logger
    import contextlib
    import fcntl
    import shutil
    import subprocess
    import sys
    import time
    _sandbox_cfg = load_config().get('agent_sandbox', {})
    verify_extra_ro = _sandbox_cfg.get('verify_extra_ro', [])
    verify_extra_rw = _sandbox_cfg.get('verify_extra_rw', [])
    from harness.paths import _target_is_self
    working_dir = task.get('working_dir')
    files_touched = _resolve_files_touched(state_dir, task, task_id)
    if not files_touched:
        logger.info('auto-commit: skipped %s (no files_touched resolved)', task_id)
        return False
    target_rel = files_touched[0]
    if not isinstance(target_rel, str):
        logger.info('auto-commit: skipped %s (target %r is not a string path)', task_id, target_rel)
        return False
    sidecar_path = state_dir / 'output' / f'{task_id}.files.json'
    if len(files_touched) > 1 and (not sidecar_path.exists()):
        logger.warning('auto-commit: multi-file task %s has %d files_touched but no sidecar at %s; agent failed to emit __JANUSMASK_MANIFEST__; falling back to singular commit of files_touched[0]=%s', task_id, len(files_touched), sidecar_path, target_rel)
        try:
            write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'auto_commit', 'task_id': task_id, 'event': 'multi_file_missing_sidecar', 'reason': 'agent_did_not_emit_manifest', 'files': files_touched, 'exit': 0})
        except OSError as exc:
            logger.warning('multi_file_missing_sidecar: ledger append failed for %s: %s', task_id, exc)
    if not target_rel.endswith('.py'):
        logger.info('auto-commit: target %s is non-py; delegating to git_integration.commit_accepted_output (direct-copy path)', task_id)
    if not _target_is_self(working_dir):
        from harness.paths import effective_target_root
        from harness.target_bootstrap import external_staging_root
        worktree_root = Path(effective_target_root(working_dir)).resolve()
        staging_path = Path(external_staging_root()) / f'{worktree_root.name}_{task_id}'
    else:
        try:
            rev = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True, check=True, timeout=10, cwd=str(state_dir.parent))
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning('auto-commit: git rev-parse failed for %s: %s', task_id, exc)
            return False
        worktree_root = Path(rev.stdout.strip()).resolve()
        staging_path = worktree_root.parent / f'{worktree_root.name}_{task_id}_staging'
    logger.info('auto-commit: using staging worktree at %s for task %s', staging_path, task_id)
    _ext_venv_ro = [str(worktree_root / '.venv')] if not _target_is_self(working_dir) else []

    def _venv_jail_env() -> dict[str, str]:
        _env = _vcmd_scrubbed_env()
        if _target_is_self(working_dir):
            return _env
        _venv_bin = worktree_root / '.venv' / 'bin'
        if not (_venv_bin / 'python').exists():
            raise RuntimeError('G3_VENV: refusing to run the verification_command for an EXTERNAL target whose virtualenv is missing (%s is absent); the orchestrator will NOT silently inherit the harness environment python (no-venv refusal, fail-closed). Create the target .venv and retry.' % (_venv_bin / 'python',))
        _path = _env.get('PATH', '')
        _env['PATH'] = str(_venv_bin) + (os.pathsep + _path if _path else '')
        return _env
    if not _target_is_self(working_dir):
        _dirty = subprocess.run(['git', 'status', '--porcelain'], cwd=str(worktree_root), capture_output=True, text=True)
        if _dirty.returncode == 0 and _dirty.stdout.strip():
            raise RuntimeError('EXTERNAL_DIRTY_GATE (REV23 §3-2): refusing to stage/commit an EXTERNAL target whose repository has a dirty working tree; JanusMask never auto-stages or stashes a user repo (working_dir=%r is outside the JanusMask tree). Commit or stash the external working tree and retry.' % (working_dir,))
    try:
        git_integration.create_staging_worktree(str(staging_path), parent_root=worktree_root)
    except Exception as e:
        logger.error('Failed to create staging worktree for %s: %s', task_id, e)
        return False
    try:
        parent_venv = worktree_root / '.venv'
        staging_venv = staging_path / '.venv'
        if parent_venv.exists() and (not staging_venv.exists()):
            try:
                os.symlink(parent_venv.resolve(), staging_venv)
            except Exception as sym_exc:
                logger.warning('Failed to symlink .venv to staging: %s', sym_exc)
        target_abs = str((worktree_root / target_rel).resolve())
        _mtt = task.get('meta_task_type') or (task.get('constraints') or {}).get('meta_task_type')
        _approval_ok = _apply_approval_granted(state_dir, task_id)
        _granted_via_auto_approve = False
        if not _approval_ok:
            _approval_ok = _auto_approve_sensitive_eligible(state_dir, task, task_id, files_touched, load_config(), repo_root=worktree_root)
            _granted_via_auto_approve = _approval_ok
        if _granted_via_auto_approve and (not _auto_approve_content_safe(state_dir, task_id)):
            _approval_ok = False
            _granted_via_auto_approve = False

        def _inv5_artifact_sha() -> str | None:
            import hashlib
            _odir = Path(state_dir) / 'output'
            for _aname in (f'{task_id}.patches.json', f'{task_id}.files.json', f'{task_id}.py'):
                _apath = _odir / _aname
                if _apath.exists():
                    try:
                        return hashlib.sha256(_apath.read_bytes()).hexdigest()
                    except OSError:
                        return None
            return None

        def _inv5_parent_head() -> str | None:
            try:
                _rp = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, cwd=str(worktree_root), timeout=10)
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                return None
            return _rp.stdout.strip() if _rp.returncode == 0 else None
        _pinned_artifact_sha = _inv5_artifact_sha() if _granted_via_auto_approve else None
        _pinned_parent_head = _inv5_parent_head() if _granted_via_auto_approve else None
        _ro_gate_cfg = load_config()
        _ro_gate_on = bool(isinstance(_ro_gate_cfg, dict) and isinstance(_ro_gate_cfg.get('autowork'), dict) and _ro_gate_cfg['autowork'].get('auto_approve_ro_gate'))
        if _granted_via_auto_approve and _ro_gate_on and (not git_integration._verify_from_ro_parent(worktree_root, _pinned_parent_head, staging_path, _RO_GATE_TESTS)):
            _approval_ok = False
            _granted_via_auto_approve = False
            logger.warning('auto_approve_ro_gate_failed: aborting auto-approve commit for %s -- the RO-parent verification gate refused the staged candidate (git_integration._verify_from_ro_parent returned False against pinned parent HEAD %s); treating as refused apply', task_id, _pinned_parent_head)
            try:
                write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'rejected', 'task_id': task_id, 'event': 'auto_approve_ro_gate_failed', 'commit_sha': None, 'files': files_touched, 'reason': 'RO-parent verification gate refused the staged candidate'})
            except OSError as _exc:
                logger.warning('auto_approve_ro_gate_failed: ledger append failed for %s: %s', task_id, _exc)
        lock_dir = state_dir / 'control' / 'autowork'
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / 'git_commit.lock'
        with open(lock_path, 'a') as lock_fd:
            _lock_acquired = _acquire_git_commit_lock_bounded(lock_fd)
            try:
                if not _lock_acquired:
                    logger.warning('git_commit_lock_timeout: failing commit attempt for %s -- git_commit.lock still held by a live process after %.0fs; routing to auto_commit_failed instead of blocking', task_id, _GIT_COMMIT_LOCK_DEADLINE_SEC)
                    try:
                        write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'rejected', 'task_id': task_id, 'event': 'git_commit_lock_timeout', 'commit_sha': None, 'files': files_touched, 'reason': 'git_commit.lock held by a live process past the acquisition deadline'})
                    except OSError as _exc:
                        logger.warning('git_commit_lock_timeout: ledger append failed for %s: %s', task_id, _exc)
                    result = {'committed': False, 'error': 'git_commit_lock_timeout: git_commit.lock held by a live process past the acquisition deadline'}
                _inv5_abort = False
                if _lock_acquired and _granted_via_auto_approve:
                    _now_artifact_sha = _inv5_artifact_sha()
                    _now_parent_head = _inv5_parent_head()
                    if _now_artifact_sha != _pinned_artifact_sha or _now_parent_head != _pinned_parent_head:
                        _inv5_abort = True
                        _approval_ok = False
                        _granted_via_auto_approve = False
                        logger.warning('INV5 TOCTOU_PIN: aborting auto-approve commit for %s -- staged artifact or parent HEAD changed between pin and commit (artifact sha pinned=%s now=%s, parent HEAD pinned=%s now=%s); treating as refused apply', task_id, _pinned_artifact_sha, _now_artifact_sha, _pinned_parent_head, _now_parent_head)
                        try:
                            write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'rejected', 'task_id': task_id, 'event': 'auto_approve_toctou_pin_mismatch', 'commit_sha': None, 'files': files_touched, 'reason': 'staged artifact bytes or parent HEAD changed between pin and commit'})
                        except OSError as _exc:
                            logger.warning('auto_approve_toctou_pin_mismatch: ledger append failed for %s: %s', task_id, _exc)
                        result = {'committed': False, 'error': 'auto_approve_toctou_pin_mismatch: staged artifact bytes or parent HEAD changed between pin and commit'}
                if _lock_acquired and (not _inv5_abort):
                    result = git_integration.commit_accepted_output(task_id, target_abs, state_dir, worktree_root=staging_path, allowed_files=set(files_touched), meta_task_type=_mtt, approval_ok=_approval_ok, working_dir=working_dir, widened_auto_approve=_granted_via_auto_approve)
                    if _granted_via_auto_approve and result.get('committed'):
                        _count_path = Path(state_dir) / 'control' / 'autowork' / 'auto_approve_count.json'
                        _n = 0
                        try:
                            _cdata = json.loads(_count_path.read_text(encoding='utf-8', errors='replace'))
                            if isinstance(_cdata, dict) and isinstance(_cdata.get('count'), int) and (not isinstance(_cdata.get('count'), bool)):
                                _n = _cdata['count']
                            elif isinstance(_cdata, int) and (not isinstance(_cdata, bool)):
                                _n = _cdata
                        except Exception:
                            _n = 0
                        _count_path.write_text(json.dumps({'count': _n + 1}), encoding='utf-8')
            finally:
                if _lock_acquired:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
        if result.get('committed'):
            vcmd = _resolve_verification_command(state_dir, task, task_id)
            if not (isinstance(vcmd, str) and vcmd.strip()):
                logger.warning('verification_missing: task=%s -- staging rolled back; tasks must carry a non-empty verification_command', task_id)
                _rollback_rejected_commit(staging_path, result.get('sha'), target_rel, task_id, 'verification_missing')
                git_integration.remove_staging_worktree(str(staging_path), parent_root=worktree_root)
                try:
                    write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'rejected', 'task_id': task_id, 'event': 'verification_missing', 'commit_sha': result.get('sha'), 'files': [target_rel], 'reason': 'verification_command missing, empty, or non-string'})
                except OSError as exc:
                    logger.warning('verification_missing: ledger append failed for %s: %s', task_id, exc)
                return False

            def _is_unscoped_pytest(cmd_str: str) -> bool:
                if 'pytest' not in cmd_str:
                    return False
                import shlex
                try:
                    parts = shlex.split(cmd_str)
                except Exception:
                    parts = cmd_str.split()
                idx = -1
                for i, part in enumerate(parts):
                    if part == 'pytest' or part.endswith('/pytest'):
                        idx = i
                        break
                if idx == -1:
                    return False
                args = parts[idx + 1:]
                options_with_args = {'-k', '-m', '-o', '-c', '-p', '--tb', '--import-mode', '--color', '--durations', '--maxfail', '--lf', '--last-failed', '--ff', '--failed-first', '--nf', '--new-first', '--cache-clear', '--rootdir', '--override-ini', '--show-capture'}
                has_target = False
                skip_next = False
                for arg in args:
                    if skip_next:
                        skip_next = False
                        continue
                    if arg.startswith('-'):
                        if arg in options_with_args:
                            skip_next = True
                        continue
                    has_target = True
                    break
                return not has_target
            if _is_unscoped_pytest(vcmd):
                from harness.test_scoper import get_relevant_test_files
                relevant_tests = get_relevant_test_files(staging_path, files_touched)
                existing_tests = [t for t in relevant_tests if (staging_path / t).exists()]
                if not existing_tests:
                    existing_tests = ['tests/test_import.py']
                vcmd = vcmd.rstrip() + ' ' + ' '.join(existing_tests)
                logger.info('Rewrote unscoped pytest command for task %s to: %s', task_id, vcmd)
            verify_exit: int | None = None
            verify_stdout = ''
            verify_stderr = ''
            timed_out = False
            try:
                _vcfg = load_config().get('synthesis', {}) or {}
                verification_timeout = int(_vcfg.get('verification_timeout_seconds', max(900, int(_vcfg.get('timeout_seconds', 600)))))
            except Exception:
                verification_timeout = 600
            try:
                _vfull = f'set -o pipefail; {vcmd}'
                if agent_jail.sandbox_enabled(load_config()):
                    _dbus_stack = contextlib.ExitStack()
                    try:
                        _sock = _dbus_stack.enter_context(proxied_session_bus())
                    except Exception:
                        if shutil.which('xdg-dbus-proxy') is not None:
                            _dbus_stack.close()
                            raise RuntimeError('agent_sandbox is enabled and xdg-dbus-proxy is present but the filtered D-Bus proxy failed to start; refusing to spawn an agent on the unfiltered host bus (fail-closed).')
                        _sock = None
                    try:
                        vproc = subprocess.run(agent_jail.build_jail_argv(['/bin/bash', '-c', _vfull], repo_root=worktree_root, work_dir=staging_path, state_dir=state_dir, extra_ro=[sys.base_prefix, sys.prefix] + list(verify_extra_ro) + _ext_venv_ro, extra_rw=list(verify_extra_rw), dbus_proxy_socket=_sock, bind_credentials=False), cwd=str(staging_path), capture_output=True, text=True, timeout=verification_timeout, env=_venv_jail_env())
                    finally:
                        _dbus_stack.close()
                else:
                    if not _target_is_self(working_dir):
                        raise RuntimeError('FLAG2_ORCH (REV22 §3): refusing to run the verification_command UNJAILED via shell=True on the host because agent_sandbox is disabled and the target is EXTERNAL (working_dir=%r is outside the JanusMask tree). An external verify/baseline/mutant spawn MUST run inside the bubblewrap jail; enable agent_sandbox.bwrap or origin the task against self.' % (working_dir,))
                    vproc = subprocess.run(_vfull, shell=True, cwd=str(staging_path), capture_output=True, text=True, timeout=verification_timeout, env=_vcmd_scrubbed_env(), executable='/bin/bash')
                verify_exit = vproc.returncode
                verify_stdout = vproc.stdout or ''
                verify_stderr = vproc.stderr or ''
            except subprocess.TimeoutExpired as texc:
                timed_out = True
                verify_exit = 124
                partial_out = texc.stdout
                partial_err = texc.stderr
                if isinstance(partial_out, (bytes, bytearray)):
                    verify_stdout = partial_out.decode('utf-8', 'replace')
                elif isinstance(partial_out, str):
                    verify_stdout = partial_out
                if isinstance(partial_err, (bytes, bytearray)):
                    verify_stderr = partial_err.decode('utf-8', 'replace')
                elif isinstance(partial_err, str):
                    verify_stderr = partial_err
                verify_stderr = (verify_stderr + '\n' if verify_stderr else '') + f'[verification_command timed out after {verification_timeout}s: {texc!r}]'
            except FileNotFoundError as fnf:
                if agent_jail.sandbox_enabled(load_config()):
                    logger.warning('verification_sandbox_error: task=%s -- sandbox enabled but bwrap/jail unavailable (%r); staging rolled back fail-closed (never run unjailed)', task_id, fnf)
                    _rollback_rejected_commit(staging_path, result.get('sha'), target_rel, task_id, 'verification_sandbox_error')
                    git_integration.remove_staging_worktree(str(staging_path), parent_root=worktree_root)
                    try:
                        write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'rejected', 'task_id': task_id, 'event': 'verification_sandbox_error', 'commit_sha': result.get('sha'), 'files': [target_rel], 'reason': str(fnf)})
                    except OSError as exc:
                        logger.warning('verification_sandbox_error: ledger append failed for %s: %s', task_id, exc)
                    return False
                raise
            _nm_oracle = _new_module_red_by_absence(task, worktree_root, verify_exit, (verify_stdout or '') + '\n' + (verify_stderr or ''))
            if verify_exit != 0 and not _nm_oracle:
                cmd_preview = vcmd if len(vcmd) <= 200 else vcmd[:200] + '...(truncated)'
                logger.warning('verification_failed: task=%s exit=%s timeout=%s cmd=%s', task_id, verify_exit, timed_out, cmd_preview)
                _rollback_rejected_commit(staging_path, result.get('sha'), target_rel, task_id, 'verification_failed')
                git_integration.remove_staging_worktree(str(staging_path), parent_root=worktree_root)
                stdout_tail = verify_stdout[-2000:] if verify_stdout else ''
                stderr_tail = verify_stderr[-2000:] if verify_stderr else ''
                try:
                    write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'rejected', 'task_id': task_id, 'event': 'verification_failed', 'exit': verify_exit, 'stdout_tail': stdout_tail, 'stderr_tail': stderr_tail, 'commit_sha': result.get('sha'), 'files': [target_rel], 'timed_out': timed_out})
                except OSError as exc:
                    logger.warning('verification_failed: ledger append failed for %s: %s', task_id, exc)
                return False
            logger.info('auto-commit: SUCCESS in staging for %s -> %s (sha=%s)', task_id, target_rel, result.get('sha'))
            _mut_specs = list(task.get('mutations') or [])
            _mut_target = task.get('mutation_target')
            if (_mtt == 'test_authoring' or _mut_specs or _mut_target) and not _nm_oracle:
                if not _mut_specs and (not _mut_target):
                    logger.warning('mutation_gate_missing: task=%s declares no mutant -- rejected fail-closed', task_id)
                    _rollback_rejected_commit(staging_path, result.get('sha'), target_rel, task_id, 'mutation_gate_missing')
                    git_integration.remove_staging_worktree(str(staging_path), parent_root=worktree_root)
                    try:
                        write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'rejected', 'task_id': task_id, 'event': 'mutation_gate_missing', 'commit_sha': result.get('sha'), 'files': files_touched, 'reason': 'test_authoring task must declare mutation_target or mutations[]'})
                    except OSError as _exc:
                        logger.warning('mutation_gate_missing: ledger append failed for %s: %s', task_id, _exc)
                    return False
                try:
                    import re as _re
                    import tempfile

                    def _valid_mut_module(_v: object) -> bool:
                        if not isinstance(_v, str) or not _v:
                            return False
                        if '/' in _v or '\\' in _v or '..' in _v or _v.endswith('.py'):
                            return False
                        return _re.fullmatch('[A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*)*', _v) is not None
                    _mut_all = list(_mut_specs)
                    if _mut_target:
                        if not _valid_mut_module(_mut_target):
                            raise ValueError(f'malformed mutation_target {_mut_target!r}: not a bare dotted module name')
                        _mut_all.append({'stub_target': _mut_target})
                    for _mi, _mut in enumerate(_mut_all):
                        _mtmp = tempfile.mkdtemp(prefix='jm_mutgate_')
                        _mvacuous = True
                        try:
                            _mcopy = os.path.join(_mtmp, 'staging')
                            shutil.copytree(str(staging_path), _mcopy, symlinks=True, ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc', 'state', 'samples', '.pytest_cache', '*.egg-info'))
                            _bfull = f'set -o pipefail; {vcmd}'
                            if agent_jail.sandbox_enabled(load_config()):
                                _dbus_stack = contextlib.ExitStack()
                                try:
                                    _sock = _dbus_stack.enter_context(proxied_session_bus())
                                except Exception:
                                    if shutil.which('xdg-dbus-proxy') is not None:
                                        _dbus_stack.close()
                                        raise RuntimeError('agent_sandbox is enabled and xdg-dbus-proxy is present but the filtered D-Bus proxy failed to start; refusing to spawn an agent on the unfiltered host bus (fail-closed).')
                                    _sock = None
                                try:
                                    _bproc = subprocess.run(agent_jail.build_jail_argv(['/bin/bash', '-c', _bfull], repo_root=worktree_root, work_dir=_mcopy, state_dir=state_dir, extra_ro=[sys.base_prefix, sys.prefix] + list(verify_extra_ro) + _ext_venv_ro, extra_rw=list(verify_extra_rw), dbus_proxy_socket=_sock, bind_credentials=False), cwd=_mcopy, capture_output=True, text=True, timeout=verification_timeout, env=_venv_jail_env())
                                finally:
                                    _dbus_stack.close()
                            else:
                                if not _target_is_self(working_dir):
                                    raise RuntimeError('FLAG2_ORCH (REV22 §3): refusing to run the verification_command UNJAILED via shell=True on the host because agent_sandbox is disabled and the target is EXTERNAL (working_dir=%r is outside the JanusMask tree). An external verify/baseline/mutant spawn MUST run inside the bubblewrap jail; enable agent_sandbox.bwrap or origin the task against self.' % (working_dir,))
                                _bproc = subprocess.run(_bfull, shell=True, cwd=_mcopy, capture_output=True, text=True, timeout=verification_timeout, env=_vcmd_scrubbed_env(), executable='/bin/bash')
                            if _bproc.returncode != 0:
                                raise RuntimeError(f'mutation_gate baseline-in-copy failed for mutant #{_mi}: the unmutated verification_command exits {_bproc.returncode} inside the mutant copy (a path dropped by the copytree ignore set); the mutant rerun cannot be trusted as a catch')
                            _applied = True
                            if _mut.get('stub_target'):
                                _st = _mut.get('stub_target')
                                if not _valid_mut_module(_st):
                                    raise ValueError(f'malformed stub_target {_st!r}: not a bare dotted module name')
                                from harness import test_author
                                _sf = os.path.join(_mcopy, _st.replace('.', '/') + '.py')
                                with open(_sf, 'r', encoding='utf-8') as _rf:
                                    _osrc = _rf.read()
                                with open(_sf, 'w', encoding='utf-8') as _wf:
                                    _wf.write(test_author.stub_for(_osrc))
                            elif _mut.get('apply'):
                                _afull = f'set -o pipefail; {_mut['apply']}'
                                if agent_jail.sandbox_enabled(load_config()):
                                    _dbus_stack = contextlib.ExitStack()
                                    try:
                                        _sock = _dbus_stack.enter_context(proxied_session_bus())
                                    except Exception:
                                        if shutil.which('xdg-dbus-proxy') is not None:
                                            _dbus_stack.close()
                                            raise RuntimeError('agent_sandbox is enabled and xdg-dbus-proxy is present but the filtered D-Bus proxy failed to start; refusing to spawn an agent on the unfiltered host bus (fail-closed).')
                                        _sock = None
                                    try:
                                        _ap = subprocess.run(agent_jail.build_jail_argv(['/bin/bash', '-c', _afull], repo_root=worktree_root, work_dir=_mcopy, state_dir=state_dir, extra_ro=[sys.base_prefix, sys.prefix] + list(verify_extra_ro) + _ext_venv_ro, extra_rw=list(verify_extra_rw), dbus_proxy_socket=_sock, bind_credentials=False), cwd=_mcopy, capture_output=True, text=True, timeout=verification_timeout, env=_venv_jail_env())
                                    finally:
                                        _dbus_stack.close()
                                else:
                                    if not _target_is_self(working_dir):
                                        raise RuntimeError('FLAG2_ORCH (REV22 §3): refusing to run the verification_command UNJAILED via shell=True on the host because agent_sandbox is disabled and the target is EXTERNAL (working_dir=%r is outside the JanusMask tree). An external verify/baseline/mutant spawn MUST run inside the bubblewrap jail; enable agent_sandbox.bwrap or origin the task against self.' % (working_dir,))
                                    _ap = subprocess.run(_afull, shell=True, cwd=_mcopy, capture_output=True, text=True, timeout=verification_timeout, env=_vcmd_scrubbed_env(), executable='/bin/bash')
                                _applied = _ap.returncode == 0
                            else:
                                _applied = False
                            if _applied:
                                _rfull = f'set -o pipefail; {vcmd}'
                                if agent_jail.sandbox_enabled(load_config()):
                                    _dbus_stack = contextlib.ExitStack()
                                    try:
                                        _sock = _dbus_stack.enter_context(proxied_session_bus())
                                    except Exception:
                                        if shutil.which('xdg-dbus-proxy') is not None:
                                            _dbus_stack.close()
                                            raise RuntimeError('agent_sandbox is enabled and xdg-dbus-proxy is present but the filtered D-Bus proxy failed to start; refusing to spawn an agent on the unfiltered host bus (fail-closed).')
                                        _sock = None
                                    try:
                                        _mproc = subprocess.run(agent_jail.build_jail_argv(['/bin/bash', '-c', _rfull], repo_root=worktree_root, work_dir=_mcopy, state_dir=state_dir, extra_ro=[sys.base_prefix, sys.prefix] + list(verify_extra_ro) + _ext_venv_ro, extra_rw=list(verify_extra_rw), dbus_proxy_socket=_sock, bind_credentials=False), cwd=_mcopy, capture_output=True, text=True, timeout=verification_timeout, env=_venv_jail_env())
                                    finally:
                                        _dbus_stack.close()
                                else:
                                    if not _target_is_self(working_dir):
                                        raise RuntimeError('FLAG2_ORCH (REV22 §3): refusing to run the verification_command UNJAILED via shell=True on the host because agent_sandbox is disabled and the target is EXTERNAL (working_dir=%r is outside the JanusMask tree). An external verify/baseline/mutant spawn MUST run inside the bubblewrap jail; enable agent_sandbox.bwrap or origin the task against self.' % (working_dir,))
                                    _mproc = subprocess.run(_rfull, shell=True, cwd=_mcopy, capture_output=True, text=True, timeout=verification_timeout, env=_vcmd_scrubbed_env(), executable='/bin/bash')
                                _mvacuous = _mproc.returncode == 0
                        finally:
                            shutil.rmtree(_mtmp, ignore_errors=True)
                        if _mvacuous:
                            logger.warning('mutation_gate_failed: task=%s mutant #%d did not break verification (vacuous test) -- staging rolled back', task_id, _mi)
                            _rollback_rejected_commit(staging_path, result.get('sha'), target_rel, task_id, 'mutation_gate_failed')
                            git_integration.remove_staging_worktree(str(staging_path), parent_root=worktree_root)
                            try:
                                write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'rejected', 'task_id': task_id, 'event': 'mutation_gate_failed', 'commit_sha': result.get('sha'), 'files': files_touched, 'mutant_index': _mi})
                            except OSError as _exc:
                                logger.warning('mutation_gate_failed: ledger append failed for %s: %s', task_id, _exc)
                            return False
                    logger.info('mutation_gate: task=%s passed %d mutant(s)', task_id, len(_mut_all))
                except Exception as _gate_exc:
                    logger.error('mutation_gate_error: task=%s unexpected exception in mutation gate -- staging rolled back fail-closed: %s', task_id, _gate_exc)
                    _rollback_rejected_commit(staging_path, result.get('sha'), target_rel, task_id, 'mutation_gate_error')
                    git_integration.remove_staging_worktree(str(staging_path), parent_root=worktree_root)
                    try:
                        write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'rejected', 'task_id': task_id, 'event': 'mutation_gate_error', 'commit_sha': result.get('sha'), 'files': files_touched, 'reason': str(_gate_exc)})
                    except OSError as _exc:
                        logger.warning('mutation_gate_error: ledger append failed for %s: %s', task_id, _exc)
                    return False
            if _wire_up_gate_enabled(state_dir):
                if _run_wire_up_gate(task, files_touched, state_dir, task_id, staging_path, worktree_root, result, working_dir):
                    return False
            try:
                write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'accepted', 'task_id': task_id, 'event': 'auto_commit', 'commit_sha': result.get('sha'), 'files': files_touched, 'exit': 0})
            except OSError as exc:
                logger.warning('auto-commit: ledger append failed for %s: %s', task_id, exc)
            try:
                git_integration.merge_staging_to_parent(staging_path, worktree_root, working_dir=working_dir)
                logger.info('Merged staging commit back to parent repository.')
            except Exception as merge_err:
                logger.error('Failed to merge staging changes: %s', merge_err)
                _mark_blocked(state_dir, task_id, outcome='merge_failed')
                return False
            _mark_processed(state_dir, task_id)
            if 'pytest' in sys.modules or 'PYTEST_CURRENT_TEST' in os.environ:
                logger.info('Test environment detected. Skipping os.execv process handover.')
                return True
            perform_process_handover(state_dir)
            return True
        err = result.get('error')
        if err:
            logger.warning('auto-commit: FAILED %s: %s', task_id, err)
            if isinstance(err, str) and err.startswith('no_diff:'):
                try:
                    marker = state_dir / 'output' / f'{task_id}.no_diff'
                    marker.parent.mkdir(parents=True, exist_ok=True)
                    marker.write_text('1', encoding='utf-8')
                except OSError as exc:
                    logger.warning('no_diff: marker write failed for %s: %s', task_id, exc)
                try:
                    write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'rejected', 'task_id': task_id, 'event': 'no_diff', 'commit_sha': None, 'files': [target_rel], 'reason': err})
                except OSError as exc:
                    logger.warning('no_diff: ledger append failed for %s: %s', task_id, exc)
            else:
                for _rel in files_touched:
                    if not isinstance(_rel, str):
                        continue
                    try:
                        subprocess.run(['git', 'reset', '-q', '--', _rel], cwd=str(staging_path), check=False, timeout=30)
                    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as rexc:
                        logger.error('commit_failed scrub: git reset -q -- %s failed for %s: %s; worktree may be in inconsistent state', _rel, task_id, rexc)
                    try:
                        subprocess.run(['git', 'checkout', 'HEAD', '--', _rel], cwd=str(staging_path), check=False, timeout=30)
                    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as cexc:
                        logger.error('commit_failed scrub: git checkout HEAD -- %s failed for %s: %s; worktree may be in inconsistent state', _rel, task_id, cexc)
            git_integration.remove_staging_worktree(str(staging_path), parent_root=worktree_root)
        return False
    finally:
        try:
            git_integration.remove_staging_worktree(str(staging_path), parent_root=worktree_root)
        except Exception as _cleanup_exc:
            logger.error('ROLLB-D staging cleanup failed for %s: %s', task_id, _cleanup_exc)

def _promote_fuzz_failures_to_tests(task: dict, failures: list, state_dir: Path) -> None:
    """B3 (AUTO_PROMOTE_FUZZ_FAILURES): ADDITIVE, FAIL-SAFE spec sharpener.

    Turn each divergent ``FuzzFailure`` into a deterministic boundary-case hint
    and APPEND it to ``task['specification']`` as COMMENT HINTS (never executable
    asserts -- inputs can be ast-nodes / Paths that don't eval), then re-persist
    BOTH on-disk task files so the next dispatch surfaces the sharper spec via
    ``prepare_task_prompt`` / ``_stage_inbox``.

    Mirrors ``rebuild/task.py::probe_oracle_contracts``: the whole body is wrapped
    so it NEVER raises and NEVER changes the pipeline's terminal state. It only
    ever APPENDS (never overwrites) and is idempotent via the embedded marker.
    """
    MARKER = '# JANUSMASK_PROMOTED_FUZZ_TESTS'
    try:
        if not failures:
            return
        existing = task.get('specification') or task.get('description') or ''
        if MARKER in existing:
            return
        import re
        sig = (task.get('constraints') or {}).get('function_signature', '') or ''
        m = re.match('def\\s+(\\w+)\\s*\\(', sig) if isinstance(sig, str) else None
        fname = m.group(1) if m else 'target'
        lines = ['', MARKER, 'Differential-fuzzing boundary hints (reproduce this behavior EXACTLY so the differential fuzzer does not diverge on these inputs):']
        for i, f in enumerate(failures[:8]):
            try:
                args_repr = ', '.join((repr(a) for a in getattr(f, 'input_args', None) or []))
                kw_repr = ', '.join((f'{k}={v!r}' for k, v in (getattr(f, 'input_kwargs', None) or {}).items()))
                call = ', '.join((x for x in (args_repr, kw_repr) if x))
                exp = getattr(getattr(f, 'result_a', None), 'return_repr', '') or ''
                reason = getattr(f, 'reason', '') or ''
                lines.append(f'    # boundary {i}: {fname}({call})  -> result == {exp}  (reason: {reason})')
            except Exception:
                continue
        block = '\n'.join(lines)
        task['specification'] = existing + '\n' + block
        task_id = task.get('task_id', 'unknown')
        tasks_dir = state_dir / 'tasks'
        payload = json.dumps(task, indent=2)
        try:
            (tasks_dir / f'current_task_{task_id}.json').write_text(payload, encoding='utf-8')
        except OSError:
            pass
        for p in tasks_dir.glob(f'*{task_id}.json.processing'):
            try:
                p.write_text(payload, encoding='utf-8')
            except OSError:
                continue
    except Exception as exc:
        logger.warning('fuzz-promotion best-effort failed for %s: %s', task.get('task_id'), exc)
        return

def _should_bypass_or_route_task(task: Any, config: dict[str, Any]) -> str:
    """Mirror the dispatch-path MD-ROUTING decision for a single task.

    Centralizes the bypass/route classification currently expressed inline in
    ``run_pipeline`` so the in-process loop and the dispatch path share one
    decision rule. Returns one of:

    - ``'route'``  -- the task's meta_task_type policy enables stateful_fuzz
      (e.g. ``state_machine``); the dispatch path routes it to stateful
      differential fuzzing.
    - ``'bypass'`` -- the task is fuzzer-bypass-eligible: ``mtt`` is in
      ``BYPASS_FUZZER_TYPES`` (e.g. ``harness_self_fix``) or it is a
      ``test_authoring`` task whose policy sets ``skip_interface_fuzz``.
    - ``'fuzz'``   -- everything else, including a missing/None/unknown
      meta_task_type.

    INERT in ``run_pipeline``: the loop consults this helper ONLY to gate the
    existing bypass branch (it bypasses iff this returns ``'bypass'``). Both
    ``'route'`` and ``'fuzz'`` fall through to the unchanged ``fuzz_from_task``
    path, so behavior is byte-for-byte identical for every task type on HEAD
    (``state_machine`` is not in ``BYPASS_FUZZER_TYPES``, so it already reaches
    ``fuzz_from_task``). ``BYPASS_FUZZER_TYPES`` and ``META_TASK_POLICY`` are
    resolved as module globals at call time -- no new import is introduced.
    """
    if isinstance(task, dict):
        mtt = task.get('meta_task_type') or task.get('constraints', {}).get('meta_task_type')
    else:
        mtt = getattr(task, 'meta_task_type', None)
        if not mtt:
            constraints = getattr(task, 'constraints', None)
            if isinstance(constraints, dict):
                mtt = constraints.get('meta_task_type')
            elif constraints is not None:
                mtt = getattr(constraints, 'meta_task_type', None)
    policy = META_TASK_POLICY.get(mtt, {}) if mtt is not None else {}
    if isinstance(policy, dict) and policy.get('stateful_fuzz'):
        return 'route'
    _skip_ifz = mtt == 'test_authoring' and META_TASK_POLICY.get('test_authoring', {}).get('skip_interface_fuzz')
    if mtt in BYPASS_FUZZER_TYPES or _skip_ifz:
        return 'bypass'
    return 'fuzz'

def run_pipeline(config: dict[str, Any], state_dir: Path) -> None:
    """Main pipeline loop implementing the full JanusMask task lifecycle.

    Phase 1: Parallel synthesis -- both agents produce code
    Phase 2: AST validation -- verify both submissions parse and pass rules
    Phase 3: Differential fuzzing -- compare outputs on generated inputs
    Phase 4: Cross-examination -- if divergent, blind review + revise
    Phase 5: Second fuzzing -- re-fuzz revised code
    Phase 6: Decomposition -- if still divergent, break into subtasks

    Synthesis retry path is selected by ``config['synthesis']['use_retry_module']``
    (default False). When enabled (P0.2), each agent is retried independently via
    ``harness.ast_retry.synthesize_with_retries`` -- a successful agent is not
    re-invoked when only its peer has to retry. Legacy joint retry is preserved
    behind the default for backward compat.

    G10: when ``_validate_submission`` returns False for an agent, the loop
    invokes ``_try_auto_repair`` on that agent's submission. If repair returns
    a non-None source AND the repaired source re-validates, the local
    agent-code variable is swapped to the repaired source and the agent's
    valid flag is flipped to True for this round. The on-disk submission file
    under ``state/workdirs/<agent>/.../outbox/submission.py`` is NOT modified.
    """
    timeout = config['synthesis']['timeout_seconds']
    max_ast_retries = config['synthesis'].get('max_ast_retries', 3)
    use_retry_module = config['synthesis'].get('use_retry_module', False)
    active_agents = config.get('synthesis', {}).get('active_agents', ['claude', 'gemini'])
    agent_a = active_agents[0]
    agent_b = active_agents[1] if len(active_agents) > 1 else active_agents[0]
    round_number = 0
    while True:
        if control_gate.check_pause(state_dir, config):
            logger.debug('control pause flag set; sleeping %ds', POLL_INTERVAL)
            time.sleep(POLL_INTERVAL)
            continue
        task = get_next_task(state_dir)
        if task is None:
            logger.debug('No tasks available, sleeping %ds', POLL_INTERVAL)
            time.sleep(POLL_INTERVAL)
            continue
        round_number += 1
        task_id = task.get('task_id', f'round-{round_number}')
        os.environ['JANUSMASK_TASK_ID'] = task_id
        _wd = task.get('working_dir')
        if isinstance(_wd, str) and _wd:
            os.environ['JANUSMASK_WORKING_DIR'] = _wd
        else:
            os.environ.pop('JANUSMASK_WORKING_DIR', None)
        try:
            logger.info('=== Round %d | Task %s ===', round_number, task_id)
            synthesis_success = False
            claude_code = None
            gemini_code = None
            base_prompt = prepare_task_prompt(task)

            def _set_task_state(state: dict[str, Any]) -> dict[str, Any]:
                state['task_id'] = task_id
                state['round'] = round_number
                state['phase'] = 'synthesis'
                for agent_name in active_agents:
                    state[f'{agent_name}_status'] = 'running'
                state['status_updated_at_epoch'] = time.time()
                state['fuzz_results'] = None
                state['cross_exam_round'] = 0
                return state
            if use_retry_module:
                locked_read_modify_write(_set_task_state, state_dir)
                logger.info('Phase -> synthesis (ast_retry per-agent module)')
                results: dict[str, tuple[bool, str | None]] = {}
                if config.get('synthesis', {}).get('antigravity_mode', True):
                    for agent_name in (agent_a, agent_b):
                        try:
                            ok, code, _violations = synthesize_with_retries(agent_name, base_prompt, config, state_dir, round_number, task, run_agent_phase, (lambda a: lambda code, t: _validate_submission(code, a, t))(agent_name))
                        except Exception as e:
                            logger.exception('ast_retry failed for %s', agent_name)
                            ok, code = (False, None)
                        results[agent_name] = (ok, code)
                else:
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        futures = {executor.submit(synthesize_with_retries, agent_name, base_prompt, config, state_dir, round_number, task, run_agent_phase, (lambda a: lambda code, t: _validate_submission(code, a, t))(agent_name)): agent_name for agent_name in (agent_a, agent_b)}
                        for future in as_completed(futures):
                            agent_name = futures[future]
                            try:
                                ok, code, _violations = future.result()
                            except Exception:
                                logger.exception('ast_retry failed for %s', agent_name)
                                ok, code = (False, None)
                            results[agent_name] = (ok, code)
                claude_ok, claude_code = results.get(agent_a, (False, None))
                gemini_ok, gemini_code = results.get(agent_b, (False, None))
                for agent_name, code in [(agent_a, claude_code), (agent_b, gemini_code)]:
                    if code is None:
                        set_agent_status(state_dir, agent=agent_name, status='timeout')
                        _emit_lifecycle(state_dir, event='agent_status', agent=agent_name, status='timeout', task_id=task_id)
                    else:
                        set_agent_status(state_dir, agent=agent_name, status='submitted')
                        _emit_lifecycle(state_dir, event='agent_status', agent=agent_name, status='submitted', task_id=task_id)
                set_phase(state_dir, phase='ast_validation')
                _emit_lifecycle(state_dir, event='phase_transition', phase='ast_validation', task_id=task_id, phase_transition={'to': 'ast_validation'})
                logger.info('Phase -> ast_validation (validated inline by ast_retry)')
                synthesis_success = bool(claude_ok and gemini_ok and claude_code and gemini_code)
            else:
                ast_retries = 0
                claude_prompt = base_prompt
                gemini_prompt = base_prompt
                while ast_retries < max_ast_retries:
                    locked_read_modify_write(_set_task_state, state_dir)
                    logger.info('Phase -> synthesis')
                    claude_code, gemini_code = run_both_agents(claude_prompt, gemini_prompt, config, state_dir, round_number, phase_name='synthesis')
                    for agent, code in [(agent_a, claude_code), (agent_b, gemini_code)]:
                        if code is None:
                            set_agent_status(state_dir, agent=agent, status='timeout')
                            _emit_lifecycle(state_dir, event='agent_status', agent=agent, status='timeout', task_id=task_id)
                        else:
                            set_agent_status(state_dir, agent=agent, status='submitted')
                            _emit_lifecycle(state_dir, event='agent_status', agent=agent, status='submitted', task_id=task_id)
                    if not claude_code and (not gemini_code):
                        logger.error('Neither agent submitted code. Retrying.')
                        ast_retries += 1
                        claude_prompt = base_prompt + '\n\nError: Your previous submission timed out or was missing. Please try again.'
                        gemini_prompt = base_prompt + '\n\nError: Your previous submission timed out or was missing. Please try again.'
                        continue
                    if not claude_code or not gemini_code:
                        submitter = agent_a if claude_code else agent_b
                        logger.warning('Only %s submitted code. Retrying.', submitter)
                        ast_retries += 1
                        if not claude_code:
                            claude_prompt = base_prompt + '\n\nError: Your previous submission timed out or was missing. Please try again.'
                        else:
                            claude_prompt = base_prompt
                        if not gemini_code:
                            gemini_prompt = base_prompt + '\n\nError: Your previous submission timed out or was missing. Please try again.'
                        else:
                            gemini_prompt = base_prompt
                        continue
                    set_phase(state_dir, phase='ast_validation')
                    _emit_lifecycle(state_dir, event='phase_transition', phase='ast_validation', task_id=task_id, phase_transition={'to': 'ast_validation'})
                    logger.info('Phase -> ast_validation')
                    claude_valid, claude_violations = _validate_submission(claude_code, agent_a, task)
                    gemini_valid, gemini_violations = _validate_submission(gemini_code, agent_b, task)
                    if not claude_valid:
                        repaired_claude = _try_auto_repair(claude_code, claude_violations, agent_a, task_id)
                        if repaired_claude is not None:
                            revalid_ok, revalid_violations = _validate_submission(repaired_claude, agent_a, task)
                            if revalid_ok:
                                logger.info('auto_repair: %s submission re-validated after repair (task=%s)', agent_a, task_id)
                                claude_code = repaired_claude
                                claude_valid = True
                                claude_violations = revalid_violations
                            else:
                                logger.info('auto_repair: %s repair re-validation still failed (task=%s)', agent_a, task_id)
                    if not gemini_valid:
                        repaired_gemini = _try_auto_repair(gemini_code, gemini_violations, agent_b, task_id)
                        if repaired_gemini is not None:
                            revalid_ok, revalid_violations = _validate_submission(repaired_gemini, agent_b, task)
                            if revalid_ok:
                                logger.info('auto_repair: %s submission re-validated after repair (task=%s)', agent_b, task_id)
                                gemini_code = repaired_gemini
                                gemini_valid = True
                                gemini_violations = revalid_violations
                            else:
                                logger.info('auto_repair: %s repair re-validation still failed (task=%s)', agent_b, task_id)
                    if not (claude_valid and gemini_valid):
                        ast_retries += 1
                        logger.warning('AST validation failed (%s=%s, %s=%s). Retry %d/%d.', agent_a, claude_valid, agent_b, gemini_valid, ast_retries, max_ast_retries)
                        if not claude_valid:
                            error_msgs = '\n'.join((f'- {v.rule} (Line {v.line}): {v.message}' for v in claude_violations if v.severity == 'error'))
                            claude_prompt = base_prompt + f'\n\nYour previous submission failed AST validation:\n{error_msgs}\n\nPlease fix these errors and resubmit.'
                        else:
                            claude_prompt = base_prompt
                        if not gemini_valid:
                            error_msgs = '\n'.join((f'- {v.rule} (Line {v.line}): {v.message}' for v in gemini_violations if v.severity == 'error'))
                            gemini_prompt = base_prompt + f'\n\nYour previous submission failed AST validation:\n{error_msgs}\n\nPlease fix these errors and resubmit.'
                        else:
                            gemini_prompt = base_prompt
                        continue
                    synthesis_success = True
                    break
            if not synthesis_success:
                logger.warning('Synthesis or AST validation failed after retries. Rejecting.')
                set_phase(state_dir, phase='rejected')
                _emit_lifecycle(state_dir, event='phase_transition', phase='rejected', task_id=task_id, phase_transition={'to': 'rejected'})
                _mark_processed(state_dir, task_id)
                _emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
                logger.info('=== Round %d complete (Synthesis/AST failure) ===\n', round_number)
                continue
            mtt = task.get('meta_task_type') or task.get('constraints', {}).get('meta_task_type')
            _skip_ifz = mtt == 'test_authoring' and META_TASK_POLICY.get('test_authoring', {}).get('skip_interface_fuzz')
            if _should_bypass_or_route_task(task, config) == 'bypass':
                if mtt not in SKIP_SMOKE_GATE_TYPES and (not _skip_ifz):
                    smoke_err = smoke_import('_smoke_candidate', claude_code)
                    if smoke_err is not None:
                        logger.error('Smoke rejected bypass-eligible %s (mtt=%s): %s', task_id, mtt, smoke_err)
                        set_phase(state_dir, phase='rejected')
                        _emit_lifecycle(state_dir, event='phase_transition', phase='rejected', task_id=task_id, phase_transition={'to': 'rejected'})
                        _mark_processed(state_dir, task_id)
                        _emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
                        logger.info('=== Round %d complete (rejected via sandbox smoke) ===\n', round_number)
                        continue
                    working_dir = task.get('working_dir')
                    from harness import agent_jail
                    from harness.paths import _target_is_self
                    if not _target_is_self(working_dir) and (not agent_jail.sandbox_enabled(config)):
                        raise RuntimeError('FLAG2_EMBEDDED_FUZZ (REV23 §C6): refusing to run embedded tests UNJAILED on an EXTERNAL target while agent_sandbox is disabled (working_dir=%r is outside the JanusMask tree). An external candidate MUST run inside the bubblewrap jail; enable agent_sandbox.bwrap or origin the task against self.' % (working_dir,))
                    embedded_err = run_embedded_tests('_embedded_candidate', claude_code)
                    if embedded_err is not None:
                        logger.error('Embedded tests rejected bypass-eligible %s (mtt=%s): %s', task_id, mtt, embedded_err)
                        set_phase(state_dir, phase='rejected')
                        _emit_lifecycle(state_dir, event='phase_transition', phase='rejected', task_id=task_id, phase_transition={'to': 'rejected'})
                        _mark_processed(state_dir, task_id)
                        _emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
                        logger.info('=== Round %d complete (rejected via embedded tests) ===\n', round_number)
                        continue
                    working_dir = task.get('working_dir')
                    from harness import agent_jail
                    from harness.paths import _target_is_self
                    if not _target_is_self(working_dir) and (not agent_jail.sandbox_enabled(config)):
                        raise RuntimeError('FLAG2_EMBEDDED_FUZZ (REV23 §C6): refusing to run narrow-fuzz UNJAILED on an EXTERNAL target while agent_sandbox is disabled (working_dir=%r is outside the JanusMask tree). An external candidate MUST run inside the bubblewrap jail; enable agent_sandbox.bwrap or origin the task against self.' % (working_dir,))
                    narrow_err = run_narrow_fuzz(mtt, '_narrow_fuzz_candidate', claude_code)
                    if narrow_err is not None:
                        logger.error('Narrow-fuzz rejected bypass-eligible %s (mtt=%s): %s', task_id, mtt, narrow_err)
                        set_phase(state_dir, phase='rejected')
                        _emit_lifecycle(state_dir, event='phase_transition', phase='rejected', task_id=task_id, phase_transition={'to': 'rejected'})
                        _mark_processed(state_dir, task_id)
                        _emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
                        logger.info('=== Round %d complete (rejected via narrow-fuzz) ===\n', round_number)
                        continue
                else:
                    logger.info('Skipping smoke + embedded gates for %s (mtt=%s in SKIP_SMOKE_GATE_TYPES -- harness-internal code legitimately imports site-packages)', task_id, mtt)
                logger.info('Bypassing fuzzing for %s task', mtt)
                _save_final_output(state_dir, task_id, claude_code)
                decision = control_gate.await_decision(state_dir, task_id, 'accepted', config, emit_pending=lambda tid, ph: _emit_pending(state_dir, tid, ph), emit_timeout=lambda tid, ph: _emit_timeout(state_dir, tid, ph))
                if decision in ('reject', 'timeout', 'retry'):
                    set_phase(state_dir, phase='rejected')
                    _emit_lifecycle(state_dir, event='phase_transition', phase='rejected', task_id=task_id, phase_transition={'to': 'rejected'})
                    _mark_processed(state_dir, task_id)
                    _emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
                    logger.warning('=== Round %d complete (rejected via HITL %s) ===\n', round_number, decision)
                    continue
                auto_commit_ok = _auto_commit_accepted(state_dir, task, task_id)
                _mark_processed(state_dir, task_id)
                _emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
                if auto_commit_ok:
                    set_phase(state_dir, phase='accepted')
                    _emit_lifecycle(state_dir, event='phase_transition', phase='accepted', task_id=task_id, phase_transition={'to': 'accepted'})
                    logger.info('=== Round %d complete (accepted via fuzzer bypass) ===\n', round_number)
                else:
                    set_phase(state_dir, phase='rejected')
                    _emit_lifecycle(state_dir, event='phase_transition', phase='rejected', task_id=task_id, phase_transition={'to': 'rejected'})
                    logger.warning('=== Round %d complete (rejected: auto-commit failed) ===\n', round_number)
                continue
            set_phase(state_dir, phase='fuzzing')
            _emit_lifecycle(state_dir, event='phase_transition', phase='fuzzing', task_id=task_id, phase_transition={'to': 'fuzzing'})
            logger.info('Phase -> fuzzing (round 1)')
            fuzz_result = fuzz_from_task(claude_code, gemini_code, task, config, session_id=f'{task_id}_r1')
            _persist_fuzz_results(state_dir, task_id, 'round1', fuzz_result)
            if fuzz_result.error:
                logger.error('Fuzzing error: %s', fuzz_result.error)
                set_phase(state_dir, phase='rejected')
                _emit_lifecycle(state_dir, event='phase_transition', phase='rejected', task_id=task_id, phase_transition={'to': 'rejected'})
                _mark_processed(state_dir, task_id)
                _emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
                continue
            if fuzz_result.equivalent:
                logger.info('EQUIVALENT after round 1 (%d/%d inputs matched)', fuzz_result.matching_inputs, fuzz_result.total_inputs)
                _save_final_output(state_dir, task_id, claude_code)
                decision = control_gate.await_decision(state_dir, task_id, 'accepted', config, emit_pending=lambda tid, ph: _emit_pending(state_dir, tid, ph), emit_timeout=lambda tid, ph: _emit_timeout(state_dir, tid, ph))
                if decision in ('reject', 'timeout', 'retry'):
                    set_phase(state_dir, phase='rejected')
                    _emit_lifecycle(state_dir, event='phase_transition', phase='rejected', task_id=task_id, phase_transition={'to': 'rejected'})
                    _mark_processed(state_dir, task_id)
                    _emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
                    logger.warning('=== Round %d complete (rejected via HITL %s) ===\n', round_number, decision)
                    continue
                auto_commit_ok = _auto_commit_accepted(state_dir, task, task_id)
                _mark_processed(state_dir, task_id)
                _emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
                if auto_commit_ok:
                    set_phase(state_dir, phase='accepted')
                    _emit_lifecycle(state_dir, event='phase_transition', phase='accepted', task_id=task_id, phase_transition={'to': 'accepted'})
                    logger.info('=== Round %d complete (accepted) ===\n', round_number)
                else:
                    set_phase(state_dir, phase='rejected')
                    _emit_lifecycle(state_dir, event='phase_transition', phase='rejected', task_id=task_id, phase_transition={'to': 'rejected'})
                    logger.warning('=== Round %d complete (rejected: auto-commit failed) ===\n', round_number)
                continue
            logger.info('DIVERGENT after round 1 (%d failures out of %d inputs)', len(fuzz_result.failures), fuzz_result.total_inputs)
            _promote_fuzz_failures_to_tests(task, fuzz_result.failures, state_dir)
            set_phase(state_dir, phase='cross_examination')
            _emit_lifecycle(state_dir, event='phase_transition', phase='cross_examination', task_id=task_id, phase_transition={'to': 'cross_examination'})
            logger.info('Phase -> cross_examination')
            task_spec = task.get('specification') or task.get('description') or ''
            claude_packet, gemini_packet = prepare_exam_packets(claude_code, gemini_code, task_spec, fuzz_result.failures)
            write_feedback_files(state_dir, claude_packet, gemini_packet, round_number)
            revised_claude, revised_gemini = run_both_agents(claude_packet.review_prompt, gemini_packet.review_prompt, config, state_dir, round_number, phase_name='cross_examination')
            clear_feedback_files(state_dir)
            revised_claude = revised_claude or claude_code
            revised_gemini = revised_gemini or gemini_code
            set_phase(state_dir, phase='fuzzing')
            _emit_lifecycle(state_dir, event='phase_transition', phase='fuzzing', task_id=task_id, phase_transition={'to': 'fuzzing'})
            logger.info('Phase -> fuzzing (round 2)')
            fuzz_result_2 = fuzz_from_task(revised_claude, revised_gemini, task, config, session_id=f'{task_id}_r2')
            _persist_fuzz_results(state_dir, task_id, 'round2', fuzz_result_2)
            if fuzz_result_2.error:
                logger.error('Round 2 fuzzing error: %s', fuzz_result_2.error)
                set_phase(state_dir, phase='rejected')
                _emit_lifecycle(state_dir, event='phase_transition', phase='rejected', task_id=task_id, phase_transition={'to': 'rejected'})
                _mark_processed(state_dir, task_id)
                _emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
                continue
            if fuzz_result_2.equivalent:
                logger.info('EQUIVALENT after round 2 (%d/%d inputs matched)', fuzz_result_2.matching_inputs, fuzz_result_2.total_inputs)
                _save_final_output(state_dir, task_id, revised_claude)
                decision = control_gate.await_decision(state_dir, task_id, 'accepted', config, emit_pending=lambda tid, ph: _emit_pending(state_dir, tid, ph), emit_timeout=lambda tid, ph: _emit_timeout(state_dir, tid, ph))
                if decision in ('reject', 'timeout', 'retry'):
                    set_phase(state_dir, phase='rejected')
                    _emit_lifecycle(state_dir, event='phase_transition', phase='rejected', task_id=task_id, phase_transition={'to': 'rejected'})
                    _mark_processed(state_dir, task_id)
                    _emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
                    logger.warning('=== Round %d complete (rejected via HITL %s) ===\n', round_number, decision)
                    continue
                auto_commit_ok = _auto_commit_accepted(state_dir, task, task_id)
                _mark_processed(state_dir, task_id)
                _emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
                if auto_commit_ok:
                    set_phase(state_dir, phase='accepted')
                    _emit_lifecycle(state_dir, event='phase_transition', phase='accepted', task_id=task_id, phase_transition={'to': 'accepted'})
                    logger.info('=== Round %d complete (accepted after cross-exam) ===\n', round_number)
                else:
                    set_phase(state_dir, phase='rejected')
                    _emit_lifecycle(state_dir, event='phase_transition', phase='rejected', task_id=task_id, phase_transition={'to': 'rejected'})
                    logger.warning('=== Round %d complete (rejected: auto-commit failed) ===\n', round_number)
                continue
            logger.info('DIVERGENT after round 2 (%d failures). Decomposing.', len(fuzz_result_2.failures))
            set_phase(state_dir, phase='decomposition')
            _emit_lifecycle(state_dir, event='phase_transition', phase='decomposition', task_id=task_id, phase_transition={'to': 'decomposition'})
            logger.info('Phase -> decomposition')
            decomp_result = decompose_task(task, fuzz_result_2.failures, config, code_a=revised_claude, code_b=revised_gemini, depth=task.get('depth', 0))
            logger.info('Decomposed %s via %s strategy: %d subtasks', task_id, decomp_result.strategy, len(decomp_result.subtasks))
            enqueue_subtasks(decomp_result.subtasks, state_dir)
            subtask_ids = [s.task_id for s in decomp_result.subtasks]
            update_parent_state(state_dir, task_id, subtask_ids)
            _mark_processed(state_dir, task_id)
            _emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
            logger.info('=== Round %d complete (decomposed into %d subtasks) ===\n', round_number, len(subtask_ids))
        finally:
            try:
                if list((state_dir / 'tasks').glob(f'*{task_id}.json.processing')):
                    _mark_blocked(state_dir, task_id, 'pipeline_crash_orphan')
            except Exception as _orphan_exc:
                logger.error('ROLLB-E pipeline orphan-route failed for %s: %s', task_id, _orphan_exc)

def main() -> None:
    """Parse arguments, load configuration, initialize state, run pipeline."""
    parser = argparse.ArgumentParser(description='JanusMask orchestrator -- dual-agent differential fuzzing')
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG_PATH, help='Path to harness config.yaml (default: %(default)s)')
    parser.add_argument('--state-dir', type=Path, default=DEFAULT_STATE_DIR, help='Path to shared state directory (default: %(default)s)')
    parser.add_argument('--log-dir', type=Path, default=None, help='Path to log directory (default: PROJECT_DIR/logs)')
    args = parser.parse_args()
    _configure_logging(args.log_dir)
    logger.info('JanusMask orchestrator starting')
    config = load_config(args.config)
    config['state_dir'] = str(args.state_dir)
    args.state_dir.mkdir(parents=True, exist_ok=True)
    (args.state_dir / 'tasks').mkdir(parents=True, exist_ok=True)
    (args.state_dir / 'sessions').mkdir(parents=True, exist_ok=True)
    init_state(args.state_dir)
    logger.info('State initialized at %s', args.state_dir)
    try:
        run_pipeline(config, args.state_dir)
    except KeyboardInterrupt:
        logger.info('Orchestrator stopped by user')
        set_phase(args.state_dir, phase='idle')
    except Exception:
        logger.exception('Fatal error in pipeline')
        sys.exit(1)
from harness.planner.taxonomies import BYPASS_FUZZER_TYPES
from harness.planner.taxonomies import SKIP_SMOKE_GATE_TYPES
from harness.planner.taxonomies import META_TASK_POLICY

@dataclass
class Task:
    """Represents a task to be processed by the orchestrator."""
    task_id: str
    meta_task_type: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None

def should_bypass_fuzzer(task: Task) -> bool:
    """
    Determine if a task should bypass the fuzzer based on its meta_task_type.

    Args:
        task: The task to evaluate

    Returns:
        True if the task should bypass the fuzzer, False otherwise

    Handles edge cases:
        - Missing meta_task_type: returns False (does not bypass)
        - Unrecognized meta_task_type: returns False (does not bypass)
    """
    if task.meta_task_type is None:
        return False
    return task.meta_task_type in BYPASS_FUZZER_TYPES

def process_task(task: Task) -> Dict[str, Any]:
    """
    Process a task through the orchestrator pipeline.

    Args:
        task: The task to process

    Returns:
        Result dictionary with 'bypassed_fuzzer' and 'status' keys
    """
    bypassed = should_bypass_fuzzer(task)
    return {'task_id': task.task_id, 'bypassed_fuzzer': bypassed, 'status': 'processed'}

def apply(orchestrator_path: Path) -> list[str]:
    """Rewrite the ``.py``-only guard inside ``harness/orchestrator.py``.

    Idempotent: if the new two-block form is already present and the old
    single-line guard is gone, returns ``[]`` without touching the file.
    Raises ``FileNotFoundError`` if ``orchestrator_path`` does not exist and
    ``RuntimeError`` if the old guard cannot be located (defensive -- the
    META-WEBUI-AUTOBRIEF-V2 scope exception only covers this exact region).
    """
    orchestrator_path = Path(orchestrator_path)
    if not orchestrator_path.is_file():
        raise FileNotFoundError(f'orchestrator file not found: {orchestrator_path}')
    src = orchestrator_path.read_text(encoding='utf-8')
    if _NEW_GUARD in src and _OLD_GUARD not in src:
        return []
    if _OLD_GUARD not in src:
        raise RuntimeError(f'expected single-line .py-only guard not found in {orchestrator_path}; refusing to patch')
    rewritten = src.replace(_OLD_GUARD, _NEW_GUARD, 1)
    if rewritten == src:
        return []
    orchestrator_path.write_text(rewritten, encoding='utf-8')
    return [str(orchestrator_path)]

def files_touched() -> Iterable[str]:
    """Repo-relative paths this submission writes onto disk."""
    return ('harness/orchestrator.py',)

def _vcmd_scrubbed_env() -> dict[str, str]:
    """Return a copy of ``os.environ`` with every ``JANUSMASK_*`` key dropped.

    G3a: closes the JANUSMASK_* env-leak class identified in
    ``brief_hooks_vcmd_env_isolation.md``. The orchestrator's vcmd subprocess
    inherits the orchestrator's full environment by default, including
    JANUSMASK_TASK_ID / JANUSMASK_AGENT / JANUSMASK_STATE_DIR /
    JANUSMASK_ROUND / JANUSMASK_MODE / JANUSMASK_WORK_DIR /
    JANUSMASK_GEMINI_SETTINGS. When a vcmd is a pytest invocation that
    imports ``harness.orchestrator`` (e.g. ``tests/test_orchestrator.py``),
    the child pytest reads ``JANUSMASK_TASK_ID`` via ``os.environ.get(...)``
    and ends up looking for session files under the CURRENT dispatch's
    task_id instead of the test's hardcoded 'default' -- manifesting as
    vcmd-pytest failing while plain-shell pytest passes.

    Uses ``startswith('JANUSMASK_')`` rather than a per-key allowlist so the
    scrub keeps working if new JANUSMASK_* keys are added in the future
    (closed namespace by convention; no PATH/HOME collisions).

    Logs (via the module-level ``logger.info``) the count and sorted names
    of dropped keys when at least one is dropped; emits no log line on the
    zero-drop path so a clean-shell invocation stays quiet.
    """
    scrubbed = {k: v for k, v in os.environ.items() if not k.startswith('JANUSMASK_')}
    dropped = sorted((k for k in os.environ if k.startswith('JANUSMASK_')))
    if dropped:
        logger.info('vcmd env scrubbed: dropped %d JANUSMASK_* key(s): %s', len(dropped), ','.join(dropped))
    return scrubbed
_MAX_REPAIRS_PER_CALL = 32
_AUTO_REPAIR_APPLIED: dict[tuple[str, str, str], int] = {}

def _rewrite_import_calls(tree: ast.Module) -> tuple[ast.Module, list[tuple[int, str]]]:
    """Rewrite ``__import__('mod').attr(...)`` to ``mod.attr(...)``.

    Returns ``(tree, repairs)`` where ``repairs`` is a list of
    ``(lineno, description)`` tuples -- empty when nothing was rewritten,
    so the function is idempotent on clean input. After rewrites, any
    module name introduced is guaranteed to have a matching
    ``import <mod_name>`` at the top of ``tree.body`` (existing
    ``import mod_name``, ``import mod_name as alias`` and
    ``from mod_name import ...`` rows all count as 'already present').
    """
    repairs: list[tuple[int, str]] = []
    introduced: list[str] = []
    seen: set[str] = set()

    class _Rewriter(ast.NodeTransformer):

        def visit_Attribute(self, node: ast.Attribute) -> Any:
            self.generic_visit(node)
            inner = node.value
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) and (inner.func.id == '__import__') and (len(inner.args) == 1) and (not inner.keywords) and isinstance(inner.args[0], ast.Constant) and isinstance(inner.args[0].value, str) and inner.args[0].value:
                mod_name = inner.args[0].value
                if mod_name not in seen:
                    seen.add(mod_name)
                    introduced.append(mod_name)
                lineno = getattr(node, 'lineno', 0) or getattr(inner, 'lineno', 0)
                repairs.append((lineno, f'rewrote __import__({mod_name!r}).{node.attr} -> {mod_name}.{node.attr}'))
                new_node = ast.Attribute(value=ast.Name(id=mod_name, ctx=ast.Load()), attr=node.attr, ctx=node.ctx)
                return ast.copy_location(new_node, node)
            return node
    tree = _Rewriter().visit(tree)
    if introduced:
        existing: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name:
                        existing.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    existing.add(node.module)
        missing = [m for m in introduced if m not in existing]
        if missing:
            new_imports: list[ast.stmt] = [ast.Import(names=[ast.alias(name=m, asname=None)]) for m in missing]
            tree.body = new_imports + list(tree.body)
            ast.fix_missing_locations(tree)
    return (tree, repairs)

def _matches_import_call_rule(violation: Any) -> bool:
    """Match the AST enforcer's ``__import__()`` security violation."""
    rule = getattr(violation, 'rule', '') or ''
    message = getattr(violation, 'message', '') or ''
    return rule == 'security' and '__import__' in message
_FIX_CLASSES: list[dict[str, Any]] = [{'name': 'import_call_rewrite', 'matches_rule': _matches_import_call_rule, 'repair': _rewrite_import_calls}]

def _try_auto_repair(code: str, violations: list, agent: str, task_id: str) -> str | None:
    """Attempt to auto-repair a submission that failed AST validation.

    Iterates ``_FIX_CLASSES``; for each entry whose ``matches_rule``
    callable matches at least one violation, invokes ``repair(tree)``
    and accumulates repairs. Returns the unparsed repaired source when
    at least one repair applied AND the repaired source still parses;
    otherwise returns None.

    Per ``(task_id, agent, fix_class)`` loop guard: the same fix-class
    is applied at most once per dispatch. Total repair count per
    invocation is capped at ``_MAX_REPAIRS_PER_CALL`` (32) -- on cap
    hit, return None and log a warning. Never raises.
    """
    try:
        if not violations:
            return None
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            logger.warning('auto_repair: ast.parse failed for %s/%s: %s', agent, task_id, exc)
            return None
        except Exception as exc:
            logger.warning('auto_repair: ast.parse raised unexpectedly: %s', exc)
            return None
        applied: list[tuple[str, list[tuple[int, str]]]] = []
        total_repairs = 0
        for entry in _FIX_CLASSES:
            name = entry.get('name')
            matcher = entry.get('matches_rule')
            repair_fn = entry.get('repair')
            if not isinstance(name, str) or not callable(matcher) or (not callable(repair_fn)):
                continue
            guard_key = (task_id, agent, name)
            if _AUTO_REPAIR_APPLIED.get(guard_key, 0) >= 1:
                continue
            try:
                if not any((matcher(v) for v in violations)):
                    continue
            except Exception as exc:
                logger.warning('auto_repair matcher %s raised: %s', name, exc)
                continue
            try:
                tree, repairs = repair_fn(tree)
            except Exception as exc:
                logger.warning('auto_repair fix_class %s raised: %s', name, exc)
                continue
            if not repairs:
                continue
            total_repairs += len(repairs)
            if total_repairs > _MAX_REPAIRS_PER_CALL:
                logger.warning('auto_repair total repairs %d exceeded cap %d; aborting', total_repairs, _MAX_REPAIRS_PER_CALL)
                return None
            applied.append((name, repairs))
            _AUTO_REPAIR_APPLIED[guard_key] = _AUTO_REPAIR_APPLIED.get(guard_key, 0) + 1
        if not applied:
            return None
        try:
            repaired_src = ast.unparse(tree)
            ast.parse(repaired_src)
        except Exception as exc:
            logger.warning('auto_repair unparse/reparse roundtrip failed: %s', exc)
            return None
        for fix_name, repairs in applied:
            sample = repairs[0][1] if repairs else ''
            row = {'ts': time.time(), 'event': 'auto_repair_applied', 'task_id': task_id, 'phase': 'ast_validation', 'agent': agent, 'fix_class': fix_name, 'repair_count': len(repairs), 'detail': f'fix_class={fix_name} count={len(repairs)} sample={sample}', 'exit': 0}
            try:
                write_jsonl_row(DEFAULT_STATE_DIR / 'impl_progress.jsonl', row)
            except OSError as exc:
                logger.warning('auto_repair ledger append failed: %s', exc)
            except Exception as exc:
                logger.warning('auto_repair ledger append raised: %s', exc)
        logger.info('auto_repair applied %d repair(s) across %d fix-class(es) for %s/%s', total_repairs, len(applied), agent, task_id)
        return repaired_src
    except Exception as exc:
        logger.warning('auto_repair unexpected error for %s/%s: %s', agent, task_id, exc)
        return None

def _matches_subprocess_check(violation: Any) -> bool:
    """Match the AST enforcer's ``subprocess_no_check`` violation."""
    rule = getattr(violation, 'rule', '') or ''
    return rule == 'subprocess_no_check'

def _matches_os_system(violation: Any) -> bool:
    """Match the AST enforcer's ``os_system`` violation."""
    rule = getattr(violation, 'rule', '') or ''
    return rule == 'os_system'

def _matches_bare_except(violation: Any) -> bool:
    """Match the AST enforcer's ``bare_except`` violation."""
    rule = getattr(violation, 'rule', '') or ''
    return rule == 'bare_except'

def _add_subprocess_check_kwarg(tree: ast.Module) -> tuple[ast.Module, list[tuple[int, str]]]:
    """Add ``check=True`` to subprocess.{run,call,check_output,check_call,Popen} calls.

    Returns ``(tree, repairs)`` where ``repairs`` is a list of
    ``(lineno, description)`` tuples -- empty when nothing was rewritten,
    so the function is idempotent on clean input. Calls that already
    pass a ``check=`` keyword (regardless of value) are skipped to
    preserve user intent.
    """
    repairs: list[tuple[int, str]] = []
    _targets = {'run', 'call', 'check_output', 'check_call', 'Popen'}

    class _Adder(ast.NodeTransformer):

        def visit_Call(self, node: ast.Call) -> Any:
            self.generic_visit(node)
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and (func.value.id == 'subprocess') and (func.attr in _targets):
                has_check = any((kw.arg == 'check' for kw in node.keywords))
                if not has_check:
                    node.keywords.append(ast.keyword(arg='check', value=ast.Constant(value=True)))
                    lineno = getattr(node, 'lineno', 0)
                    repairs.append((lineno, f'added check=True to subprocess.{func.attr}(...)'))
            return node
    tree = _Adder().visit(tree)
    if repairs:
        ast.fix_missing_locations(tree)
    return (tree, repairs)

def _rewrite_os_system_to_subprocess(tree: ast.Module) -> tuple[ast.Module, list[tuple[int, str]]]:
    """Rewrite ``os.system(cmd)`` to ``subprocess.run(shlex.split(cmd), check=True)``.

    Returns ``(tree, repairs)`` where ``repairs`` is a list of
    ``(lineno, description)`` tuples -- empty when nothing was rewritten,
    so the function is idempotent on clean input. When at least one
    rewrite occurs, ``import subprocess`` and ``import shlex`` are
    injected at the top of ``tree.body`` if not already present (mirrors
    the idiom in ``_rewrite_import_calls``).
    """
    repairs: list[tuple[int, str]] = []
    introduced: list[str] = []

    class _Rewriter(ast.NodeTransformer):

        def visit_Call(self, node: ast.Call) -> Any:
            self.generic_visit(node)
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and (func.value.id == 'os') and (func.attr == 'system') and (len(node.args) == 1) and (not node.keywords):
                original_arg = node.args[0]
                shlex_split = ast.Call(func=ast.Attribute(value=ast.Name(id='shlex', ctx=ast.Load()), attr='split', ctx=ast.Load()), args=[original_arg], keywords=[])
                new_call = ast.Call(func=ast.Attribute(value=ast.Name(id='subprocess', ctx=ast.Load()), attr='run', ctx=ast.Load()), args=[shlex_split], keywords=[ast.keyword(arg='check', value=ast.Constant(value=True))])
                lineno = getattr(node, 'lineno', 0)
                repairs.append((lineno, 'rewrote os.system(...) -> subprocess.run(shlex.split(...), check=True)'))
                if 'subprocess' not in introduced:
                    introduced.append('subprocess')
                if 'shlex' not in introduced:
                    introduced.append('shlex')
                return ast.copy_location(new_call, node)
            return node
    tree = _Rewriter().visit(tree)
    if introduced:
        existing: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name:
                        existing.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    existing.add(node.module)
        missing = [m for m in introduced if m not in existing]
        if missing:
            new_imports: list[ast.stmt] = [ast.Import(names=[ast.alias(name=m, asname=None)]) for m in missing]
            tree.body = new_imports + list(tree.body)
        ast.fix_missing_locations(tree)
    return (tree, repairs)

def _typed_bare_except(tree: ast.Module) -> tuple[ast.Module, list[tuple[int, str]]]:
    """Type bare ``except:`` handlers as ``except Exception:``.

    Returns ``(tree, repairs)`` where ``repairs`` is a list of
    ``(lineno, description)`` tuples -- empty when nothing was rewritten,
    so the function is idempotent on clean input. ExceptHandler nodes
    whose ``type`` is already an ``ast.Name`` (typed) or ``ast.Tuple``
    (multi-typed) are left untouched.
    """
    repairs: list[tuple[int, str]] = []

    class _Typer(ast.NodeTransformer):

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> Any:
            self.generic_visit(node)
            if node.type is None:
                node.type = ast.Name(id='Exception', ctx=ast.Load())
                lineno = getattr(node, 'lineno', 0)
                repairs.append((lineno, 'typed bare except as Exception'))
            return node
    tree = _Typer().visit(tree)
    if repairs:
        ast.fix_missing_locations(tree)
    return (tree, repairs)
if len(_FIX_CLASSES) == 1:
    _FIX_CLASSES.extend([{'name': 'subprocess_check_kwarg', 'matches_rule': _matches_subprocess_check, 'repair': _add_subprocess_check_kwarg}, {'name': 'os_system_to_subprocess', 'matches_rule': _matches_os_system, 'repair': _rewrite_os_system_to_subprocess}, {'name': 'bare_except_typed', 'matches_rule': _matches_bare_except, 'repair': _typed_bare_except}])
"G19: loud-fail multi-file dispatch reject in get_next_task.\n\nAdds a validator block in ``get_next_task`` that rejects any task whose\n``files_touched`` list has length > 1 BEFORE the ``.json.processing``\nrename. Rejected tasks are moved to\n``processed/<task_id>.rejected_multi_file_unsupported.json`` (NOT a\n``.archived-*`` suffix, so a corrected re-stage can land), a\n``logger.error`` row is emitted, and a ``scope_violation`` ledger row is\nappended to ``state_dir/impl_progress.jsonl`` with\n``reason='multi_file_dispatch_unsupported_pre_G19a'``. Closes the\nsilent-drop class surfaced by G18bc dual-file dispatch.\n\nThe AST merge keys on ``FunctionDef`` names, so this submission only\nneeds to carry the modified ``get_next_task`` function. All other\ntop-level nodes (``_emit_lifecycle``, ``_clear_stale_submissions``,\n``check_true_depth``, ``_auto_commit_accepted``) are left untouched on\nthe target side -- their signatures stay byte-identical.\n"

def _parse_manifest(code: str) -> dict[str, str] | None:
    """Detect and parse a ``__JANUSMASK_MANIFEST__`` multi-file submission.

    Returns a ``dict[str, str]`` mapping rel-paths -> file source when *code*
    parses to a top-level ``Assign`` whose single ``ast.Name`` target is
    ``__JANUSMASK_MANIFEST__`` and whose value is an ``ast.Dict`` with all
    keys and values being ``ast.Constant`` strings. Returns ``None`` on:

    - ``SyntaxError`` from ``ast.parse``;
    - no matching ``Assign`` node anywhere in the module body (covers
      "missing", "wrong target name", "non-Name target", "multi-target
      Assign", "tuple unpacking", "augmented assign");
    - matching ``Assign`` whose value is not an ``ast.Dict``;
    - matching ``Assign`` whose dict contains any non-string-Constant key
      or value (e.g. int, bytes, expression, None).

    G19a-1 helper; consumed by ``_validate_submission`` (per-entry AST
    validation) and ``_save_final_output`` (sidecar emission).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if target.id != '__JANUSMASK_MANIFEST__':
            continue
        if not isinstance(node.value, ast.Dict):
            return None
        result: dict[str, str] = {}
        for k, v in zip(node.value.keys, node.value.values):
            if not isinstance(k, ast.Constant) or not isinstance(k.value, str):
                return None
            if not isinstance(v, ast.Constant) or not isinstance(v.value, str):
                return None
            result[k.value] = v.value
        return result
    return None
"G19a-1: __JANUSMASK_MANIFEST__ submission channel for harness/orchestrator.py.\n\nMinimal claude submission. The orchestrator's AST merge keys top-level\nFunctionDefs by name: ``prepare_task_prompt``, ``_validate_submission``, and\n``_save_final_output`` wholesale-replace their HEAD 751c96d counterparts; the\nnew helper ``_parse_manifest`` lands as a fresh node and is placed by the G17\nforward-reference reorder (its only caller is ``_validate_submission`` /\n``_save_final_output``, so any ordering Python accepts is fine -- name\nresolution is deferred to call time for FunctionDef bodies).\n"
'G19b: relax orchestrator multi-file dispatch gate; add sidecar sanity check.\n\nWhole-file submission for AST-merge. Only the two FunctionDefs below are\nreplaced by name in harness/orchestrator.py:\n\n* ``get_next_task`` -- drops the G19 ``.rejected_multi_file_unsupported.json``\n  block (former lines 571-584). Depth-check now flows directly into the\n  ``.json.processing`` rename. Single-file, empty-list, and missing-key cases\n  are unchanged; multi-file tasks now claim normally.\n* ``_auto_commit_accepted`` -- adds a sanity check that emits a\n  ``multi_file_missing_sidecar`` ledger row + warning when\n  ``len(files_touched) > 1`` AND ``state/output/<task_id>.files.json`` is\n  absent. Block lives after the ``isinstance(target_rel, str)`` guard and\n  before the ``.py`` short-circuit; the rest of the function is byte-identical.\n'

def _compute_target_baseline_violations(rel: str, declared_signature: str | None) -> set[tuple[str, str]]:
    """Return the set of (rule, message) pairs already present in the target file.

    Reads the target source at ``pathlib.Path(rel)`` and runs ``validate_code``
    against it with ``allow_nondeterminism=False`` (so EVERY pre-existing
    violation surfaces in the baseline, regardless of the dispatch's
    ``allow_nondet`` resolution). The caller uses the returned set to filter
    submission-side violations whose (rule, message) tuple was already present
    in the target -- those are pre-existing, not introduced by the agent.

    Returns an empty set on every failure mode so a malformed target file
    never crashes the validator nor masks new violations:

    * ``rel`` is not a string;
    * ``rel`` does not end with ``.py`` (manifest entries for non-py targets,
      handled by ``_parse_manifest`` / files_touched short-circuit upstream);
    * the path does not point to a regular file (target file does not yet
      exist -- a task creating a new .py file legitimately has an empty
      baseline);
    * ``OSError`` on read (permission, vanished mid-call);
    * ``validate_code`` raises (SyntaxError-on-parse or anything else).

    Line numbers are intentionally NOT part of the key: the agent may add
    imports / reorder helpers, shifting every downstream line. (rule, message)
    is line-agnostic and matches even under line drift.
    """
    if not isinstance(rel, str) or not rel.endswith('.py'):
        return set()
    path = Path(rel)
    if not path.is_file():
        return set()
    try:
        target_src = path.read_text(encoding='utf-8')
    except OSError:
        return set()
    try:
        baseline = validate_code(target_src, allow_nondeterminism=False, declared_signature=declared_signature)
    except Exception:
        return set()
    return {(v.rule, v.message) for v in baseline}
"G12-principled: target-aware baseline diffing for _validate_submission.\n\nReplaces the G12v2 mtt-allowlist band-aid in harness/orchestrator.py with\nprincipled per-target baseline diffing. The new module-level helper\n``_compute_target_baseline_violations`` reads the on-disk target file at\n``files_touched[0]`` (or each manifest rel-path), runs ``validate_code`` on\nthe pre-existing source to compute the set of (rule, message) pairs that\nwere already present, and ``_validate_submission`` filters those out of the\nsubmission's own violations before the errors/warnings partition.\n\nAST merge keys top-level FunctionDefs by name: ``_validate_submission`` is\nwholesale-replaced; ``_compute_target_baseline_violations`` lands as a new\nnode. All other top-level nodes (logger binding, imports, helpers like\n``_load_declared_signature`` / ``_parse_manifest``, etc.) are left untouched\non the target side. No new top-level imports are introduced -- ``Path`` and\n``validate_code`` already live at module top.\n\nThe G12v2 mtt-allowlist + constraints.deterministic + test_* carve-outs are\nretained verbatim as defense-in-depth (especially the test_* path, which\nlegitimately introduces brand-new nondeterminism via uuid4/time fixtures).\n"
_INBOX_SOURCES_BY_MODE: dict[str, tuple[str, tuple[str, ...]]] = {'synthesis': ('task.json', ('tasks/current_task.json',)), 'planning': ('brief.json', ('planning/brief.json', '../../brief.json')), 'reconciliation': ('diff_summary.json', ('planning/current_diff.json',))}

def _stage_inbox(work_dir: Path, mode: str, state_dir: str) -> None:
    """Copy the canonical state-dir source for ``mode`` into work_dir/inbox/.

    Creates ``work_dir/inbox`` (mkdir parents=True, exist_ok=True) and,
    if ``mode`` appears in ``_INBOX_SOURCES_BY_MODE``, tries each
    candidate rel-path under ``state_dir`` in declaration order. The
    first that resolves to an existing regular file is
    ``shutil.copy2``'d to ``inbox/<inbox_name>`` (the filename Gemini's
    SessionStart hook expects from
    ``harness.hooks._env._INBOX_EXPECTATIONS[mode]``).

    Failure modes -- mkdir OSError, ``Path.resolve`` raising
    ``OSError`` or ``RuntimeError`` (symlink loop), source not present
    at any candidate, ``shutil.copy2`` OSError -- all surface as
    ``logger.warning`` records and the function returns without
    raising. The inbox/ directory is still created even when staging
    cannot proceed so the SessionStart hook's existence check stays
    meaningful.

    GH1 (2026-05-18) -- Report 01 H2 smoking gun: prior to this helper,
    ``spawn_agent`` only created ``<work_dir>/outbox`` and never
    populated ``<work_dir>/inbox/<expected-name>``, causing every
    Gemini planning + reconciliation spawn to abort at
    ``harness/hooks/gemini/session_start.py:182-197`` with
    ``"Inbox not staged for mode=..."``.
    """
    inbox = work_dir / 'inbox'
    try:
        inbox.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning('inbox mkdir failed for %s: %s', inbox, exc)
        return
    mapping = _INBOX_SOURCES_BY_MODE.get(mode)
    if mapping is None:
        return
    inbox_name, candidate_rels = mapping
    if mode == 'synthesis':
        task_id_env = os.environ.get('JANUSMASK_TASK_ID')
        if task_id_env:
            candidate_rels = (f'tasks/current_task_{task_id_env}.json',) + candidate_rels
    state_path = Path(state_dir)
    for rel in candidate_rels:
        try:
            src = (state_path / rel).resolve()
        except (OSError, RuntimeError):
            continue
        if not src.is_file():
            continue
        try:
            shutil.copy2(src, inbox / inbox_name)
        except OSError as exc:
            logger.warning('inbox stage failed src=%s dst=%s: %s', src, inbox / inbox_name, exc)
            return
        logger.info('staged inbox: %s -> %s', src, inbox / inbox_name)
        if mode == 'synthesis':
            _stage_targets(inbox, state_path, inbox / inbox_name)
        return

def _stage_targets(inbox: Path, state_path: Path, task_json: Path) -> None:
    """Copy each resolved files_touched target into ``inbox/targets/<rel>``.

    Best-effort and non-raising: reads the just-staged task.json, resolves
    files_touched (walking the parent chain for decomposed child tasks), and
    copies each existing target file from the repo (``state_dir.parent``) into
    ``inbox/targets/<rel>`` as read context. Missing targets (brand-new files)
    are simply skipped — the agent then authors them from scratch.

    For ``test_authoring`` tasks carrying a non-empty ``mutation_target``, the
    module-under-test is also staged so the oracle-authoring worker gets the
    module's real interface rather than only the brief's prose.
    """
    try:
        task = json.loads(task_json.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError, ValueError):
        return
    if not isinstance(task, dict):
        return
    task_id = task.get('task_id') or os.environ.get('JANUSMASK_TASK_ID', '')
    try:
        touched = _resolve_files_touched(state_path, task, task_id)
    except Exception:
        touched = task.get('files_touched') or []
    rels = list(touched)
    meta_task_type = task.get('meta_task_type') or (task.get('constraints') or {}).get('meta_task_type')
    mt = task.get('mutation_target')
    if meta_task_type == 'test_authoring' and isinstance(mt, str) and mt:
        rel = mt.replace('.', '/') + '.py'
        if rel not in rels:
            rels.append(rel)
    repo_root = state_path.resolve().parent
    targets_root = inbox / 'targets'
    for rel in rels:
        if not isinstance(rel, str) or not rel:
            continue
        try:
            src = (repo_root / rel).resolve()
            src.relative_to(repo_root)
        except (OSError, RuntimeError, ValueError):
            continue
        if not src.is_file():
            continue
        dst = targets_root / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        except OSError as exc:
            logger.warning('inbox target stage failed src=%s dst=%s: %s', src, dst, exc)
            continue
        logger.info('staged inbox target: %s -> %s', src, dst)
"GH1: Stage <work_dir>/inbox/<mode-file> in spawn_agent so Gemini's\nSessionStart hook stops denying every planning + reconciliation spawn.\n\nPure-additive, single-file harness self-fix targeting Report 01 H2.\n\nAdds two module-level entities to ``harness/orchestrator.py``:\n\n* ``_INBOX_SOURCES_BY_MODE``: maps each JANUSMASK_MODE the orchestrator\n  spawns to ``(inbox_filename, candidate_state_dir_relpaths)``. Synthesis\n  copies ``tasks/current_task.json`` -> ``inbox/task.json``; planning\n  copies ``planning/brief.json`` (master layout) or ``../../brief.json``\n  (per-agent layout via ``master/planning/sessions/<agent>``) ->\n  ``inbox/brief.json``; reconciliation copies\n  ``planning/current_diff.json`` (matching reconciliation.py:126's\n  per-agent write site) -> ``inbox/diff_summary.json``. The inbox_name\n  side of each tuple is exactly the filename Gemini's session-start hook\n  expects from ``harness.hooks._env._INBOX_EXPECTATIONS`` (asserted by\n  Subtest 7).\n\n* ``_stage_inbox(work_dir, mode, state_dir)``: creates\n  ``work_dir/inbox`` (parents=True, exist_ok=True), looks up the mode's\n  source candidates, and ``shutil.copy2``'s the first existing file into\n  ``inbox/<inbox_name>``. Failures at every layer -- mkdir OSError,\n  Path.resolve OSError/RuntimeError, copy OSError -- are caught and\n  surface as ``logger.warning`` records; the function never raises so a\n  staging failure cannot regress the orchestrator's terminal state.\n\n``spawn_agent`` is wholesale-replaced (AST merge keys top-level\nFunctionDef by name) to add exactly one new call:\n``_stage_inbox(Path(env['JANUSMASK_WORK_DIR']), env['JANUSMASK_MODE'],\nstate_dir)`` between ``outbox_path.mkdir`` and the prompt\n``.replace(...)`` line. Public signature\n``(agent, prompt, config, round_number=1) -> subprocess.Popen`` is\nbyte-identical.\n\nNo source file outside ``harness/orchestrator.py`` is modified. No new\ntop-level imports: ``shutil`` (line 9), ``pathlib.Path`` (line 14), and\n``logger`` (line 37) are already bound in the target module.\n"
'G19a-3: Harden the __JANUSMASK_MANIFEST__ prompt block.\n\nSingle-file harness self-fix. Replaces only the MULTI-FILE manifest\nprompt block inside ``prepare_task_prompt``: adds an explicit\nVERBATIM-file-content rule, a concrete docstring-bearing example, and\na DO NOT enumeration of common error modes. Surrounding code (base\nprompt, files_touched extraction, guard, files_repr, spec_summary\ntail, return) is byte-identical with the pre-fix file.\n'
'G19a-4: prepare_task_prompt manifest block uses raw triple-single-quote.\n\nReverses the G19a-3 anti-raw-triple-single-quote rule. Recommends raw-triple-single-quote raw\ntriple-single-quote wrapping for ``__JANUSMASK_MANIFEST__`` values so\nbackslash escape sequences in the embedded file source survive verbatim\nwithout the agent having to double-escape. Single-file change to\nharness/orchestrator.py; this submission carries only ``prepare_task_prompt``\nfor AST-merge by ``meta_task_type=harness_self_fix``.\n'
'AW3: serialize git commit critical section in _auto_commit_accepted.\n\nWraps the call to ``git_integration.commit_accepted_output`` in an\n``fcntl.flock(LOCK_EX)`` over ``state/control/autowork/git_commit.lock``\nso concurrent orchestrator_worker processes (spawned by the autowork\ndaemon, Task 2) can never race git add/commit/rev-parse against each\nother. Also defends against operator-driven META commits that race\nwith an in-flight auto_commit.\n\nPattern mirrors ``harness/state.py:locked_read_modify_write`` lines\n139-146 (open lock file in \'a\' mode, flock LOCK_EX, try/finally,\nLOCK_UN on release). Lock is held only around the commit critical\nsection -- verification subprocess and rollback paths run unlocked\nper the brief\'s explicit directive ("Do NOT lock around the\nverification_command subprocess that runs INSIDE _auto_commit_accepted\nafter the commit lands").\n\nSingle-file dispatch; AST merger adds ``import fcntl`` to top-level\nimports and replaces ``_auto_commit_accepted`` by name.\n'
import fcntl
from harness.ast_enforcer import Violation
"G28 patch: add manifest_missing violation to _validate_submission.\n\nSingle-file submission on a task whose ``files_touched`` declares > 1\nfile silently passed AST validation, then hit\n``multi_file_missing_sidecar`` at commit time and committed only\n``files_touched[0]`` -- after which V2 rollback fired when the\nverification_command failed on the missing files. Witnessed: G25 v1\n(de45e9a, rolled back) and AW5a v1 (c05c8f7, reverted as a405562).\n\nThe fix: between the manifest-present branch and the single-file\nfallback, detect ``manifest is None AND len(files_touched) > 1`` and\nreturn ``(False, [Violation(rule='manifest_missing', ...)])``. The\nexisting AST-retry loop then surfaces the message in the retry prompt,\nforcing the agent to resubmit as a ``__JANUSMASK_MANIFEST__`` dict.\n"
'ROLLBACK_WORKTREE_CHECKOUT: add `git checkout HEAD -- <target_rel>` after both\n`git reset --hard HEAD~1` sites in :func:`_auto_commit_accepted`.\n\nRationale: `git reset --hard HEAD~1` reverts the commit but a follow-up\n`git checkout HEAD -- <target_rel>` guarantees the specific file is restored\nfrom HEAD even if the reset left the file in a stale state (e.g. partial\nindex entries from a concurrent operator commit, or a worktree where the\ntarget was modified after the auto-commit but before the rollback path\nfired).  Both checkout calls are wrapped in try/except for\n`subprocess.TimeoutExpired`, `FileNotFoundError`, and `OSError` with\n`logger.error` on failure -- consistent with the existing rollback-reset\nexception handling so the rollback path remains best-effort and never\nraises.\n'
"ROLLBACK_WORKTREE_CHECKOUT: add git checkout HEAD -- <target_rel> after both reset sites.\n\nWhole-file submission for AST-merge. The merger keys on FunctionDef name,\nso only ``_auto_commit_accepted`` is replaced on the target side; all\nother top-level nodes (imports, ``_emit_lifecycle``, ``get_next_task``,\n``_resolve_files_touched``, etc.) remain byte-identical.\n\nDefense-in-depth: ``git reset --hard HEAD~1`` rewinds the index and the\ncommitted tree to the pre-commit state, but if a stray edit lingers in\nthe working tree (e.g. an editor write between commit and reset, or a\nfilesystem race), the working copy of ``target_rel`` can drift from\nHEAD. A follow-up ``git checkout HEAD -- <target_rel>`` restores the\nworking-copy file to match HEAD, guaranteeing the next dispatch sees a\nclean baseline. The checkout is best-effort -- failures are logged at\nERROR level (matching the reset's own failure branch) and do not change\nthe function's return value.\n"
'ROLLBACK_COMPLETENESS submission for harness/orchestrator.py:_auto_commit_accepted.\n\nWhole-file AST-merge submission: the orchestrator merges by FunctionDef name, so\nonly ``_auto_commit_accepted`` is replaced; all other top-level nodes in\n``harness/orchestrator.py`` stay byte-identical.\n\nCloses the staged-worktree-drift leak: when\n``git_integration.commit_accepted_output`` writes the merged file(s) to disk and\n``git add``-stages them, but a later git step (e.g. ``git commit`` racing an\noperator ``index.lock``) raises CalledProcessError/TimeoutExpired/OSError, the\nreturned error is a generic exception string (NOT a ``no_diff:`` string). The\nprior err branch only handled ``no_diff:`` and otherwise just logged + returned\nFalse, leaving on-disk merged content AND staged index entries that corrupt the\nnext dispatch (dirty AST-merge base, scoped-commit ride-along, polluted git\nstatus). This adds a defensive best-effort, non-destructive per-target scrub\n(``git reset -q`` + ``git checkout HEAD``) over the resolved ``files_touched``\nlist. The scrub never raises and the branch still returns False.\n\nThe module-level imports below mirror the names the merged function references so\nthis file is itself importable; they are NOT merged into the orchestrator (which\nalready has them in scope).\n'

def _claude_backend(config: dict) -> str:
    """Return the configured claude worker backend (``workers.claude_backend``).

    Reads ``config['workers']['claude_backend']`` and returns it as a string.
    Defaults to ``'headless'`` when the ``workers`` table or the
    ``claude_backend`` key is missing/None, treating absence as the safe
    default so the current (headless) behavior is preserved unless the operator
    explicitly opts in.
    """
    workers = config.get('workers') or {}
    backend = workers.get('claude_backend')
    if backend is None:
        return 'headless'
    return str(backend)

def _use_tmux_claude(agent: str, config: dict) -> bool:
    """Return True only for the claude worker on the tmux backend.

    True iff ``_claude_backend(config) == 'tmux'`` AND ``agent`` is the claude
    worker; False otherwise -- covering the headless backend, any unrecognized
    backend string, and any non-claude agent.
    """
    return _claude_backend(config) == 'tmux' and agent == 'claude'
"Minimal single-symbol submission for AST-merge into harness/orchestrator.py.\n\nOnly _path_b_outbox_fallback is replaced (merge keys by name; all other symbols in\nthe target survive). Adds a Path() coercion so the PTY backend's str _work_dir does\nnot raise TypeError on `str / 'outbox'` (the live silent-agy-fallback bug). Path,\njson, ast, logger are already module-level in orchestrator.py.\n"
if __name__ == '__main__':
    main()