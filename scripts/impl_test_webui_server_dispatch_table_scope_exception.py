import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import impl_common

row = {
    "ts": impl_common.now_iso(),
    "phase": "META",
    "task_id": "F6_dispatch_contract_tests",
    "event": "scope_exception",
    "detail": "TestDispatchTable scope exception",
    "files": [],
    "exit": 0,
    "paths": ["tests/integration/test_webui_server.py"],
    "approved_by": "human",
    "consume_on": "test_pass",
}
impl_common.write_jsonl_row(impl_common.LEDGER_PATH, row)
