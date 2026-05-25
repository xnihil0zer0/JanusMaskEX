#!/usr/bin/env python3
"""PreCompact meta-hook. Snapshots current phase state to
state/impl_preserve.md so the post-compact session sees ground truth.
"""

from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from impl_common import (
    PRESERVE_PATH,
    compute_dod_gaps,
    derive_state,
    load_ledger,
    phase_allow_globs,
)


def main() -> int:
    ledger = load_ledger()
    state = derive_state(ledger)
    phase = state["current_phase"] or "META"
    task = state["current_task_id"] or "<none>"
    gaps = compute_dod_gaps(task, ledger) if task != "<none>" else []
    globs = phase_allow_globs(phase)

    lines = [
        "# JanusMask meta-hook pre-compact snapshot",
        "",
        f"- Current phase: `{phase}`",
        f"- Current task: `{task}`",
        f"- Rollback signal: {state['rollback_signal']}",
        "",
        "## Outstanding DoD gaps",
    ]
    if gaps:
        for g in gaps:
            lines.append(f"- {g}")
    else:
        lines.append("- (none — Stop will be allowed)")
    lines.append("")
    lines.append(f"## Phase {phase} write allow-list")
    for g in globs:
        lines.append(f"- `{g}`")
    lines.append("")
    lines.append("## Last 5 ledger rows")
    for r in state["last_rows"]:
        lines.append(f"- `{r}`")

    PRESERVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PRESERVE_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sys.exit(0)


if __name__ == "__main__":
    sys.exit(main() or 0)
