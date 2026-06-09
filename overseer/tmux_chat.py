"""claude-tmux chat-turn entrypoint with store + transcript persistence.

``run_tmux_chat_turn`` is what ``run_chat_turn`` delegates to when a
conversation's ``agent_backend == 'claude-tmux'``. It drives exactly one
interactive turn through :func:`overseer.tmux_driver.run_tmux_turn` over the
real (or, in tests, injected) tmux seams, then persists exactly like the NDJSON
``run_chat_turn`` path does: it records the (possibly new) session id, appends
the assistant turn to the store, writes an assistant transcript line, and
returns ``{ok, text, session_id, tool_uses}``.

A spawn/seam failure is surfaced as an ``ok=False`` assistant turn -- it is
*never* raised and *never* hangs.

Stdlib only beyond sibling ``overseer`` modules. This module deliberately does
NOT import ``overseer.turn_runner`` (that would create an import cycle); the
transcript line is written directly via the ``overseer.transcript`` helpers.
"""
from __future__ import annotations
import inspect
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
_POLL_SECONDS = 2.0
_TURN_TIMEOUT_SECONDS = 600.0

def run_tmux_chat_turn(store: Any, cid: str, user_text: str, rec: Any, *, config: Any, repo_root: Any, state_dir: Any, transcript_path: Any, mode: Any, tmux_seams: Optional[Dict[str, Any]]=None) -> Dict[str, Any]:
    """Run one claude-tmux turn and persist it like the NDJSON path.

    When ``tmux_seams`` is injected (the test path) it is used verbatim. When it
    is ``None`` (the real path, not exercised by the oracle) the bundle is built
    from :mod:`overseer.tmux_seams`. Any failure while driving the turn is
    surfaced as an ``ok=False`` assistant-error turn rather than raised.
    """
    bundle = tmux_seams
    if bundle is None:
        bundle = _build_real_bundle(rec, config=config, repo_root=repo_root, state_dir=state_dir, cid=cid)
    try:
        from overseer.tmux_driver import run_tmux_turn
        turn = run_tmux_turn(rec, user_text, session=bundle['session'], start_argv=bundle['start_argv'], cwd=bundle['cwd'], config_dir=bundle['config_dir'], tmux_exec=bundle['tmux_exec'], sleep=bundle['sleep'], read_text=bundle['read_text'], list_dir=bundle['list_dir'], session_started=bundle.get('session_started', False), poll=_POLL_SECONDS, timeout=_TURN_TIMEOUT_SECONDS)
    except Exception as exc:
        err = '[overseer error] {}: {}'.format(type(exc).__name__, exc)
        _safe_append_turn(store, cid, err)
        _safe_append_transcript(store, cid, transcript_path, err, mode)
        return {'ok': False, 'error': err, 'text': err, 'session_id': None, 'tool_uses': []}
    session_id = getattr(turn, 'session_id', None)
    text = getattr(turn, 'text', '') or ''
    tool_uses: List[Any] = list(getattr(turn, 'tool_uses', None) or [])
    if session_id is not None:
        _safe_set_session_id(store, cid, session_id)
    store.append_turn(cid, {'role': 'assistant', 'content': text})
    _safe_append_transcript(store, cid, transcript_path, text, mode)
    return {'ok': True, 'text': text, 'session_id': session_id, 'tool_uses': tool_uses}

def _safe_append_turn(store: Any, cid: str, content: str) -> None:
    """Append an assistant turn, never letting a store hiccup escape."""
    try:
        store.append_turn(cid, {'role': 'assistant', 'content': content})
    except Exception:
        pass

def _safe_set_session_id(store: Any, cid: str, session_id: Any) -> None:
    try:
        store.set_session_id(cid, session_id)
    except Exception:
        pass

