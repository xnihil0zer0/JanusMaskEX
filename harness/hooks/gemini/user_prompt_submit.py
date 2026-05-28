"""User-prompt context-injection hook for the Gemini worker (P3 / HOOK-31).

Gemini CLI doesn't ship a dedicated UserPromptSubmit hook -- its event
list (``gemini_chunk.js`` line 314832) goes BeforeTool / AfterTool /
BeforeModel / AfterModel / SessionStart / SessionEnd / PreCompress /
Notification. The functional equivalent of Claude's UserPromptSubmit
is whatever fires once per agent turn before the model is called; on
the Gemini side the orchestrator wires this module to BeforeModel
(or to a SessionStart follow-up for single-turn workers).

Responsibilities (mirror ``harness.hooks.claude.user_prompt_submit``):

  1. On the first prompt of a session (no ``task_read`` row in the
     per-session ledger), read the mode-appropriate inbox file and
     inject its JSON body into ``systemMessage``. Append a
     ``task_read`` marker so follow-up prompts don't re-inject.
     When ``files_touched`` is present on the task, look up recent
     self-healing history records that overlap and append a formatted
     section so the worker sees prior incidents for the same files.
  2. If ``STATE.json.phase == "cross_examination"`` and an inbox/
     ``feedback.json`` is present, inject it once and record
     ``feedback_read``.
  3. Always append a locked-field reminder (agent / round / phase /
     remaining budget) so identity anchors survive any compaction.

The ledger verbs (``task_read``, ``feedback_read``) are *shared* with
HOOK-21 -- idempotency is the same contract on both sides, which keeps
the Phase 5 shadow-diff equivalence checker honest.
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
_HOOK_NAME = 'BeforeModel'

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
    return f'Identity: agent={agent}, round={round_number}, phase={phase}, session={session_id}\nRemaining budget: submissions={submissions_remaining}/{_state_gates.MAX_SUBMISSIONS}, clarifications={clarifications_remaining}/{_state_gates.MAX_CLARIFICATIONS}'

def _write(stdout: TextIO, payload: dict[str, Any]) -> None:
    stdout.write(json.dumps(payload))
    stdout.flush()

def main(stdin: TextIO | None=None, stdout: TextIO | None=None) -> int:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    try:
        payload = _common.read_input(stdin)
    except (ValueError, _common.HookInputError) as exc:
        sys.stderr.write(f'BeforeModel(gemini): malformed stdin: {exc}\n')
        payload = {}
    session_id = str(payload.get('session_id') or '')
    agent = _paths.agent() or 'gemini'
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
    _write(stdout, {'decision': 'allow', 'systemMessage': '\n\n'.join(sections)})
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
'User-prompt context-injection hook for the Gemini worker (P3 / HOOK-31).\n\nGemini CLI doesn\'t ship a dedicated UserPromptSubmit hook -- its event\nlist (``gemini_chunk.js`` line 314832) goes BeforeTool / AfterTool /\nBeforeModel / AfterModel / SessionStart / SessionEnd / PreCompress /\nNotification. The functional equivalent of Claude\'s UserPromptSubmit\nis whatever fires once per agent turn before the model is called; on\nthe Gemini side the orchestrator wires this module to BeforeModel\n(or to a SessionStart follow-up for single-turn workers).\n\nResponsibilities (mirror ``harness.hooks.claude.user_prompt_submit``):\n\n  1. On the first prompt of a session (no ``task_read`` row in the\n     per-session ledger), read the mode-appropriate inbox file and\n     inject its JSON body into ``systemMessage``. Append a\n     ``task_read`` marker so follow-up prompts don\'t re-inject.\n     When ``files_touched`` is present on the task, look up recent\n     self-healing history records that overlap and append a formatted\n     section so the worker sees prior incidents for the same files.\n     When a pre-computed baseline test result exists at\n     ``state/tasks/test_results/{task_id}_baseline.json``, append a\n     formatted markdown block summarising the unmodified-codebase\n     outcome so the worker can see whether the verification gate is\n     already green.\n  2. If ``STATE.json.phase == "cross_examination"`` and an inbox/\n     ``feedback.json`` is present, inject it once and record\n     ``feedback_read``.\n  3. Always append a locked-field reminder (agent / round / phase /\n     remaining budget) so identity anchors survive any compaction.\n\nThe ledger verbs (``task_read``, ``feedback_read``) are *shared* with\nHOOK-21 -- idempotency is the same contract on both sides, which keeps\nthe Phase 5 shadow-diff equivalence checker honest.\n'
if __name__ == '__main__':
    raise SystemExit(main())