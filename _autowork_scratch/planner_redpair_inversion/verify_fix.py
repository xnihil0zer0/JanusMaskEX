#!/usr/bin/env python3
"""Validate the PROPOSED minimal fix for _enforce_module_first.

Fix: in the carve-out, drop the is_file() (and now-unused `repo_root is not None`)
precondition so the carve-out fires whenever the impl's verification_command
substring-names an oracle-authored test file -- regardless of module-on-disk.

We do NOT edit harness/** (the fix ships through the pipeline). Instead we
install a PATCHED _enforce_module_first into the live module object so the rest
of normalize_plan's pipeline is exercised unchanged, then re-run the three cases.
"""
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import harness.planner.plan_normalizer as pn
from harness.planner.plan_normalizer import normalize_plan

MODULE_DOTTED = "ngv2.fsm_evidence"
MODULE_REL = MODULE_DOTTED.replace(".", "/") + ".py"
TEST_FILE = "tests/ngv2/test_fsm_evidence.py"
TEST_VCMD = f"python -m pytest {TEST_FILE} -q"
OTHER_VCMD = "python -m pytest tests/ngv2/test_unrelated_smoke.py -q"


def _patched_enforce_module_first(tasks, repo_root=None):
    """PROPOSED FIX: carve-out no longer requires module on disk."""
    oracles = sorted((t for t in tasks if isinstance(t, dict) and pn._is_test_authoring(t) and pn._mutation_target(t)), key=pn._task_id)
    for oracle in oracles:
        target = pn._mutation_target(oracle)
        impl = pn._impl_for_module(tasks, pn._module_path(target))
        if impl is None:
            continue
        oid = pn._task_id(oracle)
        iid = pn._task_id(impl)
        if not oid or not iid or oid == iid:
            continue
        # FIXED carve-out: the impl's verification_command naming one of THIS
        # oracle's authored test files IS the fix-forward red-pair signal, for
        # both EXISTING and NEW modules. (Dropped the is_file() precondition.)
        _vc = impl.get('verification_command')
        if isinstance(_vc, str) and _vc:
            _ofiles = [f for f in pn._files_touched(oracle) if isinstance(f, str) and f]
            if any(of in _vc for of in _ofiles):
                continue
        oracle_deps = oracle.get('dependencies')
        if not isinstance(oracle_deps, list):
            oracle_deps = []
            oracle['dependencies'] = oracle_deps
        if iid not in oracle_deps:
            oracle_deps.append(iid)
        impl_deps = impl.get('dependencies')
        if isinstance(impl_deps, list) and oid in impl_deps:
            impl['dependencies'] = [d for d in impl_deps if d != oid]
        while True:
            graph = pn._build_graph(tasks)
            if not pn._reaches(graph, iid, oid):
                break
            current = impl.get('dependencies')
            if not isinstance(current, list) or not current:
                break
            removed = False
            for d in sorted(current):
                if d == oid or pn._reaches(graph, d, oid):
                    impl['dependencies'] = [x for x in current if x != d]
                    removed = True
                    break
            if not removed:
                break


# Install the patched function so normalize_plan calls it.
pn._enforce_module_first = _patched_enforce_module_first


def build_plan(impl_vcmd, oracle_deps, impl_deps):
    return {
        "plan_id": "repro",
        "tasks": [
            {"task_id": "fsm-oracle", "meta_task_type": "test_authoring",
             "mutation_target": MODULE_DOTTED, "files_touched": [TEST_FILE],
             "dependencies": list(oracle_deps), "verification_command": TEST_VCMD},
            {"task_id": "fsm-impl", "meta_task_type": "harness_self_fix",
             "mutation_target": None, "files_touched": [MODULE_REL],
             "dependencies": list(impl_deps), "verification_command": impl_vcmd},
        ],
    }


def deps_of(plan, tid):
    for t in plan["tasks"]:
        if t.get("task_id") == tid:
            return t.get("dependencies")
    return "<MISSING>"


def run(label, impl_vcmd, module_present, expect_preserved):
    with tempfile.TemporaryDirectory() as root:
        root_p = Path(root)
        if module_present:
            m = root_p / MODULE_REL
            m.parent.mkdir(parents=True, exist_ok=True)
            m.write_text("# present\n")
        out = normalize_plan(build_plan(impl_vcmd, [], ["fsm-oracle"]), repo_root=str(root_p))
        o, i = deps_of(out, "fsm-oracle"), deps_of(out, "fsm-impl")
        preserved = (o == []) and (i == ["fsm-oracle"])
        inverted = (o == ["fsm-impl"]) and (i == [])
        state = "PRESERVED" if preserved else ("INVERTED" if inverted else f"OTHER(o={o},i={i})")
        ok = preserved == expect_preserved
        print(f"=== {label} ===")
        print(f"  module_present={module_present} vc={impl_vcmd!r}")
        print(f"  OUTPUT: oracle.deps={o!r} impl.deps={i!r}  -> {state}")
        print(f"  expect_preserved={expect_preserved}  -> {'PASS' if ok else 'FAIL!!!'}")
        print()
        return ok


def main():
    print("######## PROPOSED-FIX VALIDATION (patched _enforce_module_first) ########\n")
    a = run("FIX/A: new module ABSENT, vc names oracle test", TEST_VCMD, False, expect_preserved=True)
    b = run("FIX/B: existing module PRESENT, vc names oracle test", TEST_VCMD, True, expect_preserved=True)
    c = run("FIX/C: NEGATIVE non-red-pair, module ABSENT (must still invert)", OTHER_VCMD, False, expect_preserved=False)

    # repo_root=None regression: prior behaviour for None was "no carve-out at all".
    # Under the fix, the carve-out no longer depends on repo_root, so a red-pair
    # is now preserved even with repo_root=None. Confirm a NON-red-pair still inverts.
    out_none_rp = normalize_plan(build_plan(TEST_VCMD, [], ["fsm-oracle"]), repo_root=None)
    on_rp, in_rp = deps_of(out_none_rp, "fsm-oracle"), deps_of(out_none_rp, "fsm-impl")
    out_none_nrp = normalize_plan(build_plan(OTHER_VCMD, [], ["fsm-oracle"]), repo_root=None)
    on_nrp, in_nrp = deps_of(out_none_nrp, "fsm-oracle"), deps_of(out_none_nrp, "fsm-impl")
    print("=== FIX/None: repo_root=None ===")
    print(f"  red-pair     -> oracle.deps={on_rp!r} impl.deps={in_rp!r}  (expect preserved)")
    print(f"  non-red-pair -> oracle.deps={on_nrp!r} impl.deps={in_nrp!r}  (expect inverted)")
    none_ok = (on_rp == [] and in_rp == ["fsm-oracle"]) and (on_nrp == ["fsm-impl"] and in_nrp == [])
    print(f"  -> {'PASS' if none_ok else 'FAIL!!!'}")
    print()

    print("==================== SUMMARY ====================")
    allok = a and b and c and none_ok
    print(f"FIX/A new-module red-pair now PRESERVED : {'PASS' if a else 'FAIL'}")
    print(f"FIX/B existing-module red-pair PRESERVED: {'PASS' if b else 'FAIL'}")
    print(f"FIX/C non-red-pair STILL INVERTS (narrow): {'PASS' if c else 'FAIL'}")
    print(f"FIX/None repo_root=None consistent      : {'PASS' if none_ok else 'FAIL'}")
    print()
    print(f"FIX VERDICT: {'CORRECT AND NARROW' if allok else 'PROBLEM'}")


if __name__ == "__main__":
    main()
