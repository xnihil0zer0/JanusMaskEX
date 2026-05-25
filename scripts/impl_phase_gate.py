#!/usr/bin/env python3
"""Phase-gate CLI. Run `python3 scripts/impl_phase_gate.py P<N>` to attempt
transition to the next phase. Appends phase_gate_pass or phase_gate_fail.

See hooks-augmented §6. This is the only source that emits phase_gate_*
rows; never append them by hand.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from impl_common import (
    PROJECT_DIR,
    TASK_MANIFESTS,
    adv_satisfied,
    append_impl_progress_event,
    load_ledger,
    test_passed,
)

# Phase DoD commands from master plan §Phase 0 end. For later phases the
# commands are placeholders until the sub-plan task decomposer materialises
# them.
PHASE_DOD_COMMANDS: dict[str, list[list[str]]] = {
    "P0": [
        [sys.executable, "-m", "pytest",
         "tests/test_orchestrator.py", "tests/test_task_decomposer.py",
         "tests/test_cross_examiner.py", "tests/test_mcp_server.py", "-q"],
    ],
    # P1 — Phase 1 shared scaffolding (sub-plan 02 §3.2). The new hooks
    # modules live under tests/hooks; the pre-existing suites must also stay
    # green because HOOK-11/-12/-14 rewire harness/mcp_server.py.
    "P1": [
        [sys.executable, "-m", "pytest", "tests/hooks", "-q"],
        [sys.executable, "-m", "pytest",
         "tests/test_orchestrator.py", "tests/test_task_decomposer.py",
         "tests/test_cross_examiner.py", "tests/test_mcp_server.py",
         "tests/test_depth_validator.py", "-q"],
    ],
    # P2 — Claude worker hook entrypoints (sub-plan 02 §9). tests/hooks
    # now carries the per-hook unit coverage; the pre-existing suites guard
    # against regressions in mcp_server rewiring and orchestrator pairing.
    "P2": [
        [sys.executable, "-m", "pytest", "tests/hooks", "-q"],
        [sys.executable, "-m", "pytest",
         "tests/test_orchestrator.py", "tests/test_task_decomposer.py",
         "tests/test_cross_examiner.py", "tests/test_mcp_server.py",
         "tests/test_depth_validator.py", "-q"],
    ],
    # P3 — Gemini worker hook entrypoints (sub-plan 03 §3). Same shape as
    # P2: tests/hooks for per-hook unit coverage + pre-existing suites as
    # regression guard. Gemini modules import the shared rpc verbs so a
    # break in submit_code/plan_draft would surface in either suite.
    "P3": [
        [sys.executable, "-m", "pytest", "tests/hooks", "-q"],
        [sys.executable, "-m", "pytest",
         "tests/test_orchestrator.py", "tests/test_task_decomposer.py",
         "tests/test_cross_examiner.py", "tests/test_mcp_server.py",
         "tests/test_depth_validator.py", "-q"],
    ],
    # P4 — Orchestrator & streamer rewiring (sub-plan 04 §3 + §4). The
    # HOOK-46 invariants battery lives under tests/hooks/invariants and
    # is picked up by the tests/hooks sweep; the pre-existing suites
    # guard against regressions in orchestrator, cross_examiner, and
    # mcp_server rewiring as HOOK-41 flipped the worker config pointer.
    "P4": [
        [sys.executable, "-m", "pytest", "tests/hooks", "-q"],
        [sys.executable, "-m", "pytest",
         "tests/test_orchestrator.py", "tests/test_task_decomposer.py",
         "tests/test_cross_examiner.py", "tests/test_mcp_server.py",
         "tests/test_depth_validator.py", "-q"],
    ],
    # P5 -- Shadow / diff-gate / canary / rollback / drain-e2e (sub-plan 06
    # Phase 5 + Phase 6.1 drain precondition). The gate replays the HOOK-51
    # comparator against each of the three archived drain sessions
    # (brief_stab_001/003/005 per sub-plan 06 §1 step 5). Those comparator
    # invocations require the operator to stage shadow/<session>.jsonl +
    # MCP audit artefacts from a real drain rehearsal; the first enforce
    # flip stays human-only per sub-plan 06 §5 item 4, so this row
    # deliberately does not auto-pass until the operator runs the drain.
    "P5": [
        [sys.executable, "-m", "pytest", "tests/hooks", "-q"],
        [sys.executable, "-m", "pytest",
         "tests/test_orchestrator.py", "tests/test_task_decomposer.py",
         "tests/test_cross_examiner.py", "tests/test_mcp_server.py",
         "tests/test_depth_validator.py", "-q"],
        [sys.executable, "-m", "harness.hooks_equivalence", "stab_001"],
        [sys.executable, "-m", "harness.hooks_equivalence", "stab_003"],
        [sys.executable, "-m", "harness.hooks_equivalence", "stab_005"],
    ],
}


def _tasks_for_phase(phase: str) -> list[str]:
    return [tid for tid, m in TASK_MANIFESTS.items() if m.get("phase") == phase]


def _p5_rollback_precondition_check() -> list[str]:
    """Pre-rehearsal guard (B7 follow-up, master-plan B7).

    The P5 drain ceremony consumes state/hooks/rollback_signal and scans
    state/tasks/blocked/ for in-flight ROLLBACK-*.md stubs. A stale signal
    or stale blocked-report from test-dev time would be mis-read as a live
    rollback. Refuse the P5 gate unless both are clean.
    """
    failures: list[str] = []
    blocked_dir = PROJECT_DIR / "state" / "tasks" / "blocked"
    if blocked_dir.exists():
        stale = sorted(blocked_dir.glob("ROLLBACK-*.md"))
        if stale:
            failures.append(
                "stale rollback blocked-reports present (scrub before P5 rehearsal): "
                + ", ".join(str(p.relative_to(PROJECT_DIR)) for p in stale)
            )
    signal_path = PROJECT_DIR / "state" / "hooks" / "rollback_signal"
    if signal_path.exists():
        failures.append(
            f"rollback_signal present at {signal_path.relative_to(PROJECT_DIR)}; "
            "consume via apply_rollback or remove before P5 gate."
        )
    return failures


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write("usage: impl_phase_gate.py P<N>\n")
        return 2

    phase = sys.argv[1]
    ledger = load_ledger()

    # P5 pre-rehearsal guard: no stale rollback artefacts.
    if phase == "P5":
        rb_fail = _p5_rollback_precondition_check()
        if rb_fail:
            detail = "rollback precondition: " + "; ".join(rb_fail)
            append_impl_progress_event("phase_gate_fail", phase=phase, detail=detail[:300], exit_code=1)
            sys.stderr.write(
                "Phase gate P5 failed (rollback precondition):\n  "
                + "\n  ".join(rb_fail) + "\n"
            )
            return 1

    # Check all known tasks in this phase have test_pass + (adv_pass if required).
    missing: list[str] = []
    for tid in _tasks_for_phase(phase):
        manifest = TASK_MANIFESTS[tid]
        if not test_passed(ledger, tid):
            missing.append(f"{tid}: no test_pass")
        if manifest.get("adv_required") and not adv_satisfied(ledger, tid):
            missing.append(f"{tid}: no adv_pass")

    if missing:
        detail = "missing: " + "; ".join(missing)
        append_impl_progress_event("phase_gate_fail", phase=phase, detail=detail, exit_code=1)
        sys.stderr.write(f"Phase gate {phase} failed:\n  " + "\n  ".join(missing) + "\n")
        return 1

    # Run configured DoD commands.
    cmd_failures: list[str] = []
    for cmd in PHASE_DOD_COMMANDS.get(phase, []):
        try:
            proc = subprocess.run(cmd, cwd=str(PROJECT_DIR), capture_output=True, text=True)
            if proc.returncode != 0:
                cmd_failures.append(
                    f"{' '.join(cmd)} -> exit {proc.returncode}: "
                    f"{(proc.stdout or proc.stderr).strip()[-200:]}"
                )
        except OSError as e:
            cmd_failures.append(f"{' '.join(cmd)} -> OSError: {e}")

    if cmd_failures:
        detail = "cmd failures: " + " | ".join(cmd_failures)
        append_impl_progress_event("phase_gate_fail", phase=phase, detail=detail[:300], exit_code=1)
        sys.stderr.write("Phase gate DoD commands failed:\n  " + "\n  ".join(cmd_failures) + "\n")
        return 1

    append_impl_progress_event("phase_gate_pass", phase=phase, detail="all DoD commands green")
    sys.stdout.write(f"Phase gate {phase} PASSED.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
