"""UserPromptSubmit hook for the Claude worker (P2 / HOOK-21).

Replaces the context-injection halves of three MCP verbs:
``cmd_get_task`` (synthesis), ``cmd_get_planning_brief`` (planning /
reconciliation), and ``cmd_get_feedback`` (cross_examination).

Fires on every user prompt arriving in Claude. Responsibilities
(sub-plan 02 §4.2 + sub-plan 04 §4 invariants 3 & 9):

  1. On the first prompt of a session (no ``task_read`` ledger row
     yet), read the mode-appropriate inbox file and inject its JSON
     body verbatim into ``additionalContext``. Append a ``task_read``
     marker so follow-up prompts don't re-inject. When the task body
     advertises ``files_touched``, also look up recent self-healing
     history records that overlap and append a formatted section so
     the worker can avoid repeating a known failing trajectory.
  2. If STATE.json.phase == ``cross_examination`` and inbox/
     feedback.json is present and has not been injected yet, inject it
     and record ``feedback_read``.
  3. Always append a locked-field reminder (agent/round/phase/remaining
     submission+clarification budget) so identity anchors survive
     compaction.

Planning/reconciliation preference: ``inbox/diff_summary.json`` wins
over ``inbox/brief.json`` when both exist — matches the reconciliation
branch in ``mcp_server.cmd_get_planning_brief:803-846``.

Output: ``{decision: "allow", hookSpecificOutput: {hookEventName,
additionalContext}}``. The hook never denies the prompt — policy
enforcement is PreToolUse's job. Corrupt inbox files are skipped
silently rather than wedging the agent.
"""
from __future__ import annotations
import json
import pathlib
import sys
from typing import Any
from typing import TextIO
from .. import _common
from .. import _ledger
from .. import _paths
from .. import _state_gates
from . import _env
_HOOK_NAME = 'UserPromptSubmit'

def _read_json_file(path: pathlib.Path | None, *, session_id: str | None=None, agent: str | None=None, verb: str | None=None, round_number: int=0, phase: str='') -> Any:
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        sys.stderr.write(f'{_HOOK_NAME} {verb or 'inbox_read'} JSON decode error at {path}: {exc}\n')
        if verb is not None and session_id is not None and (agent is not None):
            _ledger.append_hook_event(session_id, agent, verb, 'invalid', hook=_HOOK_NAME, round_number=round_number, phase=phase, detail={'reason': 'json_decode_error', 'error': str(exc), 'path': str(path)})
        return None
    except (FileNotFoundError, OSError):
        return None

def _task_file_for_mode(mode: str, session_id: str | None) -> tuple[pathlib.Path | None, str]:
    """Resolve (path, label) for the inbox file to inject given `mode`.

    Planning / reconciliation prefer diff_summary.json when present; this
    mirrors ``mcp_server.cmd_get_planning_brief`` which tries
    ``current_diff.json`` first and falls back to ``brief.json``.
    """
    base = _env.inbox_dir(session_id)
    if mode == 'synthesis':
        return (base / 'task.json', 'task')
    if mode in ('planning', 'reconciliation'):
        diff = base / 'diff_summary.json'
        if diff.is_file():
            return (diff, 'diff_summary')
        brief = base / 'brief.json'
        if brief.is_file():
            return (brief, 'brief')
    return (None, '')

def _feedback_file(session_id: str | None) -> pathlib.Path:
    return _env.inbox_dir(session_id) / 'feedback.json'

def _format_section(label: str, body: Any) -> str:
    serialized = json.dumps(body, indent=2)
    return f'--- {label.upper()} ---\n{serialized}'

def _format_feedback_section(body: Any) -> str:
    serialized = json.dumps(body, indent=2)
    return f'--- CROSS-EXAMINATION FEEDBACK ---\n{serialized}'

