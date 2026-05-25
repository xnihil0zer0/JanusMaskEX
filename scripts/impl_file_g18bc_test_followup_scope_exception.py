"""scripts/impl_file_g18bc_test_followup_scope_exception.py

One-shot scope_exception authorizing manual test edits to tests/test_orchestrator.py
(outside META allow-list). G18bc intentionally changed orchestrator.py:run_pipeline's
accept-path shape (auto_commit_ok = _auto_commit_accepted gate; rejected branch
on False). Two pipeline tests in tests/test_orchestrator.py constructed synthetic
tasks without verification_command, which V2 (cf523fd) rejects. Pre-G18bc the
orchestrator discarded V2's False return and still set phase='accepted' --
that was the silent-NOOP class G18bc closed. The tests pinned the old false-accept
shape; updating them to include verification_command='true' reflects the V2+G18bc
correctness contract.

The other 4 follow-up edits are under tests/adversarial/** (already in allow-list).

Idempotent.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from impl_common import LEDGER_PATH, load_ledger, now_iso, write_jsonl_row  # type: ignore

PATHS = [
    "tests/test_orchestrator.py",
]
DETAIL = (
    "META-G18bc-TEST-FOLLOWUP: post-G18bc test-staleness drain. Updates "
    "TestPipelineStateTransitions::test_equivalent_fuzz_accepted + "
    "test_round2_equivalent_accepted to add verification_command='true' to "
    "synthetic test tasks (was false-passing pre-G18bc because the orchestrator "
    "ignored V2's False return). Test-edit only, no impl change. "
    "Operator: kevin.lindmark0@gmail.com."
)


def main() -> int:
    rows = load_ledger()
    for r in rows[-50:]:
        if (
            r.get("event") == "scope_exception"
            and r.get("task_id") == "META-G18bc-TEST-FOLLOWUP"
            and set(r.get("paths", [])) == set(PATHS)
        ):
            print("scope_exception already filed; skipping.")
            return 0
    row = {
        "ts": now_iso(),
        "phase": "META",
        "task_id": "META-G18bc-TEST-FOLLOWUP",
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
