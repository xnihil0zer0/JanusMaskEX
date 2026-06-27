#!/usr/bin/env python3
"""Empirical reproduction of the _enforce_module_first new-module red-pair inversion.

Builds a minimal 2-task red-pair plan (test_authoring oracle for a NEW module +
impl that CREATES that module, vcmd runs the oracle's authored test) in the
CORRECT direction (oracle.deps=[], impl.deps=[oracle]) and runs it through
harness.planner.plan_normalizer.normalize_plan under several repo_root conditions.

CASE A (BUG): module file ABSENT on disk  -> expect INVERSION (oracle.deps=[impl], impl.deps=[]).
CASE B (CONTROL): module file PRESENT      -> expect NO inversion (direction preserved).
CASE C (NEGATIVE/REGRESSION): genuine non-red-pair (impl vc does NOT name oracle's
        test file), module ABSENT          -> expect INVERSION (correct: a real
        oracle-first build needs module-first; the carve-out must NOT fire here).
"""
import os
import sys
import copy
import tempfile
from pathlib import Path

# Run from the repo root so `import harness...` resolves.
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from harness.planner.plan_normalizer import normalize_plan

MODULE_DOTTED = "ngv2.fsm_evidence"
MODULE_REL = MODULE_DOTTED.replace(".", "/") + ".py"        # ngv2/fsm_evidence.py
TEST_FILE = "tests/ngv2/test_fsm_evidence.py"
TEST_VCMD = f"python -m pytest {TEST_FILE} -q"
OTHER_VCMD = "python -m pytest tests/ngv2/test_unrelated_smoke.py -q"  # does NOT name oracle test


def build_plan(impl_vcmd):
    """Correct-direction red-pair: oracle.deps=[], impl.deps=[oracle]."""
    return {
        "plan_id": "repro",
        "tasks": [
            {
                "task_id": "fsm-oracle",
                "meta_task_type": "test_authoring",
                "mutation_target": MODULE_DOTTED,
                "files_touched": [TEST_FILE],
                "dependencies": [],
                "verification_command": TEST_VCMD,
            },
            {
                "task_id": "fsm-impl",
                "meta_task_type": "harness_self_fix",
                "mutation_target": None,
                "files_touched": [MODULE_REL],
                "dependencies": ["fsm-oracle"],
                "verification_command": impl_vcmd,
            },
        ],
    }


def deps_of(plan, tid):
    for t in plan["tasks"]:
        if t.get("task_id") == tid:
            return t.get("dependencies")
    return "<MISSING>"


def run_case(label, impl_vcmd, module_present, expect_inversion):
    with tempfile.TemporaryDirectory() as root:
        root_p = Path(root)
        if module_present:
            mod = root_p / MODULE_REL
            mod.parent.mkdir(parents=True, exist_ok=True)
            mod.write_text("# present\n")
        plan = build_plan(impl_vcmd)
        out = normalize_plan(plan, repo_root=str(root_p))
        o_deps = deps_of(out, "fsm-oracle")
        i_deps = deps_of(out, "fsm-impl")
        inverted = (o_deps == ["fsm-impl"]) and (i_deps == [])
        preserved = (o_deps == []) and (i_deps == ["fsm-oracle"])
        print(f"=== {label} ===")
        print(f"  module_present_on_disk = {module_present}")
        print(f"  impl.verification_command = {impl_vcmd!r}")
        print(f"  INPUT : oracle.deps=[]            impl.deps=['fsm-oracle']")
        print(f"  OUTPUT: oracle.deps={o_deps!r}  impl.deps={i_deps!r}")
        if inverted:
            print("  -> RESULT: INVERTED (oracle-first; impl fires before test authored => DEADLOCK)")
        elif preserved:
            print("  -> RESULT: PRESERVED (correct red-pair direction)")
        else:
            print(f"  -> RESULT: OTHER (o={o_deps!r}, i={i_deps!r})")
        outcome_inversion = inverted
        ok = (outcome_inversion == expect_inversion)
        print(f"  expect_inversion={expect_inversion}  observed_inversion={outcome_inversion}  -> {'AS-EXPECTED' if ok else 'UNEXPECTED!!!'}")
        print()
        return ok, inverted, preserved


def main():
    results = {}
    results["A"] = run_case(
        "CASE A (BUG: new module ABSENT, vc names oracle test)",
        TEST_VCMD, module_present=False, expect_inversion=True)
    results["B"] = run_case(
        "CASE B (CONTROL: existing module PRESENT, vc names oracle test)",
        TEST_VCMD, module_present=True, expect_inversion=False)
    results["C"] = run_case(
        "CASE C (NEGATIVE: module ABSENT, vc does NOT name oracle test)",
        OTHER_VCMD, module_present=False, expect_inversion=True)

    print("==================== SUMMARY ====================")
    a_ok, a_inv, _ = results["A"]
    b_ok, _, b_pres = results["B"]
    c_ok, c_inv, _ = results["C"]
    print(f"CASE A (bug reproduces inversion)        : {'CONFIRMED' if a_inv else 'NOT REPRODUCED'}")
    print(f"CASE B (control preserves direction)     : {'CONFIRMED' if b_pres else 'NOT PRESERVED'}")
    print(f"CASE C (negative still inverts)          : {'CONFIRMED' if c_inv else 'DID NOT INVERT'}")
    verdict = a_inv and b_pres and c_inv
    print()
    print(f"VERDICT: {'DEFECT VERIFIED' if verdict else 'INCONCLUSIVE/REFUTED'}")
    print("  (A: new-module red-pair INVERTS today; B: on-disk module is carved out;")
    print("   C: a genuine non-red-pair still inverts => any fix that drops is_file()")
    print("      must KEEP inverting C, only stop inverting A.)")


if __name__ == "__main__":
    main()
