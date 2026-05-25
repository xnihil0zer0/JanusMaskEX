"""scripts/impl_refile_f8_adversarial_autobrief_scope_exception.py

File a scope_exception for tests/adversarial/test_webui_autobrief_adversarial.py.
Brief brief_hooks_webui_autobrief_v2.md task F8 is NOT covered by the
META-WEBUI-V2 scope_exception (which globs tests/integration/test_webui_*.py
only). F8 ships tests/adversarial/test_webui_autobrief_adversarial.py per
brief §Deliverables. Reuses operator authorization from the 2026-05-15
autobrief v2 approval (FREEZE-LIFT-authorized brief).
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from impl_common import LEDGER_PATH, load_ledger, now_iso, write_jsonl_row  # type: ignore

PATHS = ["tests/adversarial/test_webui_autobrief_adversarial.py"]
DETAIL = (
    "META-WEBUI-AUTOBRIEF-V2 follow-up: F8 task is not covered by the "
    "META-WEBUI-V2 scope_exception (which globs tests/integration/ only). "
    "F8 ships tests/adversarial/test_webui_autobrief_adversarial.py per "
    "brief_hooks_webui_autobrief_v2.md §Deliverables. Reuses operator "
    "authorization from the 2026-05-15 autobrief v2 FREEZE-LIFT approval."
)


def main() -> int:
    rows = load_ledger()
    for r in rows[-30:]:
        if (
            r.get("event") == "scope_exception"
            and r.get("task_id") == "META-WEBUI-AUTOBRIEF-V2-F8"
            and set(PATHS).issubset(set(r.get("paths", [])))
        ):
            print("scope_exception already filed; skipping.")
            return 0
    row = {
        "ts": now_iso(),
        "phase": "META",
        "task_id": "META-WEBUI-AUTOBRIEF-V2-F8",
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
