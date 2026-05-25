"""scripts/impl_file_webui_v2_scope_exception.py

Append a single scope_exception ledger row covering all the file paths the
WebUI v2 implementation (E1..E8 of plan_hooks_webui_full.json) will write
outside the META allow-list. Idempotent — checks the last 50 rows and skips
if an equivalent row already exists.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from impl_common import LEDGER_PATH, load_ledger, now_iso, write_jsonl_row  # type: ignore

PATHS = [
    "tools/webui_static/**",
    "tools/webui_control.py",
    "tools/webui_auth.py",
    "tools/webui_server.py",
    "harness/orchestrator.py",
    "harness/config.yaml",
    "state/control/**",
    "tests/integration/test_webui_static.py",
    "tests/integration/test_webui_control.py",
    "tests/integration/test_orchestrator_hitl.py",
    "docs/runbooks/webui-frontend.md",
    "scripts/impl_amend_webui_plan.py",
    "scripts/impl_file_webui_v2_scope_exception.py",
    "plan_hooks_webui_full.json",
    "plan_hooks_webui_full_critique.json",
    "plan_hooks_webui_full.json.pre-amend",
]
DETAIL = (
    "META-WEBUI-V2: operator-authorized end-to-end build of plan_hooks_webui_full.json "
    "(8 tasks, E1..E8). Adds control-plane endpoints, auth+CSRF middleware, "
    "browser SPA, orchestrator HITL hooks, integration+adversarial tests, and "
    "operator runbook. Plan validated post-amendment (drop t1-t5 + 9 critique "
    "patches). Operator: kevin.lindmark0@gmail.com."
)


def main() -> int:
    rows = load_ledger()
    for r in rows[-50:]:
        if (
            r.get("event") == "scope_exception"
            and r.get("task_id") == "META-WEBUI-V2"
            and set(r.get("paths", [])) == set(PATHS)
        ):
            print("scope_exception already filed; skipping.")
            return 0
    row = {
        "ts": now_iso(),
        "phase": "META",
        "task_id": "META-WEBUI-V2",
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
