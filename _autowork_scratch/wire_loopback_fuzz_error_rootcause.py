#!/usr/bin/env python3
"""ANALYTIC root-cause + lever-selection script for the failed external build of
`brief_hooks_wire_loopback_per_cwe_channels.md` (impl task fuzz_error_r1).

Run from the JanusMaskJR repo root:
    python _autowork_scratch/wire_loopback_fuzz_error_rootcause.py

It PROVES, from the live modules (no assertions-by-hand):
  1. POLICY: io_adapter.bypass_fuzzer is False; which types actually bypass.
  2. ROUTING: the worker gate that sends a non-bypass type into differential fuzz.
  3. COERCION (the crux): normalize_plan force-retypes the EXTERNAL impl survivor to
     `data_model` REGARDLESS of the brief-requested type -- and `data_model` was FLIPPED
     to bypass_fuzzer=False by the difffuzz wave (commit ac505d7), so the external escape
     hatch now STILL fuzzes. => the brief's requested type is honored ONLY for the
     `non_impl` test_* types, which alone survive the retype.
  4. DETERMINISM: the generated candidate opens a real socket under network:false.
  5. LEVER: test_acceptance (bypass + non_impl + non-test_authoring) survives the retype,
     gets the PARTIAL-EDIT __JANUSMASK_PATCHES__ dispatch (not the test-authoring dispatch),
     keeps the red-pair oracle, and never reaches structural decomposition.
"""
import copy
from pathlib import Path

from harness.planner.taxonomies import META_TASK_POLICY, BYPASS_FUZZER_TYPES
from harness.planner.plan_normalizer import normalize_plan

REPO_ROOT = "/home/xnihil0zer0/NobleGreedv2"
ORACLE_TEST = "tests/ngv2/test_wire_loopback_per_cwe_channels.py"
VCMD = f"python -m pytest {ORACLE_TEST} -q"
NON_IMPL = {"test_authoring", "test_acceptance", "test_unit", "test_integration", "test_e2e", "validation"}


