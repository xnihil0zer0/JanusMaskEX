"""BeforeTool hook for the Gemini worker (P3 / HOOK-32).

Gemini twin of ``harness.hooks.claude.pre_tool``. The shape of the
matrix is identical — deny anything outside a minimal allowlist,
dispatch ``write_file``/``replace`` to the same rpc verbs Claude uses,
rate-limit via the shared ledger. The Gemini-specific deltas:

  * Tool names are the Gemini set (``write_file``, ``replace``,
    ``read_file``, ``read_many_files``, ``glob``, ``grep_search``,
    ``list_directory``, ``run_shell_command``).
  * ``replace`` is a substring substitution on an existing file —
    the hook must reconstruct the post-write bytes and AST-validate
    them (sub-plan 03 §5 row 3). Otherwise the bad syntax can be
    smuggled across the old_string/new_string boundary.
  * ``run_shell_command`` has no Claude analogue; hard-coded
    allow-list of ``pytest``/``python3 -m pytest``/sandbox invocation
    shapes.
  * Admin-policy tier-5 denies (``google_web_search``, ``web_fetch``,
    ``write_todos``, ``save_memory``, ``cli_help``) run before the
    hook at the policy layer; this hook denies them again as
    defence-in-depth so a policy regression doesn't open a silent
    hole.
  * Output envelope uses ``{decision, reason, hookSpecificOutput?}``;
    clarification path rewrites ``tool_input`` via
    ``hookSpecificOutput.tool_input``.

Write-dispatch deciders (submission/plan_draft/reconciliation/
error_report) and the read-like gate live in
``harness.hooks._decide_common``; this module wraps them with the
Gemini-specific ``_journal`` (tool parameter threaded) and
``_allow_with_tool_input`` envelope builder. ``_decide_clarification``
stays local because its allow envelope is ``hookSpecificOutput``
-wrapped rather than the Claude flat shape.
"""
from __future__ import annotations
import pathlib
import re
import sys
from typing import Any, TextIO
from harness.safe_subpath import is_safe_subpath
from .. import _common, _decide_common, _ledger, _paths, _state_gates
from ..rpc import clarification as rpc_clarification
from . import _env
from harness import hooks_equivalence
_HOOK_NAME = 'BeforeTool'
ALLOWED_TOOLS: frozenset[str] = frozenset({'write_file', 'replace', 'read_file', 'read_many_files', 'glob', 'grep_search', 'list_directory', 'run_shell_command', 'update_topic'})
_READ_LIKE: frozenset[str] = frozenset({'read_file', 'read_many_files', 'glob', 'grep_search', 'list_directory'})
# AGENT-ISOLATION §3.3: DEFAULT POSITION — drop the write verbs
# (tee/cp/mv/ln/cat<<EOF/chmod/rm) and arbitrary-code verbs (python -c,
# python harness/sandbox.py). Agents submit ONLY via the write_file -> outbox
# path (gated by _decide_write_or_replace); they do not need shell
# file-redirection. NOTE: pytest / python -m pytest REMAIN and ARE arbitrary
# code (conftest/plugins auto-import at collection) — this list is NOT the
# code-exec barrier; containment rests on CWD-outside-repo (§3.1/§3.2) + the
# §1b apply-path gate, not on this allowlist. (Also note: for bare `agy` this
# gate never loads today, so this hardening is defense-for-the-future / for
# the hook-loading agents, per §5.)
_SHELL_ALLOW = [re.compile('^pytest(\\s|$)'), re.compile('^python3?\\s+-m\\s+pytest(\\s|$)'), re.compile('^mkdir(\\s|$)'), re.compile('^touch(\\s|$)')]

def _read_allowed_roots(session_id: str | None) -> list[pathlib.Path]:
    project = _paths.project_dir()
    return [_env.work_dir(session_id), _paths.state_dir(), project / 'docs', project / 'briefs']

def _relpath_in_outbox(file_path: str, session_id: str | None) -> str | None:
    outbox = _env.outbox_dir(session_id).resolve()
    if not is_safe_subpath(file_path, str(outbox)):
        return None
    try:
        return pathlib.Path(file_path).resolve().relative_to(outbox).as_posix()
    except ValueError:
        return None

def _allowed_for_mode(rel: str, mode: str) -> bool:
    if rel == 'error.md':
        return True
    if rel.startswith('scratch/'):
        return True
    if mode == 'synthesis':
        if rel == 'submission.py':
            return True
        return rel.startswith('clarification_') and rel.endswith('.md')
    if mode == 'planning':
        return rel == 'plan_draft.json'
    if mode == 'reconciliation':
        return rel == 'reconciliation.json'
    return False

def _journal(session_id: str, agent: str, verb: str, outcome: str, *, tool: str, round_number: int, phase: str, detail: dict[str, Any] | None=None) -> None:
    _ledger.append_hook_event(session_id, agent, verb, outcome, hook=_HOOK_NAME, tool=tool, round_number=round_number, phase=phase, detail=detail or {})

