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
    raise NotImplementedError

def _normalise_decision(decision: str) -> str:
    raise NotImplementedError

def decision_payload(decision: str, *, reason: str='', additional_context: str='', tool_input: dict | None=None) -> dict[str, Any]:
    """Build a neutral decision envelope.

    Event-specific hookSpecificOutput shapes are built by the `claude/` and
    `gemini/` entrypoints; this helper stays decision-only so both sides can
    wrap it.
    """
    raise NotImplementedError

def write_decision(payload: dict[str, Any], stream=None) -> None:
    raise NotImplementedError