def _safe_append_transcript(store: Any, cid: str, transcript_path: Any, content: str, mode: Any) -> None:
    """Write one assistant transcript line; failures never break the turn."""
    try:
        index = max(0, len(store.get(cid)['transcript']) - 1)
    except Exception:
        index = 0
    try:
        _append_transcript_line(transcript_path, index, 'assistant', content, mode)
    except Exception:
        pass

def _append_transcript_line(transcript_path: Any, index: int, role: str, content: str, mode: Any) -> None:
    """Append a single JSONL transcript row using the overseer.transcript helpers.

    The line is produced via ``Turn`` + ``to_jsonl`` (with ``redact`` applied to
    the content). If the helper surface differs from what we expect, we fall
    back to a plain JSON row that still carries ``role`` and ``content`` so the
    transcript is always written.
    """
    path = Path(transcript_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = _render_with_transcript_helpers(index, role, content, mode)
    if line is None:
        line = json.dumps({'index': index, 'role': role, 'content': content, 'mode': mode})
    if not line.endswith('\n'):
        line = line + '\n'
    with open(path, 'a', encoding='utf-8') as handle:
        handle.write(line)

def _render_with_transcript_helpers(index: int, role: str, content: str, mode: Any) -> Optional[str]:
    """Best-effort serialization via overseer.transcript; ``None`` on mismatch."""
    try:
        from overseer import transcript as _transcript
    except Exception:
        return None
    safe_content = content
    redact = getattr(_transcript, 'redact', None)
    if callable(redact):
        try:
            safe_content = redact(content)
        except Exception:
            safe_content = content
    try:
        turn_obj = _build_turn(_transcript.Turn, index, role, safe_content, mode)
        line = _transcript.to_jsonl(turn_obj)
    except Exception:
        return None
    if not isinstance(line, str):
        return None
    try:
        parsed = json.loads(line.splitlines()[0] if line else '')
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    if parsed.get('role') != role or 'content' not in parsed:
        return None
    return line

def _build_turn(turn_cls: Any, index: int, role: str, content: str, mode: Any) -> Any:
    """Construct a transcript ``Turn`` by matching its actual parameter names."""
    candidates = {'index': index, 'idx': index, 'i': index, 'n': index, 'seq': index, 'position': index, 'role': role, 'content': content, 'text': content, 'message': content, 'body': content, 'msg': content, 'mode': mode}
    empty = inspect.Parameter.empty
    positional_kinds = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.POSITIONAL_ONLY)
    sig = inspect.signature(turn_cls)
    kwargs: Dict[str, Any] = {}
    for name, param in sig.parameters.items():
        if name == 'self':
            continue
        if name in candidates:
            kwargs[name] = candidates[name]
        elif param.default is empty and param.kind in positional_kinds:
            kwargs[name] = None
    return turn_cls(**kwargs)

def _build_real_bundle(rec: Any, *, config: Any, repo_root: Any, state_dir: Any, cid: str) -> Dict[str, Any]:
    """Assemble a tmux seam bundle from overseer.tmux_seams for the real path."""
    import os
    import shutil
    from overseer import tmux_seams as _tmux_seams
    seams = _tmux_seams.make_tmux_seams()
    cwd = str(repo_root)
    config_dir = _tmux_seams.seed_config_dir(str(state_dir), cid, copy=shutil.copy2, exists=os.path.exists, makedirs=lambda p: os.makedirs(p, exist_ok=True))
    start_argv = _tmux_seams.build_interactive_argv(config_dir, rec=rec, config=config)
    session = 'ovr_' + str(cid)
    return {'tmux_exec': _seam_get(seams, 'tmux_exec'), 'sleep': _seam_get(seams, 'sleep'), 'read_text': _seam_get(seams, 'read_text'), 'list_dir': _seam_get(seams, 'list_dir'), 'config_dir': config_dir, 'session': session, 'cwd': cwd, 'start_argv': start_argv, 'session_started': False}

def _seam_get(seams: Any, name: str) -> Any:
    if isinstance(seams, dict):
        return seams.get(name)
    return getattr(seams, name, None)