def _allow_with_tool_input(tool_input: dict[str, Any] | None=None, *, warnings: list[dict[str, Any]] | None=None, additional_context: str='') -> dict[str, Any]:
    payload: dict[str, Any] = {'decision': 'allow'}
    hso: dict[str, Any] = {'hookEventName': _HOOK_NAME}
    if tool_input is not None:
        hso['tool_input'] = tool_input
    ctx = additional_context
    if warnings:
        bullets = '\n'.join((f'- L{w['line']}: [{w['rule']}] {w['message']}' for w in warnings))
        ctx = (ctx + '\n\n' if ctx else '') + f'AST warnings (non-blocking):\n{bullets}'
    if ctx:
        payload['systemMessage'] = ctx
    if len(hso) > 1:
        payload['hookSpecificOutput'] = hso
    return payload

def _build_decider_ctx(session_id: str, agent: str, phase: str, round_number: int, tool: str) -> _decide_common.DeciderContext:

    def _journal_closure(verb: str, outcome: str, *, detail: dict[str, Any] | None=None) -> None:
        _journal(session_id, agent, verb, outcome, tool=tool, round_number=round_number, phase=phase, detail=detail)

    def _allow_with_warnings_closure(warnings: list[dict[str, Any]]) -> dict[str, Any]:
        return _allow_with_tool_input(warnings=warnings)
    return _decide_common.DeciderContext(session_id=session_id, agent=agent, phase=phase, round_number=round_number, journal=_journal_closure, allow_with_warnings=_allow_with_warnings_closure)

def _decide_submission(content: str, events: list[dict[str, Any]], session_id: str, agent: str, phase: str, round_number: int, tool: str) -> dict[str, Any]:
    return _decide_common.decide_submission(_build_decider_ctx(session_id, agent, phase, round_number, tool), content, events, _env.inbox_dir(session_id))

def _decide_plan_draft(content: str, events: list[dict[str, Any]], session_id: str, agent: str, phase: str, round_number: int, tool: str) -> dict[str, Any]:
    return _decide_common.decide_plan_draft(_build_decider_ctx(session_id, agent, phase, round_number, tool), content, events)

def _decide_reconciliation(content: str, events: list[dict[str, Any]], session_id: str, agent: str, phase: str, round_number: int, tool: str) -> dict[str, Any]:
    return _decide_common.decide_reconciliation(_build_decider_ctx(session_id, agent, phase, round_number, tool), content, events)

def _decide_clarification(tool_input: dict[str, Any], events: list[dict[str, Any]], session_id: str, agent: str, phase: str, round_number: int, tool: str) -> dict[str, Any]:
    used = _ledger.count_verb(events, 'clarification', outcome='allow')
    next_slot = used + 1
    if next_slot > rpc_clarification.MAX_CLARIFICATIONS:
        reason = f'Clarification rate limit reached ({used}/{rpc_clarification.MAX_CLARIFICATIONS}).'
        _journal(session_id, agent, 'clarification', 'rate_limited', tool=tool, round_number=round_number, phase=phase, detail={'reason': reason, 'counters': {'clarifications': used}})
        return _common.decision_payload('deny', reason=reason)
    outbox = _env.outbox_dir(session_id)
    rewritten = dict(tool_input)
    rewritten['file_path'] = str(outbox / f'clarification_{next_slot}.md')
    return _allow_with_tool_input(tool_input=rewritten)

def _decide_error_report(content: str, session_id: str, agent: str, phase: str, round_number: int, tool: str) -> dict[str, Any]:
    return _decide_common.decide_error_report(_build_decider_ctx(session_id, agent, phase, round_number, tool), content)

def _decide_read_like(tool_input: dict[str, Any], session_id: str) -> dict[str, Any]:
    return _decide_common.decide_read_like(tool_input, _read_allowed_roots(session_id), path_keys=('absolute_path', 'file_path', 'path'), tool_name_for_reason='read_file/list_directory/grep_search/glob')

def _decide_shell(tool_input: dict[str, Any], session_id: str | None=None) -> dict[str, Any]:
    command = str(tool_input.get('command') or '').strip()
    if not command:
        return _common.decision_payload('deny', reason='run_shell_command requires a non-empty command.')
    bare_cat = _CAT_BARE_RE.match(command)
    if bare_cat:
        args = bare_cat.group(1).strip()
        if args.startswith('-'):
            return _common.decision_payload('deny', reason=f'cat flags are not permitted; got {command!r}.')
        if not args or args == '-':
            return _common.decision_payload('deny', reason=f'cat stdin/empty form not permitted; got {command!r}.')
        for path_arg in args.split():
            if not _is_in_read_allowed_roots(path_arg, session_id):
                return _common.decision_payload('deny', reason=f'cat path {path_arg!r} is outside the read-allowed roots (work_dir, state_dir, docs, briefs).')
        return _common.decision_payload('allow')
    for pat in _SHELL_ALLOW:
        if pat.match(command):
            return _common.decision_payload('allow')
    return _common.decision_payload('deny', reason=f'Shell command not in allow-list: {command!r}. Allowed prefixes: pytest, python3 -m pytest, mkdir, touch (plus read-only cat restricted to the read-allowed roots).')