def build_locked_fields_reminder(*, agent: str, session_id: str, round_number: int, phase: str, submissions_remaining: int, clarifications_remaining: int) -> str:
    """Identity anchor appended to every UserPromptSubmit turn."""
    return f'Identity: agent={agent}, round={round_number}, phase={phase}, session={session_id}\nRemaining budget: submissions={submissions_remaining}/{_state_gates.MAX_SUBMISSIONS}, clarifications={clarifications_remaining}/{_state_gates.MAX_CLARIFICATIONS}'

def _write(stdout: TextIO, payload: dict[str, Any]) -> None:
    stdout.write(json.dumps(payload))
    stdout.flush()

def main(stdin: TextIO | None=None, stdout: TextIO | None=None) -> int:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    try:
        payload = _common.read_input(stdin)
    except _common.HookInputError as exc:
        sys.stderr.write(f'UserPromptSubmit: malformed stdin: {exc}\n')
        payload = {}
    session_id = str(payload.get('session_id') or '')
    agent = _paths.agent() or 'claude'
    mode = _paths.mode()
    state = _state_gates.read_state_besteffort()
    round_number = _state_gates.current_round(state)
    phase = _state_gates.current_phase(state) or mode
    events = _ledger.read_events(session_id, agent)
    sections: list[str] = []
    if not _ledger.has_verb(events, 'task_read', outcome='allow'):
        path, label = _task_file_for_mode(mode, session_id)
        body = _read_json_file(path, session_id=session_id, agent=agent, verb='task_read', round_number=round_number, phase=phase)
        if body is not None:
            sections.append(_format_section(label, body))
            _ledger.append_hook_event(session_id, agent, 'task_read', 'allow', hook=_HOOK_NAME, round_number=round_number, phase=phase, detail={'mode': mode, 'label': label, 'path': str(path)})
            inbox_task = _paths.load_inbox_task(_env.inbox_dir(session_id))
            files_touched_raw = inbox_task.get('files_touched') if isinstance(inbox_task, dict) else None
            if isinstance(files_touched_raw, list):
                files_touched = [str(f) for f in files_touched_raw if f is not None]
            elif isinstance(files_touched_raw, str):
                files_touched = [files_touched_raw]
            else:
                files_touched = []
            if files_touched:
                state_root = _paths.state_dir()
                history_path = state_root / 'control' / 'autowork' / 'self_healing_history.jsonl'
                alt_history_path = state_root / 'state' / 'control' / 'autowork' / 'self_healing_history.jsonl'
                if history_path.is_file() or alt_history_path.is_file():
                    records = _paths.load_self_healing_history(state_root)
                    matches = _paths.matching_history_records(records, files_touched)
                    if matches:
                        history_section = _paths.format_self_healing_section(matches)
                        if history_section:
                            sections.append(history_section.rstrip('\n'))
            task_id = os.environ.get('JANUSMASK_TASK_ID', '')
            if task_id:
                baseline_section = _format_baseline_section(_paths.state_dir(), task_id)
                if baseline_section:
                    sections.append(baseline_section)
    if phase == 'cross_examination' and (not _ledger.has_verb(events, 'feedback_read', outcome='allow')):
        fb_path = _feedback_file(session_id)
        body = _read_json_file(fb_path, session_id=session_id, agent=agent, verb='feedback_read', round_number=round_number, phase=phase)
        if body is not None:
            sections.append(_format_feedback_section(body))
            _ledger.append_hook_event(session_id, agent, 'feedback_read', 'allow', hook=_HOOK_NAME, round_number=round_number, phase=phase, detail={'path': str(fb_path)})
    sections.append(build_locked_fields_reminder(agent=agent, session_id=session_id, round_number=round_number, phase=phase, submissions_remaining=_state_gates.submissions_remaining(session_id, agent), clarifications_remaining=_state_gates.clarifications_remaining(session_id, agent)))
    _write(stdout, {'decision': 'allow', 'hookSpecificOutput': {'hookEventName': _HOOK_NAME, 'additionalContext': '\n\n'.join(sections)}})
    return 0
import os

