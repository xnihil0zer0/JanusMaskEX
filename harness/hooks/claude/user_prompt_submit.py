"""UserPromptSubmit hook for the Claude worker (P2 / HOOK-21).

Replaces the context-injection halves of three MCP verbs:
``cmd_get_task`` (synthesis), ``cmd_get_planning_brief`` (planning /
reconciliation), and ``cmd_get_feedback`` (cross_examination).

Fires on every user prompt arriving in Claude. Responsibilities
(sub-plan 02 §4.2 + sub-plan 04 §4 invariants 3 & 9):

  1. On the first prompt of a session (no ``task_read`` ledger row
     yet), read the mode-appropriate inbox file and inject its JSON
     body verbatim into ``additionalContext``. Append a ``task_read``
     marker so follow-up prompts don't re-inject.
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
from typing import Any, TextIO

from .. import _common, _ledger, _paths, _state_gates
from . import _env

_HOOK_NAME = "UserPromptSubmit"


def _read_json_file(
    path: pathlib.Path | None,
    *,
    session_id: str | None = None,
    agent: str | None = None,
    verb: str | None = None,
    round_number: int = 0,
    phase: str = "",
) -> Any:
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.stderr.write(
            f"{_HOOK_NAME} {verb or 'inbox_read'} JSON decode error at {path}: {exc}\n"
        )
        if verb is not None and session_id is not None and agent is not None:
            _ledger.append_hook_event(
                session_id,
                agent,
                verb,
                "invalid",
                hook=_HOOK_NAME,
                round_number=round_number,
                phase=phase,
                detail={
                    "reason": "json_decode_error",
                    "error": str(exc),
                    "path": str(path),
                },
            )
        return None
    except (FileNotFoundError, OSError):
        return None


def _task_file_for_mode(
    mode: str, session_id: str | None
) -> tuple[pathlib.Path | None, str]:
    """Resolve (path, label) for the inbox file to inject given `mode`.

    Planning / reconciliation prefer diff_summary.json when present; this
    mirrors ``mcp_server.cmd_get_planning_brief`` which tries
    ``current_diff.json`` first and falls back to ``brief.json``.
    """
    base = _env.inbox_dir(session_id)
    if mode == "synthesis":
        return base / "task.json", "task"
    if mode in ("planning", "reconciliation"):
        diff = base / "diff_summary.json"
        if diff.is_file():
            return diff, "diff_summary"
        brief = base / "brief.json"
        if brief.is_file():
            return brief, "brief"
    return None, ""


def _feedback_file(session_id: str | None) -> pathlib.Path:
    return _env.inbox_dir(session_id) / "feedback.json"


def _format_section(label: str, body: Any) -> str:
    serialized = json.dumps(body, indent=2)
    return f"--- {label.upper()} ---\n{serialized}"


def _format_feedback_section(body: Any) -> str:
    serialized = json.dumps(body, indent=2)
    return f"--- CROSS-EXAMINATION FEEDBACK ---\n{serialized}"


def build_locked_fields_reminder(
    *,
    agent: str,
    session_id: str,
    round_number: int,
    phase: str,
    submissions_remaining: int,
    clarifications_remaining: int,
) -> str:
    """Identity anchor appended to every UserPromptSubmit turn."""
    return (
        f"Identity: agent={agent}, round={round_number}, phase={phase}, "
        f"session={session_id}\n"
        f"Remaining budget: submissions={submissions_remaining}/"
        f"{_state_gates.MAX_SUBMISSIONS}, clarifications="
        f"{clarifications_remaining}/{_state_gates.MAX_CLARIFICATIONS}"
    )


def _write(stdout: TextIO, payload: dict[str, Any]) -> None:
    stdout.write(json.dumps(payload))
    stdout.flush()


def main(stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    try:
        payload = _common.read_input(stdin)
    except _common.HookInputError as exc:
        sys.stderr.write(f"UserPromptSubmit: malformed stdin: {exc}\n")
        payload = {}

    session_id = str(payload.get("session_id") or "")
    agent = _paths.agent() or "claude"
    mode = _paths.mode()
    state = _state_gates.read_state_besteffort()
    round_number = _state_gates.current_round(state)
    phase = _state_gates.current_phase(state) or mode

    events = _ledger.read_events(session_id, agent)
    sections: list[str] = []

    # (1) Task / brief / diff_summary injection — first prompt only.
    if not _ledger.has_verb(events, "task_read", outcome="allow"):
        path, label = _task_file_for_mode(mode, session_id)
        body = _read_json_file(
            path,
            session_id=session_id,
            agent=agent,
            verb="task_read",
            round_number=round_number,
            phase=phase,
        )
        if body is not None:
            sections.append(_format_section(label, body))
            _ledger.append_hook_event(
                session_id,
                agent,
                "task_read",
                "allow",
                hook=_HOOK_NAME,
                round_number=round_number,
                phase=phase,
                detail={"mode": mode, "label": label, "path": str(path)},
            )

    # (2) Feedback injection — cross_examination only, once per session.
    if phase == "cross_examination" and not _ledger.has_verb(
        events, "feedback_read", outcome="allow"
    ):
        fb_path = _feedback_file(session_id)
        body = _read_json_file(
            fb_path,
            session_id=session_id,
            agent=agent,
            verb="feedback_read",
            round_number=round_number,
            phase=phase,
        )
        if body is not None:
            sections.append(_format_feedback_section(body))
            _ledger.append_hook_event(
                session_id,
                agent,
                "feedback_read",
                "allow",
                hook=_HOOK_NAME,
                round_number=round_number,
                phase=phase,
                detail={"path": str(fb_path)},
            )

    # (3) Locked-field reminder — always appended.
    sections.append(
        build_locked_fields_reminder(
            agent=agent,
            session_id=session_id,
            round_number=round_number,
            phase=phase,
            submissions_remaining=_state_gates.submissions_remaining(
                session_id, agent
            ),
            clarifications_remaining=_state_gates.clarifications_remaining(
                session_id, agent
            ),
        )
    )

    _write(
        stdout,
        {
            "decision": "allow",
            "hookSpecificOutput": {
                "hookEventName": _HOOK_NAME,
                "additionalContext": "\n\n".join(sections),
            },
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
