"""SessionEnd hook for the Gemini worker (P3 / HOOK-34).

Gemini twin of ``harness.hooks.claude.stop``. Gemini's event list
has ``SessionEnd`` instead of Claude's ``Stop``; the semantic role is
the same — the last-chance gate that enforces "at least one accepted
mandatory verb per round" before letting the worker exit.

Mandatory verbs per mode (shared with Claude):
    synthesis      -> submit_code   (outbox/submission.py)
    planning       -> plan_draft    (outbox/plan_draft.json)
    reconciliation -> reconciliation (outbox/reconciliation.json)

Escape hatch: if ``stop_hook_active`` is set (the Gemini equivalent
of Claude's second-stop flag the CLI sends after a block), the hook
allows unconditionally so a buggy gate never wedges the worker
forever. Malformed stdin also fails open — surfacing a diagnostic on
stderr but never blocking exit.

A ``session_end`` ledger row is appended on every invocation, tagged
with the decision so the orchestrator has a stable terminal marker
per session.
"""

from __future__ import annotations

import sys
from typing import TextIO

from .. import _common, _ledger, _paths, _state_gates
from . import _env  # noqa: F401 — ensures the gemini package is imported

_HOOK_NAME = "SessionEnd"

MANDATORY_VERBS: dict[str, tuple[str, str]] = {
    "synthesis": ("submit_code", "outbox/submission.py"),
    "planning": ("plan_draft", "outbox/plan_draft.json"),
    "reconciliation": ("reconciliation", "outbox/reconciliation.json"),
}


def _decide(
    *,
    mode: str,
    stop_hook_active: bool,
    session_id: str,
    agent: str,
) -> tuple[str, str]:
    if stop_hook_active:
        return ("allow", "")
    mandatory = MANDATORY_VERBS.get(mode)
    if mandatory is None:
        return ("allow", "")
    verb, filename = mandatory
    events = _ledger.read_events(session_id, agent)
    if _ledger.has_verb(events, verb, outcome="allow"):
        return ("allow", "")
    reason = (
        f"{mode} round requires at least one accepted {verb!r}. "
        f"write_file (or replace) to {filename} (BeforeTool will "
        f"validate + AfterTool will persist) before stopping. This "
        f"block fires once; a second SessionEnd with "
        f"stop_hook_active=true is allowed as an escape."
    )
    return ("deny", reason)


def main(stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    try:
        payload = _common.read_input(stdin)
    except _common.HookInputError as exc:
        sys.stderr.write(f"SessionEnd(gemini): malformed stdin: {exc}\n")
        _common.write_decision(_common.decision_payload("allow"), stdout)
        return 0

    session_id = str(payload.get("session_id") or "")
    stop_hook_active = bool(payload.get("stop_hook_active"))
    agent = _paths.agent() or "gemini"
    mode = _paths.mode()
    state = _state_gates.read_state_besteffort()
    round_number = _state_gates.current_round(state)
    phase = _state_gates.current_phase(state) or mode

    decision, reason = _decide(
        mode=mode,
        stop_hook_active=stop_hook_active,
        session_id=session_id,
        agent=agent,
    )

    _ledger.append_hook_event(
        session_id,
        agent,
        "session_end",
        decision,
        hook=_HOOK_NAME,
        round_number=round_number,
        phase=phase,
        detail={
            "mode": mode,
            "stop_hook_active": stop_hook_active,
            "reason": reason,
        },
    )
    _common.write_decision(
        _common.decision_payload(decision, reason=reason), stdout
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
