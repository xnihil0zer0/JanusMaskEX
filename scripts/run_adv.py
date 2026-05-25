#!/usr/bin/env python3
"""Adversarial test runner. Run `python3 scripts/run_adv.py <phase>` to
execute the phase's adversarial battery and append adv_pass/adv_fail rows.

Looks under tests/adversarial/test_<phase>_*.py. The META phase uses
tests/adversarial/test_meta_hooks.py.

See hooks-augmented §5.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from impl_common import PROJECT_DIR, append_impl_progress_event, derive_state, load_ledger


def _adv_paths(phase: str) -> list[str]:
    adv_dir = PROJECT_DIR / "tests" / "adversarial"
    if not adv_dir.exists():
        return []
    if phase == "META":
        p = adv_dir / "test_meta_hooks.py"
        return [str(p)] if p.exists() else []
    prefix = f"test_{phase}_"
    return sorted(str(p) for p in adv_dir.glob(f"{prefix}*.py"))


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write("usage: run_adv.py <phase>\n")
        return 2
    phase = sys.argv[1]
    paths = _adv_paths(phase)
    if not paths:
        sys.stderr.write(f"No adversarial tests found for phase {phase}.\n")
        append_impl_progress_event("adv_fail", phase=phase, detail="no adv tests found", exit_code=1)
        return 1

    ledger = load_ledger()
    state = derive_state(ledger)
    task = state["current_task_id"]

    cmd = [sys.executable, "-m", "pytest", "-q"] + paths
    try:
        proc = subprocess.run(cmd, cwd=str(PROJECT_DIR), capture_output=True, text=True)
    except OSError as e:
        append_impl_progress_event("adv_fail", phase=phase, task_id=task,
                     detail=f"pytest launch failed: {e}", exit_code=-1)
        sys.stderr.write(f"pytest launch failed: {e}\n")
        return 1

    tail = (proc.stdout or proc.stderr).strip().splitlines()
    detail = " | ".join(tail[-5:])[:300]
    event = "adv_pass" if proc.returncode == 0 else "adv_fail"
    append_impl_progress_event(event, phase=phase, task_id=task, detail=detail,
                 files=paths, exit_code=proc.returncode)
    sys.stdout.write((proc.stdout or "") + (proc.stderr or ""))
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
