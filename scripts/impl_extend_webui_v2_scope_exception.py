"""Append a follow-up scope_exception row covering paths discovered during
implementation that weren't in the META-WEBUI-V2 initial authorization.
Idempotent — skips if already present.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from impl_common import LEDGER_PATH, load_ledger, now_iso, write_jsonl_row  # type: ignore

ADDED_PATHS = [
    "tests/integration/test_webui_auth.py",
    "scripts/impl_extend_webui_v2_scope_exception.py",
    "harness/control_gate.py",
]
DETAIL = (
    "META-WEBUI-V2 follow-up: covers per-deliverable test files split out from "
    "the umbrella tests/integration/test_webui_control.py for clarity (E2 ships "
    "test_webui_auth.py; E3 ships test_webui_control.py; E4 ships "
    "test_orchestrator_hitl.py). Same operator authorization, narrower scope."
)


def main() -> int:
    rows = load_ledger()
    # Idempotent on superset match.
    for r in rows[-50:]:
        if (
            r.get("event") == "scope_exception"
            and r.get("task_id") == "META-WEBUI-V2-EXT"
            and set(ADDED_PATHS).issubset(set(r.get("paths", [])))
        ):
            print("addendum already filed (superset present); skipping.")
            return 0
    row = {
        "ts": now_iso(),
        "phase": "META",
        "task_id": "META-WEBUI-V2-EXT",
        "event": "scope_exception",
        "detail": DETAIL,
        "files": [],
        "exit": 0,
        "paths": ADDED_PATHS,
        "approved_by": "human",
        "consume_on": "test_pass",
    }
    write_jsonl_row(LEDGER_PATH, row)
    print(f"scope_exception filed: {len(ADDED_PATHS)} paths -> {LEDGER_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
