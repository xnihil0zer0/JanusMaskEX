#!/usr/bin/env python3
"""Adversarial verification of the targets_dir redpair diagnosis + fixes.

READ-ONLY on live state. Builds SYNTHETIC state trees in a tmp dir and calls
the REAL load_sibling_tasks + is_fix_forward_redpair from harness.redpair_acceptance,
and the REAL can_run_parallel from harness.autowork_parallelism.

Run: PYTHONPATH=/home/xnihil0zer0/JanusMaskJR python3 <thisfile>
"""
from __future__ import annotations
import json
import sys
import tempfile
import shutil
from pathlib import Path

REPO = Path("/home/xnihil0zer0/JanusMaskJR")
sys.path.insert(0, str(REPO))

from harness.redpair_acceptance import is_fix_forward_redpair, load_sibling_tasks
from harness import autowork_parallelism as awp

# ---- REAL task values pulled from the live plan + task JSONs ----
ORACLE = {
    "task_id": "targets-dir-convention-oracle",
    "meta_task_type": "test_authoring",
    "mutation_target": "harness.target_bootstrap",
    "dependencies": [],
    "files_touched": ["tests/harness/test_targets_dir_convention.py"],
    "verification_command": "python -m pytest tests/harness/test_targets_dir_convention.py -q",
}
IMPL = {
    "task_id": "targets-dir-convention-impl",
    "meta_task_type": "harness_self_fix",
    "mutation_target": None,
    "dependencies": ["targets-dir-convention-oracle"],
    "files_touched": ["harness/target_bootstrap.py"],
    "verification_command": "python -m pytest tests/harness/test_targets_dir_convention.py -q",
}

results = []
def check(label, got, expected):
    ok = (got == expected)
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}: got={got!r} expected={expected!r}")
    return ok

def make_state(impl_location):
    """Build a synthetic state tree. impl_location in {'base','processed','blocked'}.
    Returns (state_dir, worktree_root). worktree_root has a real harness/target_bootstrap.py
    so the mutation_target .py-exists check passes."""
    root = Path(tempfile.mkdtemp(prefix="adv_redpair_"))
    state = root / "state"
    wt = root / "worktree"
    (state / "tasks" / "processed").mkdir(parents=True)
    (state / "tasks" / "blocked").mkdir(parents=True)
    # worktree must contain harness/target_bootstrap.py for the mutation_target check
    (wt / "harness").mkdir(parents=True)
    (wt / "harness" / "target_bootstrap.py").write_text("# stub\n")
    # oracle always sits in base/queued (it is the task under acceptance)
    (state / "tasks" / "targets-dir-convention-oracle.json").write_text(json.dumps(ORACLE))
    # impl placement varies
    loc = {"base": state / "tasks", "processed": state / "tasks" / "processed",
           "blocked": state / "tasks" / "blocked"}[impl_location]
    (loc / "targets-dir-convention-impl.json").write_text(json.dumps(IMPL))
    return state, wt, root

def run_redpair(impl_location):
    state, wt, root = make_state(impl_location)
    try:
        sibs = load_sibling_tasks(str(state), ORACLE, "targets-dir-convention-oracle")
        sib_ids = sorted(t.get("task_id") for t in sibs)
        accepted = is_fix_forward_redpair(ORACLE, str(wt), sibs)
        return sib_ids, accepted
    finally:
        shutil.rmtree(root, ignore_errors=True)

print("=" * 70)
print("2(a) CRUX: impl in base/queued => accept; impl in blocked/ => reject")
print("=" * 70)
sib_base, acc_base = run_redpair("base")
check("impl in base: load_sibling_tasks finds impl", sib_base, ["targets-dir-convention-impl"])
check("impl in base: is_fix_forward_redpair accepts oracle RED", acc_base, True)

sib_proc, acc_proc = run_redpair("processed")
check("impl in processed: load_sibling_tasks finds impl", sib_proc, ["targets-dir-convention-impl"])
check("impl in processed: is_fix_forward_redpair accepts oracle RED", acc_proc, True)