def _reconstruct_replace(target_path: str, old_string: str, new_string: str) -> str:
    try:
        existing = pathlib.Path(target_path).read_text(encoding='utf-8')
    except (FileNotFoundError, OSError):
        existing = ''
    return existing.replace(old_string, new_string, 1)

def _decide_write_or_replace(tool_name: str, tool_input: dict[str, Any], session_id: str, agent: str, mode: str, phase: str, round_number: int) -> dict[str, Any]:
    file_path = str(tool_input.get('file_path') or tool_input.get('path') or '')
    if not file_path:
        return _common.decision_payload('deny', reason=f'{tool_name} requires a file_path.')
    outbox = _env.outbox_dir(session_id)
    rel = _relpath_in_outbox(file_path, session_id)
    if rel is None:
        return _common.decision_payload('deny', reason=f'{tool_name} must target {outbox}/; got {file_path}.')
    if not _allowed_for_mode(rel, mode):
        return _common.decision_payload('deny', reason=f'Write to {rel!r} not permitted in mode={mode!r}. Mode-specific outbox contract: synthesis→submission.py|clarification_N.md|error.md, planning→plan_draft.json|error.md, reconciliation→reconciliation.json|error.md.')
    if tool_name == 'write_file':
        content = tool_input.get('content')
        if not isinstance(content, str):
            content = ''
    else:
        content = _reconstruct_replace(file_path, str(tool_input.get('old_string', '')), str(tool_input.get('new_string', '')))
    events = _ledger.read_events(session_id, agent)
    if rel == 'submission.py':
        return _decide_submission(content, events, session_id, agent, phase, round_number, tool_name)
    if rel == 'plan_draft.json':
        return _decide_plan_draft(content, events, session_id, agent, phase, round_number, tool_name)
    if rel == 'reconciliation.json':
        return _decide_reconciliation(content, events, session_id, agent, phase, round_number, tool_name)
    if rel.startswith('clarification_') and rel.endswith('.md'):
        return _decide_clarification(tool_input, events, session_id, agent, phase, round_number, tool_name)
    if rel == 'error.md':
        return _decide_error_report(content, session_id, agent, phase, round_number, tool_name)
    return _common.decision_payload('deny', reason=f'Write path not in outbox contract: {rel}. Allowed: submission.py, plan_draft.json, reconciliation.json, clarification_N.md, error.md.')

def main(stdin: TextIO | None=None, stdout: TextIO | None=None) -> int:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    try:
        payload = _common.read_input(stdin)
    except _common.HookInputError as exc:
        _common.write_decision(_common.decision_payload('deny', reason=f'Malformed hook stdin: {exc}'), stdout)
        return 0
    tool_name = str(payload.get('tool_name') or '')
    tool_input_raw = payload.get('tool_input')
    tool_input = tool_input_raw if isinstance(tool_input_raw, dict) else {}
    session_id = str(payload.get('session_id') or '')
    agent = _paths.agent() or 'gemini'
    mode = _paths.mode()
    state = _state_gates.read_state_besteffort()
    round_number = _state_gates.current_round(state)
    phase = _state_gates.current_phase(state) or mode
    if tool_input_raw is not None and (not isinstance(tool_input_raw, dict)):
        sys.stderr.write(f'{_HOOK_NAME} tool_input_coerce: non-dict {type(tool_input_raw).__name__} coerced to {{}} for tool={tool_name!r}\n')
        _ledger.append_hook_event(session_id, agent, 'tool_input_coerce', 'invalid', hook=_HOOK_NAME, tool=tool_name, round_number=round_number, phase=phase, detail={'reason': 'non_dict_tool_input', 'type': type(tool_input_raw).__name__})
    if tool_name not in ALLOWED_TOOLS:
        decision_payload = _common.decision_payload('deny', reason=f'Tool {tool_name!r} is disallowed for the Gemini worker. Allowed tools: {sorted(ALLOWED_TOOLS)}.')
    elif tool_name == 'update_topic':
        decision_payload = _common.decision_payload('allow')
    elif tool_name in _READ_LIKE:
        decision_payload = _decide_read_like(tool_input, session_id)
    elif tool_name == 'run_shell_command':
        decision_payload = _decide_shell(tool_input, session_id)
    else:
        decision_payload = _decide_write_or_replace(tool_name, tool_input, session_id, agent, mode, phase, round_number)
    hooks_equivalence.maybe_record_shadow(session_id=session_id or None, tool_name=tool_name, tool_input=tool_input, payload=decision_payload)
    _common.write_decision(decision_payload, stdout)
    return 0
_CAT_BARE_RE = re.compile('^cat\\s+(?!<<)(.+)$')

def _is_in_read_allowed_roots(file_path: str, session_id: str | None) -> bool:
    for root in _read_allowed_roots(session_id):
        try:
            if is_safe_subpath(file_path, str(root)):
                return True
        except (OSError, ValueError):
            continue
    return False
if __name__ == '__main__':
    raise SystemExit(main())