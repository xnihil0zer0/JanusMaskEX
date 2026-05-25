"""scripts/impl_file_autobrief_v2_f7_f8_handler_test_fixes.py

Drop start/write/test_pass rows for META-AUTOBRIEF-V2-F7-F8-TESTFIX: test-side
fixes to land the 15 F1 handler-internal failures from session
2026-05-15_autobrief_v2_pivot without lifting the META freeze on
tools/webui_control.py.

What landed:
  - tests/integration/test_webui_control_autobrief.py
      * stub `echo` -> `printf '%s\\n'`; dash's XSI-compliant echo was
        converting JSON's `\\n` escapes to real newlines, producing invalid
        JSON and causing 502 autobrief_parse_failed everywhere.
      * test_concurrent_requests_distinct_job_ids: fetch fresh CSRF nonce per
        thread (single-use nonce was 403-ing 4 of 5 concurrent calls).
      * test_parse_failed_recovers_on_retry: per-test counter-file plumbed
        through TEST_AUTOBRIEF_COUNTER so the stub can distinguish first
        attempt (garbage) from retry (valid) without a retry-marker on stdin.
      * Three new stub modes (poisoned_traversal_slug, poisoned_env_slug,
        hang_with_stderr) used by the F8 rewrite.
  - tests/adversarial/test_webui_autobrief_adversarial.py
      * Dropped _StubProc + _spawn_fn mock; sidecar now uses real
        subprocess.Popen via PATH-staged stubs (mirrors F7).
      * Session-autouse stub_binaries fixture writes the same stub script
        F7 uses (so PATH lookups resolve regardless of which fixture wins).
      * Migrated spawn_calls assertions to on-disk job_dir counting.
      * test_timeout_sigterm_then_sigkill_with_stderr_tail: bumped
        autobrief_timeout_sec to 2 (handler does int() coercion so 0.5
        truncated to 0 and SIGTERM'd before the shell could flush stderr);
        relaxed elapsed budget to <12s (handler hardcodes a 5s SIGKILL
        grace).
      * test_20_concurrent_kickoffs_distinct_job_dirs: pre-fetch nonces
        sequentially to avoid 40 (csrf+POST) parallel connections.

Both target files are covered by existing active scope_exceptions
(META-WEBUI-AUTOBRIEF-V2 for the integration path, META-WEBUI-AUTOBRIEF-V2-F8
for the adversarial path) — no new SE filed; the handler at
tools/webui_control.py was NOT touched.

Verification: 137/137 in the webui test bundle (F7 21/21, F8 13/13 +
test_stdout_toctou_safe now passing rather than skipping; F1-F6 unchanged).
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from impl_common import LEDGER_PATH, load_ledger, now_iso, write_jsonl_row  # type: ignore

TASK_ID = "META-AUTOBRIEF-V2-F7-F8-TESTFIX"
FILES = [
    "tests/integration/test_webui_control_autobrief.py",
    "tests/adversarial/test_webui_autobrief_adversarial.py",
]
START_DETAIL = (
    "F7+F8 test-side fixes: dash echo->printf, fresh CSRF per concurrent call, "
    "retry-counter via env var, adversarial fixture rewrite to real "
    "subprocess+PATH stubs. No handler change; both files in active SE."
)
TEST_PASS_DETAIL = (
    "F7 21/21 + F8 13/13 green; full webui bundle 137/137 "
    "(tests/integration/test_webui_{control,server,auth,control_autobrief,"
    "static}.py + tests/adversarial/test_webui_{control,autobrief}_"
    "adversarial.py)."
)


def main() -> int:
    rows = load_ledger()
    last_30 = rows[-30:]
    has_test_pass = any(
        r.get("event") == "test_pass" and r.get("task_id") == TASK_ID
        for r in last_30
    )
    if has_test_pass:
        print("test_pass already filed for this task; skipping.")
        return 0

    for event, detail, files in (
        ("start", START_DETAIL, []),
        ("write", "", FILES),
        ("test_pass", TEST_PASS_DETAIL, FILES),
    ):
        row = {
            "ts": now_iso(),
            "phase": "META",
            "task_id": TASK_ID,
            "event": event,
            "detail": detail,
            "files": files,
            "exit": 0,
        }
        write_jsonl_row(LEDGER_PATH, row)
        print(f"appended {event} for {TASK_ID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
