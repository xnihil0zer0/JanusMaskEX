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
    """Build the inner ``claude`` stream-json argv (pre-jail)."""
    backend = conversation.get('agent_backend')
    model = conversation.get('model')
    argv: List[str] = ['claude', '--output-format', 'stream-json', '--include-partial-messages']
    if model is not None and backend != 'agy':
        argv += ['--model', str(model)]
    allow = resolve_tool_allowlist(conversation.get('current_mode'))
    argv += ['--tools', ' '.join(allow)]
    session_id = conversation.get('claude_session_id')
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
    for line in lines:
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(event, dict):
            continue
        stream_parser.handle_event(event)
        if _is_init_event(event):
            sid = event.get('session_id')
            if sid is not None:
                turn.session_id = sid
            continue
        etype = event.get('type')
        if etype == 'content_block_delta':
            delta = event.get('delta') or {}
            if delta.get('type') == 'text_delta':
                chunk = delta.get('text', '')
                turn.text += chunk
                if sink is not None:
                    sink(chunk)
            continue
        if etype == 'content_block_start':
            block = event.get('content_block') or {}
            if block.get('type') == 'tool_use':
                turn.tool_uses.append(block)
            continue
    return turn