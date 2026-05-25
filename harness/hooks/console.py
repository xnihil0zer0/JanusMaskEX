"""ConsoleStreamer — rich, formatted agent-activity output to stderr.

Extracted from harness/mcp_server.py (HOOK-12). Shared by both the legacy
MCP path and the new Claude/Gemini hook paths so that console output stays
byte-for-byte identical across the migration.

Public surface (imported as `harness.hooks.console`):
    ANSI palette class  :  _C
    Low-level helpers   :  _agent_color, _agent_label, _divider,
                           _code_preview, _stream
    ConsoleStreamer     :  per-session formatter used by MCP + hooks

Every symbol is imported by harness/mcp_server.py; keep names and signatures
stable. Changes here must be mirrored in the MCP server's on_* call-sites.
"""
from __future__ import annotations
import json
import sys

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
    CODE = '\x1b[38;5;183m'
    HEADER = '\x1b[38;5;117m'
    MUTED = '\x1b[38;5;240m'

def _agent_color(agent_id: str) -> str:
    return _C.CLAUDE if agent_id == 'claude' else _C.GEMINI

def _agent_label(agent_id: str) -> str:
    color = _agent_color(agent_id)
    return f'{color}{_C.BOLD}{agent_id.upper()}{_C.RESET}'

def _divider(agent_id: str, char: str='─', width: int=60) -> str:
    color = _agent_color(agent_id)
    return f'{color}{char * width}{_C.RESET}'

def _code_preview(code: str, max_lines: int=12) -> str:
    MUTED = '\x1b[38;5;240m'
    CODE = '\x1b[38;5;183m'
    RESET = '\x1b[0m'
    DIM = '\x1b[2m'
    lines = code.rstrip().split('\n')
    truncated = len(lines) > max_lines
    display = lines[:max_lines]
    parts = []
    for i, line in enumerate(display, 1):
        parts.append(f'  {MUTED}{i:3d}{RESET} {CODE}{line}{RESET}')
    if truncated:
        parts.append(f'  {DIM}... ({len(lines) - max_lines} more lines){RESET}')
    return '\n'.join(parts)

def _stream(msg: str) -> None:
    raise NotImplementedError

class ConsoleStreamer:
    """Streams formatted agent activity to the operator console (stderr).

    Each agent type (claude/gemini) gets color-coded output showing
    task retrieval, code submissions, validation results, feedback,
    errors, and clarification requests in real time.
    """

    def __init__(self, agent_id: str, session_id: str):
        raise NotImplementedError

    def on_connect(self) -> None:
        raise NotImplementedError

    def on_task_read(self, task: dict) -> None:
        raise NotImplementedError

    def on_submit_accepted(self, code: str, submission_num: int, max_subs: int, round_number: int, warnings: list) -> None:
        raise NotImplementedError

    def on_submit_rejected(self, code: str, violations: list) -> None:
        raise NotImplementedError

    def on_submit_rate_limited(self, max_subs: int) -> None:
        raise NotImplementedError

    def on_clarification(self, question: str, num: int, remaining: int) -> None:
        raise NotImplementedError

    def on_error_report(self, error_msg: str) -> None:
        raise NotImplementedError

    def on_feedback_retrieved(self, feedback: dict) -> None:
        raise NotImplementedError

    def on_feedback_unavailable(self, reason: str) -> None:
        raise NotImplementedError

    def on_input(self, msg: dict) -> None:
        raise NotImplementedError

    def on_output(self, msg: dict) -> None:
        raise NotImplementedError

    def on_disconnect(self) -> None:
        raise NotImplementedError
__all__ = ['_C', '_agent_color', '_agent_label', '_divider', '_code_preview', '_stream', 'ConsoleStreamer']