"""Bridge that actually RUNS an overseer chat turn.

This is the integration layer between the web API (which only records turns) and
``overseer.driver.run_turn`` (which is a deterministic shell around four injected
seams but is otherwise never wired to anything). It supplies the real seams --
a subprocess ``runner`` that spawns the vendored ``claude`` binary, an
``env_builder`` mirroring the harness agent-env allowlist, a ``jail_builder``
reusing ``harness.agent_jail.build_jail_argv`` when the sandbox is enabled, and
``harness.agent_streamer.ClaudeStreamParser`` as the stream parser -- folds the
agent's stream-json output into an assistant turn, persists it to the injected
:class:`overseer.session_store.SessionStore`, and appends both the user and
assistant turns to ``logs/overseer_chat.jsonl`` in the canonical
``overseer.transcript.Turn`` JSONL shape so the WebUI SSE tailer streams them
live.

The heavy entrypoint ``run_chat_turn`` accepts an optional ``seams`` override so
the deterministic store/transcript bookkeeping is unit-testable without spawning
a real agent. With no override it builds the real seams.

Imports: stdlib + sibling overseer modules + the two reused harness seams
(``agent_jail``, ``agent_streamer``). No network/model call happens here unless
the real ``runner`` actually spawns the agent.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from overseer.driver import run_turn, AssistantTurn
from overseer.transcript import Turn, to_jsonl, redact

DEFAULT_TIMEOUT_SEC = 600

# Mirror harness.orchestrator._build_agent_env's SEC_ENV_ALLOWLIST so the jailed
# overseer agent inherits exactly the execution-essential + vendor-auth vars and
# NOT the operator's host secrets.
_ENV_ALLOW_EXACT = frozenset((
    'PATH', 'HOME', 'LANG', 'LANGUAGE', 'LC_ALL', 'TERM', 'SHELL',
    'USER', 'LOGNAME', 'TZ', 'TMPDIR', 'PWD',
    'DBUS_SESSION_BUS_ADDRESS', 'GOOGLE_GENAI_USE_GCA',
    'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE',
    'NODE_EXTRA_CA_CERTS', 'CURL_CA_BUNDLE',
    'NO_PROXY', 'no_proxy', 'HTTP_PROXY', 'http_proxy',
    'HTTPS_PROXY', 'https_proxy',
))
_ENV_ALLOW_PREFIXES = (
    'JANUSMASK_', 'XDG_', 'NVM_', 'NODE_', 'GEMINI_', 'GOOGLE_',
    'ANTHROPIC_', 'CLAUDE_', 'LC_',
)


def _resolve_claude_binary(config: Dict[str, Any], repo_root: Path) -> str:
    """Resolve the real ``claude`` executable the driver's argv refers to by name.

    Prefers ``config['agents']['claude']['command']`` (the vendored path, with
    ``${PROJECT_ROOT}`` expanded), falling back to ``shutil.which('claude')`` and
    finally the bare name (so the jail's PATH can resolve it).
    """
    cmd = ((config or {}).get('agents', {}) or {}).get('claude', {}) or {}
    command = cmd.get('command')
    if command:
        command = str(command).replace('${PROJECT_ROOT}', str(repo_root))
        if Path(command).exists():
            return command
    import shutil
    return shutil.which('claude') or 'claude'


def _overseer_work_dir(repo_root: Path, cid: str) -> Path:
    """A per-conversation work dir OUTSIDE the repo (mirrors agent_work_dir)."""
    safe = ''.join(ch if (ch.isalnum() or ch in '-_') else '_' for ch in str(cid))
    root = repo_root.parent / f'{repo_root.name}_agentwork' / 'overseer'
    return root / safe


def _build_overseer_env(repo_root: Path, work_dir: Path, state_dir: Path) -> Dict[str, str]:
    """Build the jailed agent environment (allowlisted; secrets scrubbed)."""
    base = {
        k: v for k, v in os.environ.items()
        if k in _ENV_ALLOW_EXACT or any(k.startswith(p) for p in _ENV_ALLOW_PREFIXES)
    }
    existing_pp = os.environ.get('PYTHONPATH', '')
    pythonpath = str(repo_root) if not existing_pp else str(repo_root) + os.pathsep + existing_pp
    base.update({
        'PYTHONHASHSEED': '0',
        'CLAUDE_PROJECT_DIR': str(work_dir),
        'JANUSMASK_PROJECT_DIR': str(repo_root),
        'PYTHONPATH': pythonpath,
        'JANUSMASK_AGENT': 'overseer',
        'JANUSMASK_STATE_DIR': str(state_dir),
        'JANUSMASK_MODE': 'overseer',
        'JANUSMASK_WORK_DIR': str(work_dir),
    })
    return base


def make_seams(*, config: Dict[str, Any], repo_root: Path, state_dir: Path,
               work_dir: Path, timeout: int = DEFAULT_TIMEOUT_SEC
               ) -> Tuple[Callable, Callable, Callable, Any]:
    """Construct the four real seams for ``overseer.driver.run_turn``."""
    from harness import agent_jail
    from harness.agent_streamer import ClaudeStreamParser

    claude_bin = _resolve_claude_binary(config, repo_root)

    def jail_builder(argv: Sequence[str], **kw: Any) -> List[str]:
        inner = list(argv)
        if inner and inner[0] == 'claude':
            inner[0] = claude_bin
        if agent_jail.sandbox_enabled(config) and agent_jail.bwrap_available():
            return agent_jail.build_jail_argv(
                inner, repo_root=repo_root, work_dir=work_dir, state_dir=state_dir,
                bind_credentials=True,
            )
        return inner

    def env_builder(conversation: Dict[str, Any], **kw: Any) -> Dict[str, str]:
        return _build_overseer_env(repo_root, work_dir, state_dir)

    def runner(cmd: Sequence[str], *, env: Dict[str, str], stdin: str, **kw: Any) -> List[str]:
        work_dir.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(
            list(cmd), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=env, start_new_session=True,
            cwd=str(work_dir),
        )
        try:
            out, _err = proc.communicate(input=stdin, timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _err = proc.communicate()
        return (out or '').splitlines()

    return runner, env_builder, jail_builder, ClaudeStreamParser('claude')


def _append_transcript(path: Optional[Path], index: int, role: str, mode: str, content: str) -> None:
    """Append one ``Turn`` JSONL line (secret-redacted) to the tailed log."""
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    line = to_jsonl(Turn(index=index, role=role, mode=mode, content=redact(content)))
    with path.open('a', encoding='utf-8') as fh:
        fh.write(line + '\n')
        fh.flush()
        os.fsync(fh.fileno())


def run_chat_turn(store: Any, cid: str, user_text: str, *, config: Dict[str, Any],
                  repo_root: Path, state_dir: Path, logs_dir: Path,
                  rewind_to_index: Optional[int] = None,
                  timeout: int = DEFAULT_TIMEOUT_SEC,
                  seams: Optional[Tuple[Callable, Callable, Callable, Any]] = None,
                  gate_runner: Optional[Callable] = None,
                  ) -> Dict[str, Any]:
    """Run one assistant turn for *cid* and persist it.

    The user turn is assumed ALREADY recorded in *store* (by the web API). This
    writes the user line to ``logs/overseer_chat.jsonl``, drives the agent via
    ``run_turn`` (real seams unless *seams* is injected), persists the resulting
    session id + assistant turn to *store*, appends the assistant line to the
    transcript log, and returns ``{ok, text, session_id, tool_uses}``. A spawn
    failure is caught and surfaced as an ``ok=False`` assistant turn rather than
    raising, so the UI shows the error instead of hanging.

    Additively, when *cid*'s ``current_mode`` is bound to a procedure in
    ``overseer.procedure.PROCEDURE_REGISTRY`` the turn first runs a procedure
    step: it loads the conversation's :class:`ProcedureState`, runs the current
    phase's gate via the INJECTED *gate_runner* seam, advances the phase via the
    reducer (next phase / Blocked / Complete), persists the new state, and
    threads the active phase + next action + last-gate result into *rec* so they
    surface in the agent's system prompt every turn. Modes with no bound
    procedure (e.g. ``observe``) are untouched -- no state file, no rec keys.
    """
    repo_root = Path(repo_root)
    state_dir = Path(state_dir)
    transcript_path = Path(logs_dir) / 'overseer_chat.jsonl'
    rec = store.get(cid)
    mode = rec.get('current_mode', 'observe')

    # --- additive per-turn procedure wiring ----------------------------------
    # Resolve the procedure substrate lazily + import-safely. For a mode with no
    # bound procedure this whole block is a no-op (existing behaviour preserved).
    try:
        from overseer import procedure as _procedure
        from overseer import procedure_state as _procedure_state
        _registry = getattr(_procedure, 'PROCEDURE_REGISTRY', {}) or {}
    except Exception:
        _procedure = None
        _procedure_state = None
        _registry = {}

    if _procedure is not None and _procedure_state is not None and mode in _registry:
        proc = _registry[mode]
        st = _procedure_state.load_state(cid, state_dir=state_dir)
        phase = st.phase or (proc.phases[0].name if proc.phases else '')
        if gate_runner is not None:
            gr = gate_runner(mode, phase, rec, state_dir)
            dec = _procedure.advance(proc, phase, gr)
            if isinstance(dec, str):
                new = _procedure_state.ProcedureState(phase=dec, last_gate=gr)
            elif dec is _procedure.Complete:
                new = _procedure_state.ProcedureState(phase='COMPLETE', last_gate=gr)
            else:  # Blocked(reason, fix_hint) -- hold the phase, record the gate
                new = _procedure_state.ProcedureState(phase=phase, last_gate=gr)
            _procedure_state.save_state(cid, new, state_dir=state_dir)
            st = new
        # Thread phase guidance into the rec BEFORE run_turn so the computed next
        # action and last-gate result surface in the per-turn system prompt.
        rec['procedure_phase'] = st.phase
        next_action = ''
        for _ph in proc.phases:
            if _ph.name == st.phase:
                next_action = getattr(_ph, 'next_action', '') or ''
                break
        rec['procedure_next_action'] = next_action
        rec['procedure_last_gate'] = (
            {'ok': st.last_gate.ok, 'reason': st.last_gate.reason,
             'fix_hint': st.last_gate.fix_hint}
            if st.last_gate is not None else None
        )

    transcript = rec.get('transcript') or []
    user_index = max(len(transcript) - 1, 0)
    _append_transcript(transcript_path, user_index, 'user', mode, user_text)

    if seams is None:
        work_dir = _overseer_work_dir(repo_root, cid)
        seams = make_seams(config=config, repo_root=repo_root, state_dir=state_dir,
                           work_dir=work_dir, timeout=timeout)
    runner, env_builder, jail_builder, stream_parser = seams

    try:
        turn: AssistantTurn = run_turn(
            rec, user_text, runner=runner, env_builder=env_builder,
            jail_builder=jail_builder, stream_parser=stream_parser,
            rewind_to_index=rewind_to_index,
        )
    except Exception as exc:  # surface, never hang the UI
        err = '[overseer error] %s: %s' % (type(exc).__name__, exc)
        store.append_turn(cid, {'role': 'assistant', 'content': err})
        new_index = len(store.get(cid).get('transcript') or []) - 1
        _append_transcript(transcript_path, max(new_index, 0), 'assistant', mode, err)
        return {'ok': False, 'error': err, 'text': err, 'session_id': None, 'tool_uses': []}

    if turn.session_id is not None:
        store.set_session_id(cid, turn.session_id)
    store.append_turn(cid, {'role': 'assistant', 'content': turn.text})
    asst_index = len(store.get(cid).get('transcript') or []) - 1
    _append_transcript(transcript_path, max(asst_index, 0), 'assistant', mode, turn.text)
    return {'ok': True, 'text': turn.text, 'session_id': turn.session_id,
            'tool_uses': list(turn.tool_uses)}
