#!/usr/bin/env python3
"""PostToolUse:Write|Edit meta-hook. Records writes, runs pytest --collect-only
on the nearest test module. Never blocks; only appends ledger rows.

See hooks-augmented-hooks-implementation-plan.md §3.1.
"""

from __future__ import annotations

import ast
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from impl_common import (
    PROJECT_DIR,
    append_impl_progress_event,
    derive_state,
    load_ledger,
)


def _rel_to_project(file_path: str) -> str | None:
    try:
        abs_path = pathlib.Path(file_path)
        if not abs_path.is_absolute():
            abs_path = (PROJECT_DIR / abs_path).resolve()
        else:
            abs_path = abs_path.resolve()
        return str(abs_path.relative_to(PROJECT_DIR.resolve()))
    except (ValueError, OSError):
        return None


def _nearest_test(rel_path: str) -> str | None:
    p = pathlib.Path(rel_path)
    if rel_path.startswith("tests/") and p.name.startswith("test_") and p.suffix == ".py":
        return rel_path
    if rel_path.startswith("harness/") and rel_path.endswith(".py"):
        return f"tests/test_{p.stem}.py"
    return None


def _collect_only(test_rel: str) -> tuple[int, str]:
    full = PROJECT_DIR / test_rel
    if not full.exists():
        return 4, f"test module absent: {test_rel}"
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", str(full)],
            capture_output=True, text=True, timeout=60, cwd=str(PROJECT_DIR),
        )
        return proc.returncode, (proc.stdout or proc.stderr).strip()[-200:]
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, f"collect-only invocation failed: {e}"


def main() -> int:
    try:
        raw = sys.stdin.read()
        inp = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        sys.exit(0)

    tool_input = inp.get("tool_input") or {}
    file_path = tool_input.get("file_path", "") or ""
    if not file_path:
        sys.exit(0)

    rel = _rel_to_project(file_path)
    if rel is None:
        sys.exit(0)

    ledger = load_ledger()
    state = derive_state(ledger)
    task = state["current_task_id"]
    phase = state["current_phase"]

    # Always append a write row.
    append_impl_progress_event("write", task_id=task, phase=phase, files=[rel])

    # If .py under harness/ or tests/ or scripts/, run ast.parse on disk.
    abs_path = PROJECT_DIR / rel
    if rel.endswith(".py") and abs_path.exists() and rel.startswith(("harness/", "tests/", "scripts/")):
        try:
            ast.parse(abs_path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as e:
            append_impl_progress_event(
                "test_fail", task_id=task, phase=phase,
                detail=f"ast.parse failed on {rel}: {e}", files=[rel], exit_code=1,
            )
            sys.exit(0)

    test_rel = _nearest_test(rel)
    if test_rel is None:
        sys.exit(0)

    code, detail = _collect_only(test_rel)
    event = "test_pass" if code == 0 else "test_fail"
    append_impl_progress_event(event, task_id=task, phase=phase, detail=detail, files=[test_rel], exit_code=code)
    sys.exit(0)


if __name__ == "__main__":
    sys.exit(main() or 0)
