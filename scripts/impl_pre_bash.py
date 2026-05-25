#!/usr/bin/env python3
"""PreToolUse:Bash meta-hook. Denies destructive git ops until DoD is met.

Only gates git commit / push / reset --hard / rebase. Everything else is
allowed. See hooks-augmented-hooks-implementation-plan.md §3.1.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from impl_common import (
    adv_satisfied,
    load_ledger,
    task_manifest,
    test_passed,
)


def _most_recent_start(ledger: list[dict]) -> dict | None:
    for row in reversed(ledger):
        if row.get("event") == "start":
            return row
    return None

GATED_PATTERNS = [
    re.compile(r"\bgit\s+commit\b"),
    re.compile(r"\bgit\s+push\b"),
    re.compile(r"\bgit\s+reset\s+--hard\b"),
    re.compile(r"\bgit\s+rebase\b"),
]


def _deny(reason: str) -> None:
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    sys.stdout.write(json.dumps(out))
    sys.exit(0)


def main() -> int:
    try:
        raw = sys.stdin.read()
        inp = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        sys.exit(0)

    command = (inp.get("tool_input") or {}).get("command", "") or ""
    # Strip heredoc bodies before pattern-matching so payloads cannot
    # smuggle (or be falsely accused of carrying) gated git verbs in
    # documentation strings, prints, or generated code. Then split the
    # remaining command into top-level shell segments and only fire the
    # gate when a gated verb appears as a real command, not a substring
    # of a quoted argument inside the same segment as something benign.
    #
    # Heredoc forms handled:
    #   <<EOF ... EOF        <<-EOF (tab-indented end)
    #   <<'EOF' ... EOF      <<"EOF" ... EOF
    # Multiple heredocs in one command are stripped iteratively (DOTALL
    # + non-greedy keeps each pair local).
    #
    # KNOWN LIMITATIONS (documented; not a security regression vs. today
    # because today's gate is a SUPER-set false-positive of these):
    #   * Connectors inside double/single quotes (echo "a && b") are
    #     still treated as segment splits. False positives remain
    #     possible, but never on the gated verbs themselves unless the
    #     quoted text literally contains `git commit` etc., which is
    #     no worse than today.
    #   * Subshells `(...)` are not unwrapped; a gated verb inside
    #     parentheses still triggers the gate (correct: it IS a real
    #     git invocation).
    #   * `$(...)` / backtick command substitution is not split; a
    #     gated verb inside still triggers (also correct).
    #   * Comments after `#` are not stripped; gated verbs in trailing
    #     comments still trigger (rare; safer to over-gate).
    stripped = re.sub(
        r"<<-?\s*[\"']?(\w+)[\"']?\n.*?\n\s*\1\s*(?:\n|$)",
        "\n",
        command,
        flags=re.DOTALL,
    )
    segments = re.split(r"&&|\|\||;|(?<!\|)\|(?!\|)", stripped)
    if not any(p.search(seg) for seg in segments for p in GATED_PATTERNS):
        sys.exit(0)

    ledger = load_ledger()
    start = _most_recent_start(ledger)
    if start is None:
        _deny(
            "Destructive git operations require an active task with test_pass + adv_pass. "
            "No active task in ledger."
        )
    task = start.get("task_id", "")

    manifest = task_manifest(task)
    need_adv = bool(manifest.get("adv_required"))
    has_test = test_passed(ledger, task)
    has_adv = adv_satisfied(ledger, task) if need_adv else True
    if has_test and has_adv:
        sys.exit(0)

    missing = []
    if not has_test:
        missing.append("test_pass")
    if need_adv and not has_adv:
        missing.append("adv_pass")
    _deny(
        f"Task {task} is not ready for git commit/push: missing {missing} rows. "
        f"Run tests + adversarial battery first, or append a blocked row to pause."
    )


if __name__ == "__main__":
    sys.exit(main() or 0)
