"""scripts/impl_file_g18bc_orchestrator_tail_scope_exception.py

One-shot scope_exception authorizing the manual commit of the
harness/orchestrator.py half of G18bc. Context: G18bc was a dual-file
dispatch (harness/git_integration.py + harness/orchestrator.py). The
agents authored BOTH files correctly (the worktree's orchestrator.py
matches the brief verbatim), and the vcmd's AST-shape assertions on
orchestrator.py passed. However, `_auto_commit_accepted` at
harness/orchestrator.py:863 only processes `files_touched[0]` -- a known
single-file-per-dispatch limitation of the auto-commit pipeline -- so
only harness/git_integration.py was auto-committed (e66f7f4). The
matching orchestrator.py edit landed on disk via the AST merge but was
never staged. This scope_exception authorizes the manual stage+commit
of the orchestrator.py tail so G18bc lands as a complete pair.

Filing for next-session note: the single-file-only dispatch constraint
is a harness gap (G19 candidate): for any dispatch whose files_touched
has len > 1, the orchestrator silently drops the tail files. Either
extend _auto_commit_accepted to iterate, or surface a validator error
at plan-staging time.

Idempotent -- checks last 50 rows and skips if equivalent row exists.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from impl_common import LEDGER_PATH, load_ledger, now_iso, write_jsonl_row  # type: ignore

PATHS = [
    "harness/orchestrator.py",
]
DETAIL = (
    "META-G18bc-ORCH-TAIL: manual stage+commit of the harness/orchestrator.py "
    "half of G18bc_orchestrator_silent_noop_close. Agents authored both files; "
    "AST merge landed orchestrator.py edits on disk; vcmd validated the AST "
    "shape end-to-end. The orchestrator's _auto_commit_accepted only commits "
    "files_touched[0] (single-file dispatch limitation), so the tail edit needs "
    "a manual commit. Operator: kevin.lindmark0@gmail.com."
)


def main() -> int:
    rows = load_ledger()
    for r in rows[-50:]:
        if (
            r.get("event") == "scope_exception"
            and r.get("task_id") == "META-G18bc-ORCH-TAIL"
            and set(r.get("paths", [])) == set(PATHS)
        ):
            print("scope_exception already filed; skipping.")
            return 0
    row = {
        "ts": now_iso(),
        "phase": "META",
        "task_id": "META-G18bc-ORCH-TAIL",
        "event": "scope_exception",
        "detail": DETAIL,
        "files": [],
        "exit": 0,
        "paths": PATHS,
        "approved_by": "human",
        "consume_on": "test_pass",
    }
    write_jsonl_row(LEDGER_PATH, row)
    print(f"scope_exception filed: {len(PATHS)} paths -> {LEDGER_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
