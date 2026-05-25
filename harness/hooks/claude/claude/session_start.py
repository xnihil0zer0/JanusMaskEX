"""SessionStart hook for the Claude worker (P2 / HOOK-20).

Replaces the MCP-proxy half of ``cmd_get_task`` + ``_inject_locked_fields``
+ the ``_initialized`` handshake (``harness/mcp_server.py:282-329,
:217-226, :595-601``). Fired once per Claude Code worker process. Reads
the hook envelope from stdin, resolves JANUSMASK_AGENT/MODE/ROUND,
asserts the orchestrator's pre-staged inbox matches the declared mode,
emits ``additionalContext`` anchoring the agent on identity + round +
phase + remaining submission/clarification budget, and appends a single
``session_start`` row to the per-session ledger so the rate-limit
counters (HOOK-22) and the ``task_read`` gate have a stable origin.

On inbox-missing or unknown mode: returns
``{continue: false, stopReason: ...}``. The orchestrator pre-stages
the inbox before spawning the worker (sub-plan 04 §1.1); a missing
inbox is an upstream breakage, and halting the worker surfaces the bug
on turn 0 rather than letting the agent invent a task.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from .. import _common, _ledger, _paths, _state_gates
from . import _env

_HOOK_NAME = "SessionStart"


def build_additional_context(
    *,
    agent: str,
    session_id: str,
    mode: str,
    round_number: int,
    phase: str,
    submissions_remaining: int,
    clarifications_remaining: int,
    source: str = "",
) -> str:
    """Human-readable banner injected into Claude's first turn.

    Prose, not JSON — Claude Code concatenates ``additionalContext``
    literally into the context window; bullet points read better.
    """
    source_suffix = f" (source={source})" if source else ""
    lines = [
        f"You are agent={agent}, mode={mode}, round={round_number}, "
        f"phase={phase}.",
        f"Session: {session_id}{source_suffix}",
        f"Submissions remaining: {submissions_remaining}/"
        f"{_state_gates.MAX_SUBMISSIONS}",
        f"Clarifications remaining: {clarifications_remaining}/"
        f"{_state_gates.MAX_CLARIFICATIONS}",
        "Inbox pre-staged by the orchestrator; Write to outbox/ only.",
    ]
    return "\n".join(lines)


def _stop_reason(
    mode: str, inbox_path: str, expected: tuple[str, ...]
) -> str:
    if not expected:
        return (
            f"Unknown JANUSMASK_MODE={mode!r}. Expected one of "
            f"{sorted(_env.INBOX_EXPECTATIONS)}."
        )
    names = ", ".join(expected)
    return (
        f"Inbox not staged for mode={mode!r}: none of [{names}] exist "
        f"under {inbox_path}. Orchestrator must pre-stage the inbox "
        f"before worker spawn."
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
        # Fail open on malformed envelopes: never wedge the worker on a
        # stdin glitch, but surface the error on stderr for diagnosis.
        sys.stderr.write(f"SessionStart: malformed stdin: {exc}\n")
        payload = {}

    session_id = str(payload.get("session_id") or "")
    source = str(payload.get("source") or "")
    agent = _paths.agent() or "claude"
    mode = _paths.mode()
    state = _state_gates.read_state_besteffort()
    round_number = _state_gates.current_round(state)
    phase = _state_gates.current_phase(state) or mode

    _env.ensure_workdir_skeleton(session_id)

    if not _env.inbox_ready(mode, session_id):
        inbox = _env.inbox_dir(session_id)
        expected = _env.expected_inbox_files(mode)
        reason = _stop_reason(mode, str(inbox), expected)
        _ledger.append_hook_event(
            session_id,
            agent,
            "session_start",
            "deny",
            hook=_HOOK_NAME,
            round_number=round_number,
            phase=phase,
            detail={"source": source, "mode": mode, "reason": reason},
        )
        _write(stdout, {"continue": False, "stopReason": reason})
        return 0

    ctx = build_additional_context(
        agent=agent,
        session_id=session_id,
        mode=mode,
        round_number=round_number,
        phase=phase,
        submissions_remaining=_state_gates.submissions_remaining(
            session_id, agent
        ),
        clarifications_remaining=_state_gates.clarifications_remaining(
            session_id, agent
        ),
        source=source,
    )
    _ledger.append_hook_event(
        session_id,
        agent,
        "session_start",
        "allow",
        hook=_HOOK_NAME,
        round_number=round_number,
        phase=phase,
        detail={"source": source, "mode": mode},
    )
    _write(
        stdout,
        {
            "continue": True,
            "hookSpecificOutput": {
                "hookEventName": _HOOK_NAME,
                "additionalContext": ctx,
            },
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
