"""Shared stdin/stdout hook envelope + unified decision vocabulary.

Both Claude Code and Gemini CLI fire hooks by spawning a short-lived process,
piping a JSON object on stdin and reading a JSON object on stdout. Claude uses
the `allow`/`block`/`ask` vocabulary; Gemini uses `allow`/`deny`/`block`/`ask`.
The harness normalises to `allow`/`deny` across both sides — any other token
raises.

Diagnostics always go to stderr. stdout carries exactly one JSON object
(the decision) so the hook runner can parse it without ambiguity.
"""
from __future__ import annotations
import json
import sys
from typing import Any
ALLOW = 'allow'
DENY = 'deny'
DECISIONS = frozenset({ALLOW, DENY})

class HookInputError(ValueError):
    """Raised when the stdin JSON envelope is malformed."""

def read_input(stream=None) -> dict[str, Any]:
    """Read and parse the hook envelope from stdin (or provided stream)."""
    stream = stream if stream is not None else sys.stdin
    raw = stream.read()
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f'hook stdin is not valid JSON: {exc}') from exc
    if not isinstance(data, dict):
        raise ValueError(f'hook stdin must be a JSON object, got {type(data).__name__}')
    return data

def _normalise_decision(decision: str) -> str:
    token = (decision or '').strip().lower()
    if token not in DECISIONS:
        raise ValueError(f'unknown decision {decision!r}; expected one of {sorted(DECISIONS)}')
    return token

def decision_payload(decision: str, *, reason: str='', additional_context: str='', tool_input: dict | None=None) -> dict[str, Any]:
    """Build a neutral decision envelope.

    Event-specific hookSpecificOutput shapes are built by the `claude/` and
    `gemini/` entrypoints; this helper stays decision-only so both sides can
    wrap it.
    """
    token = _normalise_decision(decision)
    payload: dict[str, Any] = {'decision': token}
    if reason:
        payload['reason'] = reason
    if additional_context:
        payload['additionalContext'] = additional_context
    if tool_input is not None:
        payload['tool_input'] = tool_input
    return payload

def write_decision(payload: dict[str, Any], stream=None) -> None:
    if stream is None:
        stream = sys.stdout
    stream.write(json.dumps(payload))
    stream.flush()