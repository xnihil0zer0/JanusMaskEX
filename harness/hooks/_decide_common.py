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
    header = payload.get('error') or payload.get('message') or 'AST validation failed.'
    violations = payload.get('violations') or []
    lines = [header]
    for v in violations:
        lines.append(f'- L{v['line']}: [{v['rule']}] {v['message']}')
    return '\n'.join(lines)

def format_plan_reason(payload: dict[str, Any]) -> str:
    header = payload.get('error', 'plan_draft validation failed.')
    bullets = [f'- [{v['code']}] {v['path']}: {v['message']}' for v in payload.get('violations', [])]
    return header + ('\n' + '\n'.join(bullets) if bullets else '')

def decide_submission(ctx: 'DeciderContext', content: str, events: list[dict[str, Any]], inbox_dir: Any) -> dict[str, Any]:
    used = _ledger.count_verb(events, 'submit_code', outcome='allow')
    if used >= _state_gates.MAX_SUBMISSIONS:
        reason = f'Submission rate limit reached ({used}/{_state_gates.MAX_SUBMISSIONS}).'
        ctx.journal('submit_code', 'rate_limited', detail={'reason': reason, 'counters': {'submissions': used}})
        return _common.decision_payload('deny', reason=reason)
    task = _paths.load_inbox_task(inbox_dir)
    files_touched = task.get('files_touched') or []
    if not files_touched:
        target_is_py = True
    elif not isinstance(files_touched[0], str):
        target_is_py = True
    else:
        target_is_py = files_touched[0].endswith('.py')
    if not target_is_py:
        task_id = str(task.get('task_id') or '')
        ctx.journal('submit_code', 'allow', detail={'reason': 'non-py target', 'task_id': task_id})
        return _common.decision_payload('allow')
    allow_nondet = task.get('constraints', {}).get('deterministic') is False
    if not allow_nondet:
        mtt = task.get('meta_task_type') or task.get('constraints', {}).get('meta_task_type')
        if mtt in {'io_adapter', 'logging_observability'} or (mtt or '').startswith('test_'):
            allow_nondet = True
    synthesis_target_type = str(task.get('synthesis_target_type', '') or '')
    task_id = str(task.get('task_id') or '')
    # REV22 §4-3 (CR-1): external targets (working_dir resolves OUTSIDE the
    # JanusMask tree) relax eval/exec/__import__ at submit-time. Fail-safe to
    # self: absent/None working_dir => _target_is_self True => relax False.
    from harness.paths import _target_is_self
    relax_external = not _target_is_self(task.get('working_dir'))
    violations = rpc_submit_code.validate(content, allow_nondeterminism=allow_nondet, relax_external_constructs=relax_external)
    errors = [v for v in violations if getattr(v, 'severity', '') == 'error']
    if errors:
        payload = rpc_submit_code.rejected_payload(errors, max_show=MAX_VIOLATIONS)
        ctx.journal('submit_code', 'deny', detail={'error_count': len(errors), 'truncated': len(errors) > MAX_VIOLATIONS, 'task_id': task_id})
        rpc_submit_code.emit_ast_rejection(agent=ctx.agent, task_id=task_id, synthesis_target_type=synthesis_target_type, state_dir=_paths.state_dir())
        return _common.decision_payload('deny', reason=format_ast_reason(payload))
    warnings = rpc_submit_code.warnings_from_violations(violations)
    if warnings:
        return ctx.allow_with_warnings(warnings)
    return _common.decision_payload('allow')

def decide_plan_draft(ctx: DeciderContext, content: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    if _ledger.has_verb(events, 'plan_draft', outcome='allow'):
        reason = 'plan_draft already submitted (single-shot per round).'
        ctx.journal('plan_draft', 'deny', detail={'reason': reason})
        return _common.decision_payload('deny', reason=reason)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        reason = f'plan_draft content must be valid JSON: {exc}'
        ctx.journal('plan_draft', 'invalid', detail={'reason': reason})
        return _common.decision_payload('deny', reason=reason)
    violations = rpc_submit_plan_draft.validate(parsed)
    if violations:
        payload = rpc_submit_plan_draft.rejected_payload(violations, max_show=MAX_VIOLATIONS)
        ctx.journal('plan_draft', 'deny', detail={'violation_count': len(violations)})
        return _common.decision_payload('deny', reason=format_plan_reason(payload))
    return _common.decision_payload('allow')

def decide_reconciliation(ctx: DeciderContext, content: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    if _ledger.has_verb(events, 'reconciliation', outcome='allow'):
        reason = 'reconciliation already submitted (single-shot per round).'
        ctx.journal('reconciliation', 'deny', detail={'reason': reason})
        return _common.decision_payload('deny', reason=reason)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        reason = f'reconciliation content must be valid JSON: {exc}'
        ctx.journal('reconciliation', 'invalid', detail={'reason': reason})
        return _common.decision_payload('deny', reason=reason)
    valid_ids = rpc_submit_reconciliation.load_valid_diff_ids(_paths.state_dir())
    err = rpc_submit_reconciliation.validate_responses(parsed.get('responses', []), valid_ids=valid_ids)
    if err:
        ctx.journal('reconciliation', 'deny', detail={'reason': err})
        return _common.decision_payload('deny', reason=err)
    return _common.decision_payload('allow')

def decide_error_report(ctx: DeciderContext, content: str) -> dict[str, Any]:
    size = len(content.encode('utf-8'))
    if size > ERROR_MAX_BYTES:
        reason = f'error.md exceeds 64 KB cap ({size} bytes > {ERROR_MAX_BYTES}).'
        ctx.journal('error', 'deny', detail={'size': size})
        return _common.decision_payload('deny', reason=reason)
    return _common.decision_payload('allow')

def decide_read_like(tool_input: dict[str, Any], allowed_roots: list[Any], *, path_keys: tuple[str, ...], tool_name_for_reason: str) -> dict[str, Any]:
    file_path = ''
    for key in path_keys:
        val = tool_input.get(key)
        if val:
            file_path = str(val)
            break
    if not file_path:
        return _common.decision_payload('allow')
    if any((is_safe_subpath(file_path, str(r)) for r in allowed_roots)):
        return _common.decision_payload('allow')
    return _common.decision_payload('deny', reason=f'{tool_name_for_reason} path outside allowed roots: {file_path}. Allowed roots: JANUSMASK_WORK_DIR, $STATE_DIR, project docs/, project briefs/.')