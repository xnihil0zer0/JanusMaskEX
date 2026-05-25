"""Per-verb decider core shared by the Claude + Gemini pre-tool hooks.

Both ``harness/hooks/claude/pre_tool.py`` and
``harness/hooks/gemini/pre_tool.py`` used to carry near-byte-identical
copies of the write-dispatch decider bodies (_decide_submission,
_decide_plan_draft, _decide_reconciliation, _decide_error_report plus
_decide_read_like). They diverged only on:

  1. Gemini threads a ``tool: str`` through every ledger journal call;
     Claude hard-codes ``tool="Write"``.
  2. The happy-path allow envelope (Claude: ``additionalContext`` via
     ``_allow_with_warning_context``; Gemini: ``systemMessage`` via
     ``_allow_with_tool_input``).
  3. For _decide_read_like, the path-field priority list (Gemini
     checks ``absolute_path`` first; Claude does not) and the
     deny-reason tool-name citation.

This module extracts the four write-dispatch deciders and
decide_read_like as pure-logic functions parameterised by a
``DeciderContext`` (carrying the ``journal`` and ``allow_with_warnings``
callables the caller prepares) or, for read_like, by explicit
path_keys + tool_name_for_reason arguments.

``_decide_clarification`` is intentionally NOT extracted here: Claude
returns a flat ``{"decision": "allow", "tool_input": ...}`` via
``_common.decision_payload``; Gemini wraps ``tool_input`` inside
``hookSpecificOutput`` via ``_allow_with_tool_input``. That envelope
difference is load-bearing for the Gemini BeforeTool contract and does
not reduce cleanly to a callable parameter on DeciderContext.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Any
from typing import Callable
from harness.safe_subpath import is_safe_subpath
from . import _common
from . import _ledger
from . import _paths
from . import _state_gates
from .rpc import submit_code as rpc_submit_code
from .rpc import submit_plan_draft as rpc_submit_plan_draft
from .rpc import submit_reconciliation as rpc_submit_reconciliation
MAX_VIOLATIONS = 50
ERROR_MAX_BYTES = 64 * 1024

@dataclass(frozen=True)
class DeciderContext:
    """Per-call context for a write-dispatch decider.

    ``journal`` is called as ``journal(verb, outcome, detail=dict|None)``
    and is responsible for threading session_id/agent/round/phase and
    (on Gemini) the tool kwarg into ``_ledger.append_hook_event``.

    ``allow_with_warnings`` is called with ``list[dict]`` of AST
    warnings and returns the agent-specific allow envelope (Claude
    attaches ``additionalContext``; Gemini attaches ``systemMessage``
    under ``hookSpecificOutput``).
    """
    session_id: str
    agent: str
    phase: str
    round_number: int
    journal: Callable[..., None]
    allow_with_warnings: Callable[[list[dict[str, Any]]], dict[str, Any]]

def format_ast_reason(payload: dict[str, Any]) -> str:
    raise NotImplementedError

def format_plan_reason(payload: dict[str, Any]) -> str:
    """Renders a human-readable validation summary from a plan_draft rejection payload:

        header = payload.get('error', 'plan_draft validation failed.')
        bullets = ['- [{code}] {path}: {message}' for each v in payload['violations']]
        return header + ('
' + '
'.join(bullets) if bullets else '')
    """
    header = payload.get('error')
    if header is None:
        header = 'plan_draft validation failed.'
    violations = payload.get('violations')
    if not violations:
        return header
    bullets = []
    for v in violations:
        code = v.get('code', '')
        path = v.get('path', '')
        message = v.get('message', '')
        bullets.append(f'- [{code}] {path}: {message}')
    return header + '\n' + '\n'.join(bullets)

def decide_submission(ctx: 'DeciderContext', content: str, events: list[dict[str, Any]], inbox_dir: Any) -> dict[str, Any]:
    raise NotImplementedError

def decide_plan_draft(ctx: DeciderContext, content: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    raise NotImplementedError

def decide_reconciliation(ctx: DeciderContext, content: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    raise NotImplementedError

def decide_error_report(ctx: DeciderContext, content: str) -> dict[str, Any]:
    raise NotImplementedError

def decide_read_like(tool_input: dict[str, Any], allowed_roots: list[Any], *, path_keys: tuple[str, ...], tool_name_for_reason: str) -> dict[str, Any]:
    raise NotImplementedError
import sys
import types
try:
    import harness.hooks.rpc as _rpc
except ImportError:
    _rpc = types.ModuleType('harness.hooks.rpc')
    sys.modules['harness.hooks.rpc'] = _rpc
for _name in ('submit_code', 'submit_plan_draft', 'submit_reconciliation'):
    if not hasattr(_rpc, _name):
        setattr(_rpc, _name, lambda *a, **k: None)