#!/usr/bin/env python3
"""
AGENT-A: (a) enumerate the LIVE META_TASK_POLICY + empirical bypass_fuzzer,
(b) prototype the surgical fix and prove the fix LOGIC keeps data_model fuzzed
while routing the non-fuzzable external survivor away from the diff-fuzzer.

Read-only on production. The "fix" is prototyped here only -- it is the SAME
behavior the surgical patch would produce, modeled in-script.
"""
import copy
from harness.planner.taxonomies import (
    META_TASK_POLICY, BYPASS_FUZZER_TYPES, META_TASK_TYPES, SIDE_EFFECT_META_TYPES,
)
from harness.planner.plan_normalizer import _force_smoke_gated_leaf_impl

EXTERNAL_REPO_ROOT = "/home/xnihil0zer0/NobleGreedv2"
SHARED_VCMD = "python -m pytest tests/ngv2/test_wire_loopback_per_cwe_channels.py -q"


def banner(s):
    print("\n" + "=" * 78 + "\n" + s + "\n" + "=" * 78)


# ----------------------------------------------------------------------------
banner("(A) LIVE META_TASK_POLICY -- empirical bypass_fuzzer per type")
print(f"{'meta_task_type':24} {'bypass_fuzzer':14} {'skip_struct':12} "
      f"{'skip_smoke':11} {'skip_ifz':9} {'stateful'}")
print("-" * 86)
for k in sorted(META_TASK_POLICY):
    v = META_TASK_POLICY[k]
    print(f"{k:24} {str(v.get('bypass_fuzzer')):14} "
          f"{str(v.get('skip_structural_decomp')):12} "
          f"{str(v.get('skip_smoke_gates')):11} "
          f"{str(v.get('skip_interface_fuzz')):9} {v.get('stateful_fuzz')}")
print("-" * 86)
fuzzed = sorted(k for k in META_TASK_POLICY if not META_TASK_POLICY[k]["bypass_fuzzer"])
bypass = sorted(BYPASS_FUZZER_TYPES)
print(f"\nDIFF-FUZZED types ({len(fuzzed)}): {fuzzed}")
print(f"\nBYPASS (not diff-fuzzed) types ({len(bypass)}): {bypass}")
print(f"\n>>> data_model in BYPASS_FUZZER_TYPES = {'data_model' in BYPASS_FUZZER_TYPES} "
      f"(False == data_model IS now diff-fuzzed -- the intentional ac505d7 flip)")

# ----------------------------------------------------------------------------
banner("(B) How many code paths force-retype a leaf to 'data_model'?")
import subprocess
res = subprocess.run(
    ["grep", "-rn", r"=\s*'data_model'\|= \"data_model\"\|'data_model'",
     "harness/planner/plan_normalizer.py"],
    capture_output=True, text=True, cwd="/home/xnihil0zer0/JanusMaskJR")
assign_lines = [ln for ln in res.stdout.splitlines() if "meta_task_type" in ln and "=" in ln]
print("Assignment sites of meta_task_type <- 'data_model' in plan_normalizer.py:")
for ln in assign_lines:
    print("   ", ln.strip())
print(f"\n=> distinct force-retype-to-data_model code paths: {len(assign_lines)} "
      f"(only the escape-hatch)")

# ----------------------------------------------------------------------------
banner("(C) FIX PROTOTYPE: retype the external survivor to a type that is still"
       "\n    BYPASS (smoke-gated) and INDEPENDENT of the data_model fuzz flip.")

# Candidate fix targets: a type that is (i) bypass_fuzzer=True (so the external
# non-fuzzable survivor is smoke/embedded/narrow-gated, NOT diff-fuzzed) AND
# (ii) NOT data_model (so it is decoupled from the intentional data_model flip)
# AND (iii) side-effect/smoke-gating semantics appropriate for an impl.
candidates = [k for k in META_TASK_POLICY
              if META_TASK_POLICY[k]["bypass_fuzzer"]
              and META_TASK_POLICY[k].get("skip_structural_decomp")
              and not META_TASK_POLICY[k].get("skip_smoke_gates")]
print("bypass_fuzzer=True AND skip_structural_decomp=True AND NOT skip_smoke_gates")
print("  (i.e. still SMOKE-GATED, fuzz-bypassed, side-effecting):")
print("   ", candidates)