sib_blk, acc_blk = run_redpair("blocked")
check("impl in blocked: load_sibling_tasks returns NO sibling", sib_blk, [])
check("impl in blocked: is_fix_forward_redpair REJECTS oracle", acc_blk, False)

print()
print("=" * 70)
print("2(b) Each of the 5 is_fix_forward_redpair conditions, real values, impl in base")
print("=" * 70)
state, wt, root = make_state("base")
try:
    sibs = load_sibling_tasks(str(state), ORACLE, "targets-dir-convention-oracle")
    # baseline: all conditions met
    check("baseline all-5-met accepts", is_fix_forward_redpair(ORACLE, str(wt), sibs), True)

    # cond1: meta_task_type must be test_authoring
    o = dict(ORACLE); o["meta_task_type"] = "harness_self_fix"
    check("cond1 non-test_authoring meta => reject", is_fix_forward_redpair(o, str(wt), sibs), False)

    # cond2: valid module mutation_target (no slash/.py)
    o = dict(ORACLE); o["mutation_target"] = "harness/target_bootstrap.py"
    check("cond2 path-style mutation_target => reject", is_fix_forward_redpair(o, str(wt), sibs), False)
    o = dict(ORACLE); o["mutation_target"] = "harness.does_not_exist_xyz"
    check("cond2b mutation_target .py absent in worktree => reject", is_fix_forward_redpair(o, str(wt), sibs), False)

    # cond3: oracle own_files non-empty
    o = dict(ORACLE); o["files_touched"] = []
    check("cond3 empty oracle files_touched => reject", is_fix_forward_redpair(o, str(wt), sibs), False)

    # cond4: sibling impl lists target_rel (harness/target_bootstrap.py) in files_touched
    bad_impl = dict(IMPL); bad_impl["files_touched"] = ["harness/other.py"]
    check("cond4 impl does NOT touch target_rel => reject", is_fix_forward_redpair(ORACLE, str(wt), [bad_impl]), False)

    # cond5: impl vcmd substring-contains the oracle's authored test file
    bad_impl2 = dict(IMPL); bad_impl2["verification_command"] = "python -m pytest tests/harness/other_test.py -q"
    check("cond5 impl vcmd lacks oracle test file => reject", is_fix_forward_redpair(ORACLE, str(wt), [bad_impl2]), False)

    # also: a test_authoring sibling does not count as impl
    ta_sib = dict(IMPL); ta_sib["meta_task_type"] = "test_authoring"
    check("sibling that is itself test_authoring => not counted => reject",
          is_fix_forward_redpair(ORACLE, str(wt), [ta_sib]), False)
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
print("=" * 70)
print("3(a) DEDUP: does file-overlap dedup conflict oracle vs impl?")
print("    Diagnosis claims mutation_target collides with impl files_touched.")
print("=" * 70)
# Real values: oracle.files_touched=[test file], impl.files_touched=[source file]
cr = awp.can_run_parallel(ORACLE, IMPL, all_tasks=[ORACLE, IMPL])
print(f"can_run_parallel(oracle, impl) with REAL files_touched = {cr}")
# Explain why
fo = awp._files_overlap(ORACLE["files_touched"], IMPL["files_touched"])
check("3a _files_overlap(oracle.files, impl.files) is FALSE (test vs source, no overlap)", fo, False)
# Does dedup use mutation_target at all?
import inspect
awp_src = inspect.getsource(awp)
uses_mt = "mutation_target" in awp_src
check("3a autowork_parallelism does NOT reference mutation_target", uses_mt, False)
# But there IS a transitive-dependency block (impl depends on oracle):
check("3a impl depends on oracle => can_run_parallel returns False (dep block, NOT file overlap)",
      cr, False)
print("    => They CANNOT run in parallel, but the REASON is the DEPENDENCY edge,")
print("       not a files_touched overlap and not mutation_target. Diagnosis's stated")
print("       mechanism (mutation_target collision) is the WRONG mechanism.")

print()
print("=" * 70)
print("3(b) PERMANENT FIX: simulate load_sibling_tasks ALSO scanning blocked/")
print("=" * 70)

