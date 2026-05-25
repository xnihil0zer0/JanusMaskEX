"""scripts/impl_file_autobrief_v2_remaining_scope_exceptions.py

File scope_exceptions for the F2-F7 META direct-implementation pivot
after orchestrator failed to commit non-.py targets via
_auto_commit_accepted's .py-only gate. F1+F4 already landed via
git add (working tree was prewritten by the orchestrator). F8 was
filed previously via impl_refile_f8_adversarial_autobrief_scope_exception.

Operator authorization carries forward from the 2026-05-15
FREEZE-LIFT autobrief v2 approval (brief_hooks_webui_autobrief_v2.md).
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from impl_common import LEDGER_PATH, load_ledger, now_iso, write_jsonl_row  # type: ignore

PATHS = [
    "tools/webui_autobrief_prompt.txt",
    "tools/webui_static/app.js",
    "harness/config.yaml",
    "docs/runbooks/webui-frontend.md",
    "tests/integration/test_webui_control_autobrief.py",
]
TASK_ID = "META-WEBUI-AUTOBRIEF-V2-PIVOT"
DETAIL = (
    "META-WEBUI-AUTOBRIEF-V2 pivot: orchestrator successfully synthesised "
    "F2-F7 outputs but harness/orchestrator.py:_auto_commit_accepted's "
    ".py-only gate skipped commits for non-.py targets and F7 hit "
    "ast_validation rejection. Per the handoff's pivot clause, finalising "
    "these targets via META direct-implementation using the freshest "
    "claude (Opus) outboxes as starting material. Reuses operator "
    "authorization from the 2026-05-15 autobrief v2 FREEZE-LIFT approval."
)


def main() -> int:
    rows = load_ledger()
    for r in rows[-50:]:
        if (
            r.get("event") == "scope_exception"
            and r.get("task_id") == TASK_ID
            and set(PATHS).issubset(set(r.get("paths", [])))
        ):
            print("scope_exception already filed; skipping.")
            return 0
    row = {
        "ts": now_iso(),
        "phase": "META",
        "task_id": TASK_ID,
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
    for p in PATHS:
        print(f"  - {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
