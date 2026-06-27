#!/usr/bin/env python3
"""WORKS-demo for the smoke-gated diff-fuzz routing fix (commits 95c2d3d + 901d074).

Read-only on production. Imports the REAL committed harness functions and
exercises them. No reimplementation. Every PASS/FAIL line is produced by the
live function's actual return value.

Cases:
  (a) EXTERNAL UNFUZZABLE survivor (ngv2/ files_touched + socket hint) ->
      smoke_gated=True, real meta_task_type kept, _task_bypasses_fuzz True (BYPASS).
  (b) ANTI-CATCH-ALL: EXTERNAL FUZZABLE survivor (pure stdlib, non-ngv2 path,
      no socket hint) -> NO smoke_gated, real type kept, _task_bypasses_fuzz False (FUZZED).
  (c) ac505d7 PRESERVED: plain data_model, no smoke_gated -> _task_bypasses_fuzz False (FUZZED);
      'data_model' not in BYPASS_FUZZER_TYPES.
  (d) JM-SELF no-op: repo_root == PROJECT_ROOT -> no flag set.
"""
import copy
import os
import sys
import tempfile
from pathlib import Path

# Ensure repo root on path
REPO = Path(__file__).resolve().parents[3]  # .../JanusMaskJR
sys.path.insert(0, str(REPO))

from harness.planner.plan_normalizer import _force_smoke_gated_leaf_impl  # REAL
from harness.orchestrator_worker import _task_bypasses_fuzz  # REAL
from harness.planner.taxonomies import BYPASS_FUZZER_TYPES, META_TASK_POLICY
from harness.paths import PROJECT_ROOT

results = []


def record(name, passed, detail):
    tag = "PASS" if passed else "FAIL"
    results.append(passed)
    print(f"[{tag}] {name}: {detail}")


def make_external_root():
    """Create a temp EXTERNAL repo_root (outside PROJECT_ROOT) with a real
    oracle .py file so _oracle_set resolves and grouping fires."""
    d = tempfile.mkdtemp(prefix="ext_repo_")
    # oracle file that the verification_command will reference
    (Path(d) / "tests").mkdir(parents=True, exist_ok=True)
    (Path(d) / "tests" / "test_oracle.py").write_text("def test_x():\n    assert True\n")
    return d


# -------- helper to build a faithful minimal plan that drives the collapse --------
# The real function groups tasks by their _oracle_set: the set of `.py` tokens in
# `verification_command` that resolve to a real file under repo_root. A group needs
# >=1 impl candidate (meta_task_type NOT in the oracle/test set) to pick a survivor.
# We give a single impl task whose vcmd references the real oracle file, so it is its
# own group and becomes the survivor.

def build_plan(survivor_extra):
    base = {
        "task_id": "impl-1",
        "meta_task_type": survivor_extra.get("meta_task_type", "data_model"),
        "verification_command": "pytest tests/test_oracle.py -q",
    }
    base.update(survivor_extra)
    return {"tasks": [base]}


print("=" * 72)
print("Pre-flight: live policy facts")
print("=" * 72)
print(f"PROJECT_ROOT = {PROJECT_ROOT}")
print(f"BYPASS_FUZZER_TYPES = {sorted(BYPASS_FUZZER_TYPES)}")
print(f"'data_model' in BYPASS_FUZZER_TYPES = {'data_model' in BYPASS_FUZZER_TYPES}")
print(f"META_TASK_POLICY['data_model'] = {META_TASK_POLICY.get('data_model')}")
print()

# ============================================================
# CASE (a): EXTERNAL UNFUZZABLE survivor
# ============================================================
print("=" * 72)
print("CASE (a): EXTERNAL UNFUZZABLE survivor (ngv2/ + socket hint)")
print("=" * 72)
ext_root = make_external_root()
plan_a = build_plan({
    "meta_task_type": "data_model",  # real type that ac505d7 makes FUZZED
    "files_touched": ["ngv2/workers/_runner.py"],  # ngv2/ unfuzzability signal
    "specification": "Open a loopback server_socket and listen() for the runner.",  # socket hint
})
orig_mtt_a = plan_a["tasks"][0]["meta_task_type"]
# DISCRIMINATOR: prove the flag is load-bearing — without it, this exact survivor
# (real type data_model, which ac505d7 fuzzes) WOULD be diff-fuzzed.
pre_bypass_a = _task_bypasses_fuzz(plan_a["tasks"][0], orig_mtt_a)
record(
    "(a) PRE-flag baseline: same survivor's type alone does NOT bypass (would be fuzzed)",
    pre_bypass_a is False,
    f"pre-flag _task_bypasses_fuzz={pre_bypass_a!r}",
)
out_a = _force_smoke_gated_leaf_impl(copy.deepcopy(plan_a), ext_root)
surv_a = out_a["tasks"][0]
sg_a = surv_a.get("smoke_gated")
mtt_a = surv_a.get("meta_task_type")
bypass_a = _task_bypasses_fuzz(surv_a, mtt_a)
record(
    "(a) smoke_gated set True",
    sg_a is True,
    f"smoke_gated={sg_a!r}",
)
record(
    "(a) real meta_task_type kept (NOT retyped to data_model-bypass; keeps original)",
    mtt_a == orig_mtt_a,
    f"meta_task_type={mtt_a!r} (orig {orig_mtt_a!r})",
)
record(
    "(a) _task_bypasses_fuzz True -> routed to BYPASS (smoke), NOT diff-fuzzed",
    bypass_a is True,
    f"_task_bypasses_fuzz={bypass_a!r}",
)