def load_sibling_with_blocked(state_dir, task, task_id):
    """Reimplementation of load_sibling_tasks that ALSO scans state/tasks/blocked/.
    Mirrors the real function's dep + reverse-dep logic."""
    out = []
    sd = Path(state_dir)
    proc = sd / "tasks" / "processed"
    base = sd / "tasks"
    blocked = sd / "tasks" / "blocked"
    seen = set()
    dirs = (proc, base, blocked)  # <-- added blocked
    def _read(tid):
        if not isinstance(tid, str) or not tid or tid in seen:
            return
        seen.add(tid)
        for d in dirs:
            p = d / (tid + ".json")
            if p.is_file():
                out.append(json.loads(p.read_text()))
                return
    deps = task.get("dependencies") or []
    for tid in deps:
        _read(tid)
    for d in dirs:
        if not d.is_dir():
            continue
        for p in d.glob("*.json"):
            try:
                obj = json.loads(p.read_text())
            except Exception:
                continue
            if isinstance(obj, dict) and task_id in (obj.get("dependencies") or []):
                tid = obj.get("task_id") or p.stem
                if tid not in seen:
                    seen.add(tid)
                    out.append(obj)
    return out

state, wt, root = make_state("blocked")
try:
    # real loader: misses impl
    real_sibs = load_sibling_tasks(str(state), ORACLE, "targets-dir-convention-oracle")
    check("3b REAL loader with impl in blocked => no sibling", sorted(t.get("task_id") for t in real_sibs), [])
    check("3b REAL loader => reject", is_fix_forward_redpair(ORACLE, str(wt), real_sibs), False)
    # patched loader: finds impl in blocked
    patched_sibs = load_sibling_with_blocked(str(state), ORACLE, "targets-dir-convention-oracle")
    check("3b PATCHED loader (scans blocked) => finds impl",
          sorted(t.get("task_id") for t in patched_sibs), ["targets-dir-convention-impl"])
    check("3b PATCHED loader => ACCEPTS oracle RED", is_fix_forward_redpair(ORACLE, str(wt), patched_sibs), True)
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
print("=" * 70)
print("3(b)-downside: would scanning blocked/ WRONGLY accept against a DEAD sibling?")
print("    e.g. an .exhausted-marked blocked impl. Does redpair/loader exclude it?")
print("=" * 70)
# Build a state where impl is blocked AND has a .exhausted sidecar
root2 = Path(tempfile.mkdtemp(prefix="adv_redpair_exh_"))
state2 = root2 / "state"; wt2 = root2 / "worktree"
(state2 / "tasks" / "processed").mkdir(parents=True)
(state2 / "tasks" / "blocked").mkdir(parents=True)
(wt2 / "harness").mkdir(parents=True)
(wt2 / "harness" / "target_bootstrap.py").write_text("# stub\n")
(state2 / "tasks" / "targets-dir-convention-oracle.json").write_text(json.dumps(ORACLE))
(state2 / "tasks" / "blocked" / "targets-dir-convention-impl.json").write_text(json.dumps(IMPL))
# simulate an exhausted marker (common factory convention)
(state2 / "tasks" / "blocked" / "targets-dir-convention-impl.exhausted").write_text("")
try:
    patched = load_sibling_with_blocked(str(state2), ORACLE, "targets-dir-convention-oracle")
    found_dead = sorted(t.get("task_id") for t in patched)
    check("3b-downside naive blocked-scan INCLUDES exhausted dead sibling",
          found_dead, ["targets-dir-convention-impl"])
    accepted_dead = is_fix_forward_redpair(ORACLE, str(wt2), patched)
    check("3b-downside => would ACCEPT oracle against a DEAD impl (BAD if impl never lands)",
          accepted_dead, True)
    print("    => A naive blocked/-scan that ignores .exhausted CAN green-light an oracle")
    print("       whose impl is permanently dead. The permanent fix MUST exclude")
    print("       .exhausted-marked (and any terminally-dead) blocked tasks.")
finally:
    shutil.rmtree(root2, ignore_errors=True)

print()
print("=" * 70)
total = len(results); passed = sum(results)
print(f"SUMMARY: {passed}/{total} checks passed")
print("=" * 70)
sys.exit(0 if passed == total else 1)
