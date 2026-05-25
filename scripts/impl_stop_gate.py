#!/usr/bin/env python3
"""Stop meta-hook. Blocks Stop until current task DoD is met.

Honours stop_hook_active to avoid infinite loops. Writing a ledger row with
event='blocked' is the escape hatch — see hooks-augmented §3.3.
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from impl_common import (
    append_impl_progress_event,
    compute_dod_gaps,
    derive_state,
    load_ledger,
)


def main() -> int:
    try:
        raw = sys.stdin.read()
        inp = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        inp = {}

    if inp.get("stop_hook_active"):
        # Second Stop — let the agent stop; prior block message stands.
        append_impl_progress_event("stop_allow", detail="stop_hook_active=true; passthrough")
        sys.exit(0)

    ledger = load_ledger()
    state = derive_state(ledger)
    task = state["current_task_id"]
    if not task:
        # No active task; allow stop.
        sys.exit(0)

    # Check for an active blocked marker for this task (escape hatch).
    for row in reversed(ledger):
        if row.get("task_id") != task:
            continue
        if row.get("event") == "blocked":
            append_impl_progress_event(
                "stop_allow", task_id=task, phase=state["current_phase"],
                detail="blocked marker present",
            )
            sys.exit(0)
        if row.get("event") == "start":
            break

    gaps = compute_dod_gaps(task, ledger)
    if not gaps:
        append_impl_progress_event("stop_allow", task_id=task, phase=state["current_phase"])
        sys.exit(0)

    reason_lines = [f"Task {task} DoD unmet:"]
    for g in gaps:
        reason_lines.append(f"- {g}")
    reason_lines.append(
        "Either satisfy the gaps or append a ledger row "
        "{event:'blocked', task_id, detail} with a one-line justification, then Stop again."
    )
    reason = "\n".join(reason_lines)
    append_impl_progress_event(
        "stop_block", task_id=task, phase=state["current_phase"],
        detail=reason[:200], exit_code=1,
    )
    sys.stdout.write(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


if __name__ == "__main__":
    sys.exit(main() or 0)