def section(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


# ---- 1. POLICY -----------------------------------------------------------------
section("1. POLICY FACTS (from live harness.planner.taxonomies)")
print("io_adapter.bypass_fuzzer    =", META_TASK_POLICY["io_adapter"]["bypass_fuzzer"])
print("orchestration.bypass_fuzzer =", META_TASK_POLICY["orchestration"]["bypass_fuzzer"],
      " <- REFUTES hypothesis: orchestration does NOT bypass")
print("data_model.bypass_fuzzer    =", META_TASK_POLICY["data_model"]["bypass_fuzzer"],
      " <- the coercion target; flipped True->False by difffuzz wave (ac505d7)")
print("\nTypes that ACTUALLY bypass the fuzzer (BYPASS_FUZZER_TYPES):")
for t in sorted(BYPASS_FUZZER_TYPES):
    print(f"   {t:18} skip_decomp={META_TASK_POLICY[t].get('skip_structural_decomp')} "
          f"skip_smoke={META_TASK_POLICY[t].get('skip_smoke_gates')}")

# ---- 2. ROUTING ----------------------------------------------------------------
section("2. ROUTING (orchestrator_worker.py:816 gate replicated)")
for mtt in ("io_adapter", "data_model", "test_acceptance"):
    skip_ifz = (mtt == "test_authoring") and META_TASK_POLICY.get("test_authoring", {}).get("skip_interface_fuzz")
    stateful = META_TASK_POLICY.get(mtt, {}).get("stateful_fuzz")
    routes_to_fuzz = not (mtt in BYPASS_FUZZER_TYPES or skip_ifz) and not stateful
    print(f"   mtt={mtt:16} -> routes to DIFFERENTIAL FUZZING (line 902 path): {routes_to_fuzz}")
print("   (worker: `if mtt in BYPASS_FUZZER_TYPES or _skip_ifz:` no-fuzz block; "
      "else -> set_phase('fuzzing') -> fuzz_from_task)")

# ---- 3. COERCION (THE CRUX) ----------------------------------------------------
section("3. PLANNER COERCION -- does it HONOR the brief-requested meta_task_type?")
print("normalize_plan(repo_root=NobleGreedv2) on the brief's red-pair shape.")
print(f"oracle test exists on disk: {(Path(REPO_ROOT) / ORACLE_TEST).is_file()}  "
      "(=> impl shares its oracle-set => _force_smoke_gated_leaf_impl groups+retypes)\n")


def make_plan(impl_type: str) -> dict:
    return {
        "required_task_ids": ["wire-loopback-per-cwe-channels-oracle", "wire-loopback-per-cwe-channels-impl"],
        "tasks": [
            {"task_id": "wire-loopback-per-cwe-channels-oracle", "meta_task_type": "test_authoring",
             "files_touched": [ORACLE_TEST], "mutation_target": "ngv2.workers._runner",
             "verification_command": VCMD, "dependencies": []},
            {"task_id": "wire-loopback-per-cwe-channels-impl", "meta_task_type": impl_type,
             "files_touched": ["ngv2/workers/_runner.py"], "verification_command": VCMD,
             "dependencies": ["wire-loopback-per-cwe-channels-oracle"]},
        ],
    }


print(f"{'requested':18} {'FINAL impl type':18} {'bypass?':8} {'oracle_kept':12} {'impl_kept'}")
for req in ("io_adapter", "orchestration", "data_model", "config_schema",
            "test_unit", "test_integration", "test_e2e", "test_acceptance"):
    out = normalize_plan(copy.deepcopy(make_plan(req)), repo_root=REPO_ROOT)
    by = {t["task_id"]: t for t in out["tasks"]}
    impl = by.get("wire-loopback-per-cwe-channels-impl")
    oracle_kept = "wire-loopback-per-cwe-channels-oracle" in by
    final = impl.get("meta_task_type") if impl else None
    print(f"{req:18} {str(final):18} {str(final in BYPASS_FUZZER_TYPES):8} "
          f"{str(oracle_kept):12} {impl is not None}")
print("\n=> NON test_* (impl-candidate) types are ALL force-retyped to data_model (still fuzzes).")
print("   ONLY the `non_impl` test_* types survive with their requested (bypass) type.")

# ---- 5. LEVER VALIDATION -------------------------------------------------------
section("5. LEVER = test_acceptance -- dispatch + decomposition safety")
mtt = "test_acceptance"
print(f"test_acceptance in BYPASS_FUZZER_TYPES: {mtt in BYPASS_FUZZER_TYPES}  "
      f"(orchestrator.py:1468 selects PARTIAL-EDIT __JANUSMASK_PATCHES__ dispatch)")
print(f"test_acceptance == 'test_authoring': {mtt == 'test_authoring'}  "
      "(orchestrator.py:1475 TEST-AUTHORING dispatch fires ONLY for test_authoring -> NOT selected)")
print(f"test_acceptance.skip_structural_decomp: {META_TASK_POLICY[mtt].get('skip_structural_decomp')}  "
      "(MOOT: decomposition (worker:1015-1039) is reached ONLY after fuzz rounds fail;")
print("   a bypass type returns at worker:901 and never reaches the decomposition phase.)")
print(f"test_acceptance.skip_smoke_gates: {META_TASK_POLICY[mtt].get('skip_smoke_gates')}")

# ---- 4. DETERMINISM (candidate opens a real socket) ----------------------------
section("4. DETERMINISM -- the generated candidate opens a real socket under network:false")
cand = Path("/home/xnihil0zer0/JanusMaskJR/state/output/wire-loopback-per-cwe-channels-impl.py")
cfg = Path("/home/xnihil0zer0/JanusMaskJR/harness/config.yaml")
net = [ln.strip() for ln in cfg.read_text().splitlines() if "network" in ln]
print("harness/config.yaml network setting:", net)
if cand.is_file():
    for i, ln in enumerate(cand.read_text().splitlines(), 1):
        s = ln.strip()
        if any(k in s for k in ("LoopbackListener", "listener.start()", "port=0", "url_for")):
            print(f"   candidate L{i}: {s}")
print("=> seam closure binds 127.0.0.1:0 + start() at fuzz time; under network:false the")
print("   sandboxed exec errors on the socket op DETERMINISTICALLY -> fuzz_error_r1 every retry.")
print("\nblocked retry sidecar:",
      Path("/home/xnihil0zer0/JanusMaskJR/state/tasks/blocked/"
           "wire-loopback-per-cwe-channels-impl.retry.json").read_text().strip())