# FINDING: the wave-flips (3b58a10, 84a877c) flipped sandbox_infra/orchestration/
# planner_tooling/harness_plumbing/harness_self_fix/validation -> bypass_fuzzer=False.
# The ONLY surviving meta_task_type that is bypass_fuzzer=True AND smoke-gated
# (not skip_smoke_gates) AND impl-shaped (skip_structural_decomp=True) is
# 'mcp_plumbing'. That is the sole drop-in EXISTING type that preserves the
# escape-hatch's original (data_model) policy semantics: fuzz-bypassed + smoke-
# gated + structural-decomp-skipped. It is decoupled from data_model, so the
# data_model fuzz flip cannot re-break it.  (A NEW dedicated type e.g.
# 'external_smoke_survivor' would be cleaner but is multi-file; see report.)
FIX_TARGET = "mcp_plumbing"
print(f"\nChosen drop-in fix target meta_task_type: {FIX_TARGET!r}")
print(f"  policy: {META_TASK_POLICY.get(FIX_TARGET)}")
assert FIX_TARGET in META_TASK_POLICY
assert META_TASK_POLICY[FIX_TARGET]["bypass_fuzzer"] is True, "fix target must bypass"
assert FIX_TARGET != "data_model", "fix target must be decoupled from data_model flip"
assert not META_TASK_POLICY[FIX_TARGET].get("skip_smoke_gates"), "must keep smoke gate"
assert META_TASK_POLICY[FIX_TARGET].get("skip_structural_decomp"), "impl-shaped"


def fuzz_gate(mtt, policy):
    bypass_types = frozenset(k for k, v in policy.items() if v.get("bypass_fuzzer"))
    skip_ifz = bool(policy.get(mtt, {}).get("skip_interface_fuzz"))
    return "BYPASS" if (mtt in bypass_types or skip_ifz) else "DIFF-FUZZED"


# Model the FIXED escape-hatch: identical collapse, but survivor retyped to
# FIX_TARGET instead of 'data_model'. (We reuse the prod hatch then re-stamp the
# survivor in-memory to model the one-line change survivor['meta_task_type']=...)
def fixed_survivor_gate():
    plan = {
        "slug": "x", "tasks": [
            {"task_id": "o", "meta_task_type": "test_authoring",
             "verification_command": SHARED_VCMD, "dependencies": []},
            {"task_id": "i", "meta_task_type": "io_adapter",
             "verification_command": SHARED_VCMD, "dependencies": ["o"]},
        ]}
    out = _force_smoke_gated_leaf_impl(plan, EXTERNAL_REPO_ROOT)
    surv = next(t for t in out["tasks"] if t["task_id"] == "i")
    assert surv["meta_task_type"] == "data_model", "prod hatch should retype to data_model"
    # model the surgical change:
    surv["meta_task_type"] = FIX_TARGET
    return fuzz_gate(surv["meta_task_type"], META_TASK_POLICY)


print("\nResulting runtime gate for the external survivor:")
print(f"  CURRENT (buggy, ->data_model)        : "
      f"{fuzz_gate('data_model', META_TASK_POLICY)}")
print(f"  FIXED  (->{FIX_TARGET})              : {fixed_survivor_gate()}")

# Prove data_model is STILL fuzzed under the fix (intent preserved).
print(f"\n  data_model gate UNCHANGED by fix     : {fuzz_gate('data_model', META_TASK_POLICY)} "
      f"(intentional ac505d7 flip preserved)")

# ----------------------------------------------------------------------------
banner("FIX LOGIC ASSERTIONS")
fails = []
if fuzz_gate("data_model", META_TASK_POLICY) != "DIFF-FUZZED":
    fails.append("data_model must remain DIFF-FUZZED (intent)")
if fixed_survivor_gate() != "BYPASS":
    fails.append("fixed external survivor must BYPASS (smoke), not diff-fuzz")
if FIX_TARGET == "data_model":
    fails.append("fix must decouple from data_model")
if fails:
    print("RESULT: FAIL")
    for f in fails:
        print("  FAIL:", f)
    raise SystemExit(1)
print("RESULT: PASS")
print("  - data_model stays DIFF-FUZZED (ac505d7 intent preserved)")
print(f"  - external non-fuzzable survivor routes to {FIX_TARGET} -> SMOKE-GATED, not fuzzed")
print("  - the two concerns are now decoupled: future data_model flips can't re-break this")
