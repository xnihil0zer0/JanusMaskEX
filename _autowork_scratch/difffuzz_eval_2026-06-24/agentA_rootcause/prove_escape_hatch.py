#!/usr/bin/env python3
"""
AGENT-A ROOT-CAUSE PROOF (read-only on production).

Proves that the planner escape-hatch `_force_smoke_gated_leaf_impl` retypes an
EXTERNAL impl-survivor (red-pair sharing the oracle's pytest test-set) to
meta_task_type `data_model`, and that the ac505d7 + wave-flips data_model
True->False flip now causes that survivor to be DIFF-FUZZED where it used to be
SMOKE-GATED (bypass).

It does NOT edit production. The "before flip" world is simulated by mutating an
in-memory copy of META_TASK_POLICY in this script only.
"""
import sys
import copy
from pathlib import Path

# Use the REAL production target's external repo_root + the SAME shared pytest
# vcmd observed on the live P1.3 leaf (wire-loopback-per-cwe-channels).
EXTERNAL_REPO_ROOT = "/home/xnihil0zer0/NobleGreedv2"
SHARED_VCMD = "python -m pytest tests/ngv2/test_wire_loopback_per_cwe_channels.py -q"

# Import the production symbols (read-only).
from harness.planner.plan_normalizer import _force_smoke_gated_leaf_impl
from harness.planner.taxonomies import META_TASK_POLICY, BYPASS_FUZZER_TYPES

# --- The runtime fuzz-gate decision, replicated from orchestrator_worker.py:816
#     `if mtt in BYPASS_FUZZER_TYPES or _skip_ifz:`  -> bypass (smoke), else fuzz.
def fuzz_gate(mtt, policy):
    bypass_types = frozenset(k for k, v in policy.items() if v.get("bypass_fuzzer"))
    skip_ifz = bool(policy.get(mtt, {}).get("skip_interface_fuzz"))
    if mtt in bypass_types or skip_ifz:
        return "BYPASS (smoke/embedded/narrow gate -- NOT diff-fuzzed)"
    return "DIFF-FUZZED"


def make_plan():
    """A representative EXTERNAL red-pair: a test_authoring oracle + an impl,
    both sharing the same pytest test-set (the exact live P1.3 shape)."""
    return {
        "slug": "wire-loopback-per-cwe-channels",
        "tasks": [
            {
                "task_id": "wire-loopback-per-cwe-channels-oracle",
                "meta_task_type": "test_authoring",
                "verification_command": SHARED_VCMD,
                "dependencies": [],
            },
            {
                # External side-effecting impl (opens loopback listeners per CWE).
                "task_id": "wire-loopback-per-cwe-channels-impl",
                "meta_task_type": "io_adapter",  # any impl (non-oracle) type
                "verification_command": SHARED_VCMD,
                "dependencies": ["wire-loopback-per-cwe-channels-oracle"],
            },
        ],
    }


def survivor_mtt(plan):
    """Run the production escape-hatch and return the survivor impl's mtt."""
    out = _force_smoke_gated_leaf_impl(plan, EXTERNAL_REPO_ROOT)
    for t in out["tasks"]:
        if t["task_id"] == "wire-loopback-per-cwe-channels-impl":
            return t["meta_task_type"], out
    return None, out


def main():
    fails = []
    print("=" * 78)
    print("AGENT-A: escape-hatch _force_smoke_gated_leaf_impl root-cause proof")
    print("=" * 78)

    # Sanity: the external test file actually resolves (else _oracle_set is empty
    # and the collapse never fires -- prove the precondition holds in reality).
    tf = Path(EXTERNAL_REPO_ROOT) / "tests/ngv2/test_wire_loopback_per_cwe_channels.py"
    print(f"\n[precond] external test file exists: {tf.is_file()}  ({tf})")
    if not tf.is_file():
        fails.append("PRECOND: external test file missing -> _oracle_set empty -> hatch inert")

    # 1) Escape-hatch retypes the external impl survivor to data_model.
    mtt_after, out = survivor_mtt(make_plan())
    print(f"\n[1] survivor impl meta_task_type after escape-hatch: {mtt_after!r}")
    n_tasks = len(out["tasks"])
    print(f"    (oracle collapsed? surviving task count = {n_tasks}; expect 1 -- oracle dropped)")
    if mtt_after != "data_model":
        fails.append(f"[1] expected survivor retyped to 'data_model', got {mtt_after!r}")

    # 2) Print the CURRENT (post-flip) data_model policy + resulting gate.
    cur_policy = copy.deepcopy(dict(META_TASK_POLICY))
    print(f"\n[2] CURRENT data_model policy (production): {cur_policy['data_model']}")
    gate_after = fuzz_gate("data_model", cur_policy)
    print(f"    data_model in BYPASS_FUZZER_TYPES (prod) : {'data_model' in BYPASS_FUZZER_TYPES}")
    print(f"    => runtime gate for the retyped survivor : {gate_after}")
    if "DIFF-FUZZED" not in gate_after:
        fails.append("[2] expected CURRENT data_model survivor to be DIFF-FUZZED")

    # 3) Simulate the PRE-FLIP world (data_model.bypass_fuzzer=True) IN MEMORY ONLY.
    before_policy = copy.deepcopy(dict(META_TASK_POLICY))
    before_policy["data_model"] = dict(before_policy["data_model"])
    before_policy["data_model"]["bypass_fuzzer"] = True  # the pre-ac505d7 value
    gate_before = fuzz_gate("data_model", before_policy)
    print(f"\n[3] SIMULATED pre-flip data_model policy      : {before_policy['data_model']}")
    print(f"    => runtime gate for the retyped survivor : {gate_before}")
    if "BYPASS" not in gate_before:
        fails.append("[3] expected pre-flip data_model survivor to BYPASS (smoke)")

    # 4) The defect: SAME plan + SAME escape-hatch retyping -> gate FLIPPED.
    print("\n[4] DEFECT: identical external red-pair, identical escape-hatch retyping")
    print(f"      BEFORE flip (data_model bypass=True) : {gate_before}")
    print(f"      AFTER  flip (data_model bypass=False): {gate_after}")
    if gate_before == gate_after:
        fails.append("[4] gate did NOT change across the flip -- no defect demonstrated")

    # ---- explicit PASS/FAIL ----
    print("\n" + "=" * 78)
    if fails:
        print("RESULT: FAIL")
        for f in fails:
            print("  FAIL:", f)
        return 1
    print("RESULT: PASS -- escape-hatch retypes external impl survivor to data_model;")
    print("        the data_model True->False flip turns its gate BYPASS->DIFF-FUZZED.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
