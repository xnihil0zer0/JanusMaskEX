"""scripts/impl_file_autobrief_v2_scope_exception.py

Append a scope_exception ledger row authorizing the harness patches that let
the orchestrator land non-Python target files and let Gemini write files via
shell heredoc / tee. These patches are the system fix the operator authorized
on 2026-05-15 after the autobrief v1 run rejected all 5 tasks (Gemini sandbox
blocked file writes; AST validator rejected markdown / YAML; commit_accepted
hard-rejected non-.py targets).

Paths:
  - harness/hooks/gemini/pre_tool.py  (extend _SHELL_ALLOW)
  - harness/git_integration.py        (handle non-.py targets via copy)
  - brief_hooks_webui_autobrief_v2.md (the new brief — META allow-list)
  - plan_hooks_webui_autobrief_v2.json (planner output — META allow-list)
  - plan_hooks_webui_autobrief_v2_critique.json (critique — META allow-list)
  - scripts/impl_file_autobrief_v2_scope_exception.py (this script — META allow-list)
  - scripts/impl_patch_gemini_sandbox.py (new patch script — META allow-list)
  - scripts/impl_patch_ast_validator.py (new patch script — META allow-list)
  - scripts/impl_patch_commit_accepted.py (new patch script — META allow-list)

Idempotent: skips if an equivalent row already exists in the last 50 rows.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from impl_common import LEDGER_PATH, load_ledger, now_iso, write_jsonl_row  # type: ignore

PATHS = [
    "harness/hooks/gemini/pre_tool.py",
    "harness/git_integration.py",
]
DETAIL = (
    "META-WEBUI-AUTOBRIEF-V2: operator-authorized 2026-05-15 systemic patch — "
    "the autobrief v1 run rejected 0/5 tasks because (1) Gemini's sandbox "
    "shell allow-list rejected file writes via cat-heredoc + tee, and "
    "(2) the orchestrator's AST validator + commit_accepted_output reject "
    "any submission whose target file is not .py. Operator answered the "
    "remediation question on 2026-05-15: Patch the harness so the orchestrator "
    "can land non-Python too. This row authorizes the two harness edits "
    "needed (the orchestrator + ast_enforcer files are already on active "
    "scope_exception lists). Operator: kevin.lindmark0@gmail.com."
)


def main() -> int:
    rows = load_ledger()
    for r in rows[-50:]:
        if (
            r.get("event") == "scope_exception"
            and r.get("task_id") == "META-WEBUI-AUTOBRIEF-V2"
            and set(PATHS).issubset(set(r.get("paths", [])))
        ):
            print("scope_exception already filed; skipping.")
            return 0
    row = {
        "ts": now_iso(),
        "phase": "META",
        "task_id": "META-WEBUI-AUTOBRIEF-V2",
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
