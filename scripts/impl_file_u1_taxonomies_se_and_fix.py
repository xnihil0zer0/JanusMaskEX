"""scripts/impl_file_u1_taxonomies_se_and_fix.py

File scope_exception for harness/planner/taxonomies.py under the
brief_hooks_orchestrator_selfbuild_unblock.md umbrella, then drop start/write
ledger rows for the META direct-impl that fixes U1's silent NOOP.

Background: U1 (commit ff5e361) was supposed to add `"skip_smoke_gates": True`
to the `harness_plumbing` and `hooks_integration` rows of META_TASK_POLICY,
matching the existing `harness_self_fix` carve-out. The orchestrator's
auto-commit landed a reformat-only change (compact one-line dict, single
quotes, blank lines stripped) with NO behavioral effect — the processed
task file is even tagged `.attempt1_silent_noop` as the orchestrator's
own breadcrumb. U3's `verification_command` enforcement was not yet live
at U1 commit time, so nothing caught the NOOP.

This SE authorizes one human-approved META direct-impl on
harness/planner/taxonomies.py to land the originally-intended change and
unblock the next-session multifmt-dispatch resume.

Consume_on: test_pass (the new ledger row asserting
SKIP_SMOKE_GATE_TYPES == {'harness_self_fix', 'harness_plumbing',
'hooks_integration'}).
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from impl_common import LEDGER_PATH, load_ledger, now_iso, write_jsonl_row  # type: ignore

TASK_ID = "META-SELFBUILD-U1-NOOP-FIX"
PATHS = ["harness/planner/taxonomies.py"]
SE_DETAIL = (
    "U1 (ff5e361) shipped as a silent NOOP — orchestrator's auto-commit "
    "landed a cosmetic reformat (compact one-line dict, single quotes, "
    "stripped blanks) with no behavior change; SKIP_SMOKE_GATE_TYPES "
    "remained ['harness_self_fix'] instead of the intended union with "
    "harness_plumbing + hooks_integration. The processed task file is "
    "tagged `.attempt1_silent_noop` confirming the orchestrator detected "
    "but did not block the no-op (U3 verification_command enforcement was "
    "not yet live at U1 commit time). META direct-impl to add the two "
    "missing 'skip_smoke_gates': True flags and restore the multi-line "
    "readable format. Authorization reuses the 2026-05-15 selfbuild brief "
    "FREEZE-LIFT umbrella (brief_hooks_orchestrator_selfbuild_unblock.md)."
)


def main() -> int:
    rows = load_ledger()
    for r in rows[-30:]:
        if (
            r.get("event") == "scope_exception"
            and r.get("task_id") == TASK_ID
            and set(PATHS).issubset(set(r.get("paths", [])))
        ):
            print("scope_exception already filed; skipping.")
            return 0
    se_row = {
        "ts": now_iso(),
        "phase": "META",
        "task_id": TASK_ID,
        "event": "scope_exception",
        "detail": SE_DETAIL,
        "files": [],
        "exit": 0,
        "paths": PATHS,
        "approved_by": "human",
        "consume_on": "test_pass",
    }
    write_jsonl_row(LEDGER_PATH, se_row)
    print(f"scope_exception filed: {PATHS} -> {LEDGER_PATH}")
    start_row = {
        "ts": now_iso(),
        "phase": "META",
        "task_id": TASK_ID,
        "event": "start",
        "detail": (
            "Add 'skip_smoke_gates': True to harness_plumbing + "
            "hooks_integration META_TASK_POLICY rows; restore multi-line "
            "readable format the orchestrator collapsed."
        ),
        "files": [],
        "exit": 0,
    }
    write_jsonl_row(LEDGER_PATH, start_row)
    print(f"start filed for {TASK_ID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
