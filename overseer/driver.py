"""Deterministic per-turn driver for the overseer interactive loop.

``run_turn`` is a thin, deterministic shell around four injected seams:

    runner        -- the ONLY process path; called exactly once and returns a
                     list of stream-json NDJSON line strings.
    env_builder   -- builds the process environment mapping.
    jail_builder  -- wraps the built claude argv (sandbox/jail).
    stream_parser -- receives every decoded stream event for side-channels.

The driver builds the ``claude`` stream-json argv (``--output-format
stream-json``, ``--include-partial-messages``, ``--model``, ``--tools`` with the
mode allowlist, ``--resume`` to append and ``--fork-session`` to branch a
rewind), wraps it via ``jail_builder``, spawns it via ``runner`` feeding
``user_text`` on stdin, and folds the returned NDJSON stream into an
``AssistantTurn`` (new session id + accumulated text + tool-use blocks). It
never spawns a real process, makes a model/API call, opens an SSE channel, or
touches the network -- all I/O flows through the injected seams.

Only stdlib plus sibling ``overseer`` modules are imported.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence
from overseer.mode_gate import resolve_tool_allowlist
try:
    from overseer import model_select as _model_select
except Exception:
    _model_select = None

@dataclass
class AssistantTurn:
    """The result of a single assistant turn.

    Attributes:
        session_id: the (possibly new) claude session id from the init event.
        text: assistant text accumulated verbatim from ``text_delta`` deltas.
        tool_uses: ordered list of ``tool_use`` content blocks (each a dict
            exposing at least a ``name``).
    """
    session_id: Optional[str] = None
    text: str = ''
    tool_uses: List[Dict[str, Any]] = field(default_factory=list)

def _is_init_event(event: Dict[str, Any]) -> bool:
    """True for a stream-json init event in either claude or agy shape."""
    etype = event.get('type')
    if etype == 'init':
        return True
    return etype == 'system' and event.get('subtype') == 'init'

def _build_argv(conversation: Dict[str, Any], rewind_to_index: Optional[int]) -> List[str]:
    """Build the inner ``claude`` stream-json argv (pre-jail).

    Mirrors the harness's canonical headless claude spawn for the CLAUDE
    backend (``-p``, ``--verbose``, real comma-joined tool names mapped from the
    mode allowlist, ``--permission-mode acceptEdits`` and the per-mode system
    prompt via ``--append-system-prompt``). The ``agy`` backend keeps its
    minimal prompt-on-stdin shape with no model/permission/tools knobs.
    """
    backend = conversation.get('agent_backend')
    session_id = conversation.get('claude_session_id')

    # --- agy backend: minimal shape, prompt flows on stdin in run_turn ---
    if backend == 'agy':
        argv: List[str] = ['claude', '-p', '--output-format', 'stream-json', '--include-partial-messages']
        if session_id:
            argv += ['--resume', str(session_id)]
        if rewind_to_index is not None:
            argv.append('--fork-session')
        return argv

    # --- claude backend: full headless print-mode invocation -------------
    argv = ['claude', '-p', '--output-format', 'stream-json', '--verbose', '--include-partial-messages']

    model = conversation.get('model')
    if model is not None:
        argv += ['--model', str(model)]

    argv += ['--permission-mode', 'acceptEdits']

    mode = conversation.get('current_mode') or 'observe'

    # Per-mode procedure context -> --append-system-prompt (best effort).
    try:
        from overseer.mode_prompts import render_mode_context
        rendered = render_mode_context(mode, conversation)
    except Exception:
        rendered = None
    if rendered:
        argv += ['--append-system-prompt', rendered]

    # Map abstract capability tokens to real claude tool names, order
    # preserving and de-duplicated; unmapped tokens are dropped.
    tool_name_map: Dict[str, str] = {
        'read': 'Read',
        'search': 'Grep',
        'list': 'Glob',
        'write': 'Write',
        'diff': 'Read',
        'drive-ui': 'Read',
        'push': 'Write',
    }

    def _to_real_tools(tokens: Sequence[str]) -> List[str]:
        seen: set = set()
        out: List[str] = []
        for token in tokens:
            real = tool_name_map.get(token)
            if real is None or real in seen:
                continue
            seen.add(real)
            out.append(real)
        return out

    mapped = _to_real_tools(resolve_tool_allowlist(mode))
    if mapped:
        argv += ['--tools', ','.join(mapped)]

    if session_id:
        argv += ['--resume', str(session_id)]
    if rewind_to_index is not None:
        argv.append('--fork-session')
    return argv

def run_turn(conversation: Dict[str, Any], user_text: str, *, runner: Callable[..., Sequence[str]], env_builder: Callable[..., Dict[str, str]], jail_builder: Callable[..., Sequence[str]], stream_parser: Any, **kw: Any) -> AssistantTurn:
    """Drive a single assistant turn deterministically through injected seams.

    Args:
        conversation: dict with ``claude_session_id``, ``current_mode``,
            ``model``, ``agent_backend`` and ``transcript``.
        user_text: the user input fed to the agent via stdin.
        runner: the sole process seam ``runner(argv, *, env, stdin, **kw)``
            returning a list of stream-json NDJSON line strings.
        env_builder: builds the process environment mapping.
        jail_builder: wraps the built argv (sandbox/jail).
        stream_parser: object with ``handle_event(event)`` receiving every
            decoded stream event.
        **kw: extra options threaded to the seams; ``rewind_to_index`` selects
            a fork/branch turn and ``sink`` (a callable) relays streamed deltas.

    Returns:
        An :class:`AssistantTurn` with the captured session id, accumulated
        text, and collected tool-use blocks.
    """
    rewind_to_index = kw.get('rewind_to_index')
    sink = kw.get('sink')
    argv = _build_argv(conversation, rewind_to_index)
    cmd = jail_builder(argv, **kw)
    env = env_builder(conversation, **kw)
    lines = runner(cmd, env=env, stdin=user_text, **kw)
    turn = AssistantTurn()

    # Three independent text sources, folded with precedence after the loop.
    deltas = ''
    result_text = ''
    assistant_text = ''

    for line in lines:
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(event, dict):
            continue

        # (1) Every decoded raw line reaches the parser FIRST, before any
        #     unwrapping, and the init/session-id capture branch is preserved.
        stream_parser.handle_event(event)
        if _is_init_event(event):
            sid = event.get('session_id')
            if sid is not None:
                turn.session_id = sid
            continue

        etype = event.get('type')

        # (2) Unwrap a ``stream_event`` envelope FIRST and re-read the inner
        #     type so the partial-message logic runs on the inner event. A
        #     malformed/empty envelope unwraps to {} and is skipped.
        if etype == 'stream_event':
            event = event.get('event') or {}
            etype = event.get('type')

        # (3) Inner content_block_delta text_delta -> accumulate + relay.
        if etype == 'content_block_delta':
            delta = event.get('delta') or {}
            if delta.get('type') == 'text_delta':
                chunk = delta.get('text', '')
                deltas += chunk
                if sink is not None:
                    sink(chunk)
            continue

        # (4) Inner content_block_start tool_use -> the SOLE tool source.
        if etype == 'content_block_start':
            block = event.get('content_block') or {}
            if block.get('type') == 'tool_use':
                turn.tool_uses.append(block)
            continue

        # (5) Complete assistant message: claude shape nests a list of blocks
        #     under ``message.content``; the agy shape is a bare top-level
        #     string under ``content``.
        if etype == 'assistant':
            message = event.get('message')
            if isinstance(message, dict):
                parts: List[str] = []
                for block in message.get('content') or []:
                    if isinstance(block, dict) and block.get('type') == 'text':
                        parts.append(block.get('text', ''))
                assistant_text = ''.join(parts)
            else:
                assistant_text = event.get('content') or ''
            continue

        # (6) Terminal result: authoritative answer + defensive session id,
        #     ignored when the turn errored.
        if etype == 'result':
            if not event.get('is_error'):
                result_text = event.get('result') or ''
                sid = event.get('session_id')
                if sid is not None:
                    turn.session_id = sid
            continue

    # Single source of truth: assistant > result > deltas. A later source that
    # is empty never blanks an earlier non-empty one.
    text = ''
    if deltas:
        text = deltas
    if result_text:
        text = result_text
    if assistant_text:
        text = assistant_text
    turn.text = text
    return turn
