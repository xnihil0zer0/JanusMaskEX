"""scripts/impl_close_brief_verification_required.py

Append a brief_closure ledger row for
brief_hooks_orchestrator_verification_required.md after V1 + V2 landed via
orchestrator dispatch (commits 3739e72 + add5171).

Idempotent: skips if a brief_closure row for this task_id already exists in
the last 50 ledger rows.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from impl_common import LEDGER_PATH, load_ledger, now_iso, write_jsonl_row  # type: ignore

TASK_ID = "META-BRIEF-VERIFICATION-REQUIRED"
DETAIL = (
    "brief_hooks_orchestrator_verification_required.md closed: V1 + V2 both "
    "landed via orchestrator dispatch (V1 commit 3739e72 on "
    "harness/planner/plan_validator.py; V2 commit add5171 on "
    "harness/orchestrator.py). Both passed their own non-empty "
    "verification_command at commit time (auto_commit rows exit=0). "
    "Behavioral audit confirmed: empty/null/whitespace vcmd now rejected "
    "by plan_validator with code=invalid_verification_command; "
    "_auto_commit_accepted now reverts via git reset --hard HEAD~1 when "
    "vcmd is missing/empty/non-string and emits a verification_missing "
    "ledger row. No regressions in existing plans "
    "(plan_hooks_orchestrator_selfbuild_unblock.json: 0 errors). Hallucinated "
    "Gemini tasks t1-t5 in the plan file were correctly recognised by "
    "Claude reconciliation but remained in the merged plan; not extracted "
    "to queue. Closes the U1-class silent-NOOP failure mode end-to-end."
)


def main() -> int:
    rows = load_ledger()
    for r in rows[-50:]:
        if r.get("event") == "brief_closure" and r.get("task_id") == TASK_ID:
            print("brief_closure already filed; skipping.")
            return 0
    row = {
        "ts": now_iso(),
        "phase": "META",
        "task_id": TASK_ID,
        "event": "brief_closure",
        "detail": DETAIL,
        "files": [
            "brief_hooks_orchestrator_verification_required.md",
            "plan_hooks_orchestrator_verification_required.json",
            "harness/planner/plan_validator.py",
            "harness/orchestrator.py",
        ],
        "exit": 0,
    }
    write_jsonl_row(LEDGER_PATH, row)
    print(f"brief_closure filed for {TASK_ID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
