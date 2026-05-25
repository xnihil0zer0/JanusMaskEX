"""PreCompact hook for the Claude worker (P2 / HOOK-25).

Claude Code fires this hook before compacting the conversation
context. JanusMask has no state that needs migrating across the
compaction boundary — the per-session ledger at
``state/sessions/{agent}_{session_id}.ledger.jsonl`` already
persists everything we care about, and ``SessionStart`` re-injects
identity + task context on the post-compact side.

The hook therefore journal-only: one ``pre_compact`` row so the
operator can correlate transcripts with compaction events, plus an
``additionalContext`` note telling the model that its ledger is
durable across the boundary.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from .. import _common, _ledger, _paths, _state_gates
from . import _env  # noqa: F401 — ensures the claude package is imported

_HOOK_NAME = "PreCompact"


def _write(stdout: TextIO, payload: dict[str, Any]) -> None:
    stdout.write(json.dumps(payload))
    stdout.flush()


def main(stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    try:
        payload = _common.read_input(stdin)
    except _common.HookInputError as exc:
        sys.stderr.write(f"PreCompact: malformed stdin: {exc}\n")
        payload = {}

    session_id = str(payload.get("session_id") or "")
    trigger = str(payload.get("trigger") or "")
    agent = _paths.agent() or "claude"
    state = _state_gates.read_state_besteffort()
    round_number = _state_gates.current_round(state)
    phase = _state_gates.current_phase(state) or _paths.mode()

    _ledger.append_hook_event(
        session_id,
        agent,
        "pre_compact",
        "allow",
        hook=_HOOK_NAME,
        round_number=round_number,
        phase=phase,
        detail={"trigger": trigger},
    )
    _write(
        stdout,
        {
            "continue": True,
            "hookSpecificOutput": {
                "hookEventName": _HOOK_NAME,
                "additionalContext": (
                    "Session ledger persists across compaction; SessionStart "
                    "will re-anchor identity + task context on the next turn."
                ),
            },
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