# ============================================================
# CASE (b): ANTI-CATCH-ALL — EXTERNAL FUZZABLE survivor
# ============================================================
print()
print("=" * 72)
print("CASE (b): ANTI-CATCH-ALL: EXTERNAL FUZZABLE survivor (pure stdlib)")
print("=" * 72)
plan_b = build_plan({
    "meta_task_type": "data_model",
    "files_touched": ["src/parser/tokens.py"],  # normal non-ngv2 path
    "specification": "Parse integers from a string and return a list of ints.",  # no socket hint
})
orig_mtt_b = plan_b["tasks"][0]["meta_task_type"]
out_b = _force_smoke_gated_leaf_impl(copy.deepcopy(plan_b), ext_root)
surv_b = out_b["tasks"][0]
sg_b = surv_b.get("smoke_gated")
mtt_b = surv_b.get("meta_task_type")
bypass_b = _task_bypasses_fuzz(surv_b, mtt_b)
record(
    "(b) NO smoke_gated set (key under-fuzz guard)",
    sg_b is None or sg_b is False,
    f"smoke_gated={sg_b!r}",
)
record(
    "(b) real meta_task_type kept",
    mtt_b == orig_mtt_b,
    f"meta_task_type={mtt_b!r}",
)
record(
    "(b) _task_bypasses_fuzz False -> STILL diff-fuzzed",
    bypass_b is False,
    f"_task_bypasses_fuzz={bypass_b!r}",
)

# ============================================================
# CASE (c): ac505d7 PRESERVED — plain data_model, no smoke_gated
# ============================================================
print()
print("=" * 72)
print("CASE (c): ac505d7 PRESERVED — plain data_model task, no smoke_gated")
print("=" * 72)
plain_dm = {"task_id": "dm-1", "meta_task_type": "data_model"}  # no smoke_gated key
bypass_c = _task_bypasses_fuzz(plain_dm, "data_model")
record(
    "(c) _task_bypasses_fuzz(data_model, no flag) False -> still diff-fuzzed",
    bypass_c is False,
    f"_task_bypasses_fuzz={bypass_c!r}",
)
record(
    "(c) 'data_model' not in live BYPASS_FUZZER_TYPES",
    "data_model" not in BYPASS_FUZZER_TYPES,
    f"in_bypass={'data_model' in BYPASS_FUZZER_TYPES}",
)

# ============================================================
# CASE (d): JM-SELF no-op — repo_root == PROJECT_ROOT
# ============================================================
print()
print("=" * 72)
print("CASE (d): JM-SELF no-op — repo_root == PROJECT_ROOT")
print("=" * 72)
# Build a plan whose vcmd resolves under the REAL PROJECT_ROOT, with an ngv2/ signal
# that WOULD flag it if the function ran. The function must short-circuit (no flag).
self_oracle = None
# Find a real .py under PROJECT_ROOT to use as the oracle token
candidate = Path(PROJECT_ROOT) / "harness" / "paths.py"
assert candidate.is_file(), "expected harness/paths.py to exist"
rel = candidate.relative_to(PROJECT_ROOT)
plan_d = {
    "tasks": [
        {
            "task_id": "self-1",
            "meta_task_type": "data_model",
            "verification_command": f"pytest {rel} -q",
            "files_touched": ["ngv2/workers/_runner.py"],  # would flag if function ran
            "specification": "loopback server_socket listen()",  # would flag if function ran
        }
    ]
}
out_d = _force_smoke_gated_leaf_impl(copy.deepcopy(plan_d), str(PROJECT_ROOT))
surv_d = out_d["tasks"][0]
sg_d = surv_d.get("smoke_gated")
record(
    "(d) repo_root==PROJECT_ROOT -> NO smoke_gated flag (self-fix never flagged)",
    sg_d is None or sg_d is False,
    f"smoke_gated={sg_d!r}",
)

# ============================================================
# SUMMARY
# ============================================================
print()
print("=" * 72)
total = len(results)
passed = sum(1 for r in results if r)
print(f"SUMMARY: {passed}/{total} checks PASS")
print("=" * 72)

sys.exit(0 if passed == total else 1)
