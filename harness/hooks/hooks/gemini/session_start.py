"""SessionStart hook for the Gemini worker (P3 / HOOK-30).

Gemini CLI's ``HookEventName.SessionStart`` fires before any tool
dispatch (gemini_chunk.js line 314832). This module is the Gemini twin
of ``harness.hooks.claude.session_start``: it reads the same stdin
envelope, resolves agent/mode/round from the same env vars, seeds the
same per-session ledger, and emits a banner carrying identity +
remaining-budget anchors.

Two Gemini-specific jobs on top of the Claude shape:

  1. Assert ``security.folderTrust.enabled == true`` in the resolved
     settings file. Gemini silently drops project-level hooks when
     the folder is untrusted (gemini_chunk.js line 325910) — if the
     orchestrator ships a settings.json with folderTrust off, the
     session would run *without any gates* and the operator would
     see a successful-looking worker that never actually gated a
     single tool call. We surface that as ``continue: false`` with
     a stop reason on turn 0.

  2. Emit the banner as ``systemMessage`` (Gemini's equivalent of
     Claude's ``additionalContext``). Claude Code and Gemini CLI
     differ on the envelope shape for continue-style events; the
     vocabulary is normalised one layer up in ``_common.py``, but the
     key names are event-specific and belong here.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from typing import Any, TextIO

from .. import _common, _ledger, _paths, _state_gates
from . import _env

_HOOK_NAME = "SessionStart"

# Decision token is 'deny' per plan §3.1 normalisation via
# harness/hooks/_common.py:44-53 (_normalise_decision rewrites block→deny).
# Claude Code's native Stop-event contract expects 'block' to re-prompt;
# empirical re-prompt behaviour to be verified during Phase 5 shadow.


def build_system_message(
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
    """Human-readable banner injected into Gemini's first turn."""
    source_suffix = f" (source={source})" if source else ""
    lines = [
        f"You are agent={agent}, mode={mode}, round={round_number}, "
        f"phase={phase}.",
        f"Session: {session_id}{source_suffix}",
        f"Submissions remaining: {submissions_remaining}/"
        f"{_state_gates.MAX_SUBMISSIONS}",
        f"Clarifications remaining: {clarifications_remaining}/"
        f"{_state_gates.MAX_CLARIFICATIONS}",
        "Inbox pre-staged by the orchestrator; write_file to outbox/ only.",
    ]
    return "\n".join(lines)


def _resolve_settings() -> dict | None:
    """Read the settings file the orchestrator pointed the worker at.

    Preference order:
      1. $JANUSMASK_GEMINI_SETTINGS (orchestrator-set absolute path)
      2. $GEMINI_PROJECT_DIR/.gemini/settings.json (gemini default)
      3. $JANUSMASK_PROJECT_DIR/config/gemini_settings.json (repo copy)

    Returns ``None`` on any I/O or parse error — callers treat that as
    ``folderTrust.enabled is False`` so a corrupt settings file is
    surfaced, not silently accepted.
    """
    explicit = os.environ.get("JANUSMASK_GEMINI_SETTINGS")
    if explicit:
        # When the orchestrator names an explicit settings file, it is
        # authoritative — a missing or unparsable file at that path is
        # a hard deny, not a fall-through. Silently reading a DIFFERENT
        # settings file than the one the orchestrator intended would be
        # worse than halting the session.
        try:
            return json.loads(
                pathlib.Path(explicit).read_text(encoding="utf-8")
            )
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
    candidates: list[pathlib.Path] = []
    project = os.environ.get("GEMINI_PROJECT_DIR") or os.environ.get(
        "CLAUDE_PROJECT_DIR"
    )
    if project:
        candidates.append(pathlib.Path(project) / ".gemini" / "settings.json")
    candidates.append(
        _paths.project_dir() / "config" / "gemini_settings.json"
    )
    for path in candidates:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
    return None


def _stop_reason_inbox(
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


def _stop_reason_folder_trust() -> str:
    return (
        "Gemini security.folderTrust.enabled must be true for project-level "
        "hooks to register (gemini_chunk.js line 325910). Settings either "
        "missing, unreadable, or has folderTrust disabled — without it the "
        "BeforeTool/AfterTool gates would silently not fire."
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
        sys.stderr.write(f"SessionStart(gemini): malformed stdin: {exc}\n")
        payload = {}

    session_id = str(payload.get("session_id") or "")
    source = str(payload.get("source") or "")
    agent = _paths.agent() or "gemini"
    mode = _paths.mode()
    state = _state_gates.read_state_besteffort()
    round_number = _state_gates.current_round(state)
    phase = _state_gates.current_phase(state) or mode

    _env.ensure_workdir_skeleton(session_id)

    # FolderTrust gate first — if hooks wouldn't register, nothing else
    # in this pipeline means anything. Surface loudly on turn 0.
    settings = _resolve_settings()
    if not _env.folder_trust_enabled(settings):
        reason = _stop_reason_folder_trust()
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

    if not _env.inbox_ready(mode, session_id):
        inbox = _env.inbox_dir(session_id)
        expected = _env.expected_inbox_files(mode)
        reason = _stop_reason_inbox(mode, str(inbox), expected)
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

    msg = build_system_message(
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
    _write(stdout, {"continue": True, "systemMessage": msg})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
