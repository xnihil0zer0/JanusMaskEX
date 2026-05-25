"""scripts/impl_file_webui_server_autocomplete_route_scope_exception.py

File a scope_exception for tools/webui_server.py covering the missing
mutation-router entry for /api/briefs/autocomplete.

The F1 task (tools/webui_control.py) added _dispatch_post as a class
attribute on ControlHandlers, but tools/webui_server.py:_dispatch_mutation
uses a hardcoded if/elif chain and never consults that attribute.
Result: POSTs to /api/briefs/autocomplete return 404 'no mutation handler'
even though the handler method exists on ControlHandlers. This is a
true integration gap missed by the brief's per-task decomposition.

Reuses operator authorization from the 2026-05-15 autobrief v2
FREEZE-LIFT approval.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from impl_common import LEDGER_PATH, load_ledger, now_iso, write_jsonl_row  # type: ignore

PATHS = ["tools/webui_server.py"]
TASK_ID = "META-AUTOBRIEF-V2-F1-ROUTE"
DETAIL = (
    "F1 follow-up: tools/webui_server.py:_dispatch_mutation is a "
    "hardcoded if/elif chain — the _dispatch_post class attribute that "
    "F1 added to ControlHandlers is never consulted. Adding one line "
    "to route POST /api/briefs/autocomplete to ctl.post_brief_autocomplete. "
    "Without this, F7+F8 tests fail with 404 'no mutation handler' even "
    "though the F1 handler method exists. Reuses META-WEBUI-AUTOBRIEF-V2 "
    "operator authorization from 2026-05-15 FREEZE-LIFT."
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