def _baseline_result_path(state_root: pathlib.Path, task_id: str) -> pathlib.Path | None:
    """Resolve the baseline JSON path under ``state/tasks/test_results/``.

    Mirrors the worker's persistence path so the hook and the worker
    agree on a single location regardless of how state_dir was rooted.
    """
    if not task_id:
        return None
    primary = state_root / 'tasks' / 'test_results' / f'{task_id}_baseline.json'
    if primary.is_file():
        return primary
    alt = state_root / 'state' / 'tasks' / 'test_results' / f'{task_id}_baseline.json'
    if alt.is_file():
        return alt
    return primary if primary.exists() else None

def _format_baseline_section(state_root: pathlib.Path, task_id: str) -> str | None:
    """Read the pre-computed baseline JSON and format it as a markdown block.

    Returns ``None`` when the file is absent, unreadable, or not a dict so
    the caller appends nothing (silent skip mirrors the existing
    inbox-read failure semantics).
    """
    path = _baseline_result_path(state_root, task_id)
    if path is None:
        return None
    try:
        body = json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(body, dict):
        return None
    command = body.get('command', '')
    outcome = body.get('outcome', 'unknown')
    exit_code = body.get('exit_code')
    stdout_tail = body.get('stdout') or ''
    stderr_tail = body.get('stderr') or ''
    lines: list[str] = ['--- BASELINE TEST RESULTS (UNMODIFIED CODEBASE) ---']
    lines.append(f'Command: `{command}`')
    lines.append(f'Outcome: {outcome}')
    if exit_code is not None:
        lines.append(f'Exit code: {exit_code}')
    if stdout_tail:
        lines.append('')
        lines.append('Stdout (tail):')
        lines.append('```')
        lines.append(stdout_tail.rstrip('\n'))
        lines.append('```')
    if stderr_tail:
        lines.append('')
        lines.append('Stderr (tail):')
        lines.append('```')
        lines.append(stderr_tail.rstrip('\n'))
        lines.append('```')
    return '\n'.join(lines)
'UserPromptSubmit hook for the Claude worker (P2 / HOOK-21).\n\nReplaces the context-injection halves of three MCP verbs:\n``cmd_get_task`` (synthesis), ``cmd_get_planning_brief`` (planning /\nreconciliation), and ``cmd_get_feedback`` (cross_examination).\n\nFires on every user prompt arriving in Claude. Responsibilities\n(sub-plan 02 §4.2 + sub-plan 04 §4 invariants 3 & 9):\n\n  1. On the first prompt of a session (no ``task_read`` ledger row\n     yet), read the mode-appropriate inbox file and inject its JSON\n     body verbatim into ``additionalContext``. Append a ``task_read``\n     marker so follow-up prompts don\'t re-inject. When the task body\n     advertises ``files_touched``, also look up recent self-healing\n     history records that overlap and append a formatted section so\n     the worker can avoid repeating a known failing trajectory. When\n     a pre-computed baseline test result exists at\n     ``state/tasks/test_results/{task_id}_baseline.json``, append a\n     formatted markdown block summarising the unmodified-codebase\n     outcome so the agent can see whether the verification gate is\n     already green.\n  2. If STATE.json.phase == ``cross_examination`` and inbox/\n     feedback.json is present and has not been injected yet, inject it\n     and record ``feedback_read``.\n  3. Always append a locked-field reminder (agent/round/phase/remaining\n     submission+clarification budget) so identity anchors survive\n     compaction.\n\nPlanning/reconciliation preference: ``inbox/diff_summary.json`` wins\nover ``inbox/brief.json`` when both exist — matches the reconciliation\nbranch in ``mcp_server.cmd_get_planning_brief:803-846``.\n\nOutput: ``{decision: "allow", hookSpecificOutput: {hookEventName,\nadditionalContext}}``. The hook never denies the prompt — policy\nenforcement is PreToolUse\'s job. Corrupt inbox files are skipped\nsilently rather than wedging the agent.\n'
if __name__ == '__main__':
    raise SystemExit(main())