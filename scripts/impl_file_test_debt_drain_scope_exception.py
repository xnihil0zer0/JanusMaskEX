"""scripts/impl_file_test_debt_drain_scope_exception.py

One-shot scope_exception authorizing test-debt drain edits to
tests/test_ast_enforcer.py (the only target outside META allow-list;
tests/adversarial/** is already permitted).

Context: post-G13 (commit 7b97427) the ast_enforcer validator's
incomplete_ast rule widened to accept ClassDef/ImportFrom/Assign-Name/
AnnAssign-Name as mergeable tops. Two TestSyntaxValidation cases
(test_no_function_def, test_only_class_no_function) pin the pre-G13
narrow shape and now FAIL against intentional impl. Update test bodies
to match the new accept-surface (renamed for clarity).

Idempotent — checks last 50 rows and skips if equivalent row exists.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from impl_common import LEDGER_PATH, load_ledger, now_iso, write_jsonl_row  # type: ignore

PATHS = [
    "tests/test_ast_enforcer.py",
]
DETAIL = (
    "META-TEST-DEBT-DRAIN: post-sweep-closure session #3 manual test-edit drain. "
    "Updates 2 TestSyntaxValidation cases (test_no_function_def, "
    "test_only_class_no_function) in tests/test_ast_enforcer.py to reflect "
    "G13's (7b97427) widened incomplete_ast accept-surface. Test-edit only, "
    "no impl change. Operator: kevin.lindmark0@gmail.com."
)


def main() -> int:
    rows = load_ledger()
    for r in rows[-50:]:
        if (
            r.get("event") == "scope_exception"
            and r.get("task_id") == "META-TEST-DEBT-DRAIN"
            and set(r.get("paths", [])) == set(PATHS)
        ):
            print("scope_exception already filed; skipping.")
            return 0
    row = {
        "ts": now_iso(),
        "phase": "META",
        "task_id": "META-TEST-DEBT-DRAIN",
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
