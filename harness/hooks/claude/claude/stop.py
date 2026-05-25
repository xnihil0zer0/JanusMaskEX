"""Stop hook for the Claude worker (P2 / HOOK-24).

Restores the "must submit before stopping" invariant the old MCP
inbox-gate enforced implicitly. For each mode, one ledger verb is
the mandatory output — the worker must have at least one
``outcome=allow`` row for that verb before it's permitted to stop:

    synthesis      -> submit_code
    planning       -> plan_draft
    reconciliation -> reconciliation

If the gate would block but ``stop_hook_active`` is already set
(Claude Code's second-stop flag), the hook allows — this is the
escape hatch that prevents block-loop thrash when the gate logic
has a bug.

On every path, the hook appends a ``session_end`` ledger row so
the orchestrator has a stable terminal marker per session.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from .. import _common, _ledger, _paths, _state_gates
from . import _env  # noqa: F401 — ensures the claude package is imported

_HOOK_NAME = "Stop"

# Mode -> (ledger verb, human-readable mandatory-output filename).
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
    """Return (decision, reason). decision in {'allow','deny'}."""
    # Decision token is 'deny' per plan §3.1 normalisation via
    # harness/hooks/_common.py:44-53 (_normalise_decision rewrites block→deny).
    # Claude Code's native Stop-event contract expects 'block' to re-prompt;
    # empirical re-prompt behaviour to be verified during Phase 5 shadow.
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
        f"Write {filename} (PreToolUse will validate + PostToolUse will "
        f"persist) before stopping. This block fires once; a second "
        f"Stop with stop_hook_active=true is allowed as an escape."
    )
    return ("deny", reason)


def main(stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    try:
        payload = _common.read_input(stdin)
    except _common.HookInputError as exc:
        # Fail open — never wedge the agent forever on a stdin glitch.
        sys.stderr.write(f"Stop: malformed stdin: {exc}\n")
        _common.write_decision(_common.decision_payload("allow"), stdout)
        return 0

    session_id = str(payload.get("session_id") or "")
    stop_hook_active = bool(payload.get("stop_hook_active"))
    agent = _paths.agent() or "claude"
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
