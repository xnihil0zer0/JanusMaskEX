#!/usr/bin/env python3
"""
Adversarial edge-logic probe for the diff-fuzz escape-hatch issue.

CONTEXT
-------
`_force_smoke_gated_leaf_impl` (harness/planner/plan_normalizer.py:570) retypes an
EXTERNAL-build survivor impl task to meta_task_type='data_model'. The docstring
(lines 575-578) asserts data_model "is bypass_fuzzer and smoke-gated", which routes
external ngv2.* builds AWAY from the diff-fuzzer that cannot resolve external imports.

But ac505d7 (2026-06-22) flipped data_model bypass_fuzzer True->False. So the
hardcoded retype target now gets diff-fuzzed. For an external impl that imports
ngv2.* (or opens a listener), the fuzz sandbox can't execute it -> batch_error ->
FuzzResult(error=...) -> fuzz_error_r1 -> blocked.

This script PROTOTYPES candidate-fix logic (NEVER edits production) and tests at
the EDGES, with explicit PASS/FAIL and a deliberate "would this under-fuzz X?" probe.

We import the REAL META_TASK_POLICY to keep the prototype honest about live values.
"""
import sys, os, importlib.util

JM = "/home/xnihil0zer0/JanusMaskJR"
sys.path.insert(0, JM)

from harness.planner.taxonomies import (
    META_TASK_POLICY, BYPASS_FUZZER_TYPES, SIDE_EFFECT_META_TYPES,
)

def policy(t):
    return META_TASK_POLICY.get(t, {})

def is_bypass(t):
    return t in BYPASS_FUZZER_TYPES  # bypass_fuzzer == True => NOT fuzzed

def is_smoke_gated(t):
    # smoke-gated == NOT skip_smoke_gates (a bypass type with skip_smoke_gates
    # gets NEITHER fuzz NOR smoke -> weakest verification)
    return not policy(t).get("skip_smoke_gates", False)

# ---------------------------------------------------------------------------
# Ground truth about the live policy
# ---------------------------------------------------------------------------
print("="*78)
print("LIVE POLICY GROUND TRUTH")
print("="*78)
print(f"data_model live policy        : {policy('data_model')}")
print(f"data_model is_bypass (no fuzz): {is_bypass('data_model')}")
print(f"data_model is_smoke_gated     : {is_smoke_gated('data_model')}")
print(f"BYPASS_FUZZER_TYPES (no fuzz) : {sorted(BYPASS_FUZZER_TYPES)}")
print()

results = []  # (name, passed, detail)
def check(name, passed, detail=""):
    results.append((name, passed, detail))
    print(f"[{'PASS' if passed else 'FAIL'}] {name}  {detail}")

# ---------------------------------------------------------------------------
# PART 1 — DEMONSTRATE THE DEFECT: the escape-hatch's stated purpose is broken.
# ---------------------------------------------------------------------------
print("\n" + "="*78)
print("PART 1 — DEFECT DEMONSTRATION (escape-hatch target now gets fuzzed)")
print("="*78)
# The docstring claims the retype routes the survivor AWAY from the fuzzer.
# That requires the target type to be bypass_fuzzer=True.
check(
    "escape-hatch DOCSTRING is now FALSE (data_model is fuzzed, not bypass)",
    not is_bypass("data_model"),
    "-> retyped external survivor WILL be diff-fuzzed; ngv2.* imports cannot load in fuzz sandbox -> fuzz_error_r1",
)

# ---------------------------------------------------------------------------
# PART 2 — CANDIDATE FIXES PROTOTYPED AT THE EDGES.
# We define a tiny model of the routing decision and test each candidate.
# ---------------------------------------------------------------------------
print("\n" + "="*78)
print("PART 2 — CANDIDATE FIX EDGE PROBES")
print("="*78)

# Model of a leaf the escape-hatch is choosing a target type for.
# 'external' = repo_root outside PROJECT_ROOT (the ONLY path the hatch runs on).
# 'imports_external' = candidate code imports ngv2.* / opens a listener => unfuzzable.
class Leaf:
    def __init__(self, name, external, imports_external, should_be_fuzzed):
        self.name = name
        self.external = external               # hatch only fires when True
        self.imports_external = imports_external
        # GROUND TRUTH: does the project INTENT want this leaf fuzzed?
        # Intent: "code that SHOULD be fuzzed must be fuzzed". An external leaf
        # whose candidate genuinely cannot be loaded in the fuzz sandbox CANNOT
        # be meaningfully fuzzed (fuzzer errors, not certifies). A pure-stdlib
        # external transform CAN and SHOULD be fuzzed.
        self.should_be_fuzzed = should_be_fuzzed

# Edge corpus. The crux: a stdlib-only external transform SHOULD still be fuzzed;
# only the genuinely-unloadable (ngv2.* import / listener) external impl must bypass.
corpus = [
    Leaf("ext_pure_stdlib_transform",  external=True,  imports_external=False, should_be_fuzzed=True),
    Leaf("ext_opens_loopback_listener",external=True,  imports_external=True,  should_be_fuzzed=False),
    Leaf("ext_imports_ngv2_pkg",       external=True,  imports_external=True,  should_be_fuzzed=False),
    Leaf("internal_normal_impl",       external=False, imports_external=False, should_be_fuzzed=True),  # hatch never fires
]

# --- CANDIDATE A: current behavior (retype ALL survivors -> data_model[fuzzed]) ---
# i.e. the escape-hatch as it stands post-ac505d7: target is fuzzed.
def route_candidate_A(leaf):
    # hatch fires on external; target = data_model (fuzzed)
    if not leaf.external:
        return ("(hatch skipped)", "fuzzed")   # internal goes normal path = fuzzed
    return ("data_model", "fuzzed" if not is_bypass("data_model") else "bypass")

# --- CANDIDATE B (NAIVE CATCH-ALL): retype ALL survivors -> a bypass type ---
# e.g. blanket retype to mcp_plumbing (bypass=True, skip_decomp=True). This is the
# DANGEROUS catch-all: every external survivor dodges fuzzing, even stdlib ones.
def route_candidate_B(leaf):
    if not leaf.external:
        return ("(hatch skipped)", "fuzzed")
    return ("mcp_plumbing", "bypass" if is_bypass("mcp_plumbing") else "fuzzed")

# --- CANDIDATE C (TARGETED): only bypass when the candidate is genuinely unfuzzable ---
# Gate the retype-to-bypass on imports_external; otherwise leave as fuzzed data_model.
# This is the MINIMAL-SEMANTICS fix prototype (the *policy* it should implement).
def route_candidate_C(leaf):
    if not leaf.external:
        return ("(hatch skipped)", "fuzzed")
    if leaf.imports_external:
        # genuinely cannot be loaded in fuzz sandbox -> route to bypass+smoke
        return ("mcp_plumbing", "bypass")
    # stdlib-only external transform -> KEEP fuzzed
    return ("data_model", "fuzzed")

def grade(candidate_fn, label):
    print(f"\n--- {label} ---")
    under_fuzz = []   # SHOULD be fuzzed but candidate routes to bypass (REGRESSION)
    over_fuzz  = []   # genuinely unfuzzable but routed to fuzz (the original bug)
    for leaf in corpus:
        target, mode = candidate_fn(leaf)
        fuzzed = (mode == "fuzzed")
        tag = "ok"
        if leaf.should_be_fuzzed and not fuzzed:
            under_fuzz.append(leaf.name); tag = "UNDER-FUZZ (reliability REGRESSION)"
        elif (not leaf.should_be_fuzzed) and fuzzed:
            over_fuzz.append(leaf.name); tag = "OVER-FUZZ (spurious fuzz_error)"
        print(f"   {leaf.name:32s} -> target={target:14s} mode={mode:8s}  [{tag}]")
    return under_fuzz, over_fuzz

uA, oA = grade(route_candidate_A, "CANDIDATE A: current post-ac505d7 (retype->data_model, fuzzed)")
uB, oB = grade(route_candidate_B, "CANDIDATE B: NAIVE CATCH-ALL (retype ALL->bypass type)")
uC, oC = grade(route_candidate_C, "CANDIDATE C: TARGETED (bypass ONLY genuinely-unfuzzable)")

print("\n" + "="*78)
print("PART 3 — ADVERSARIAL ASSERTIONS")
print("="*78)

# A: the live bug — over-fuzzes the unloadable external impls (the reported issue).
check("CANDIDATE A over-fuzzes genuinely-unfuzzable external impls (the live bug)",
      len(oA) >= 1, f"over_fuzz={oA}")

# B: the catch-all DISASTER probe — does the naive bypass under-fuzz a leaf that
# SHOULD be fuzzed? This is the highest-severity regression.
check("CANDIDATE B UNDER-FUZZES a should-be-fuzzed external transform (catch-all regression)",
      "ext_pure_stdlib_transform" in uB, f"under_fuzz={uB}")

# C: targeted fix has NO under-fuzz AND NO over-fuzz on the corpus.
check("CANDIDATE C does NOT under-fuzz any should-be-fuzzed leaf",
      len(uC) == 0, f"under_fuzz={uC}")
check("CANDIDATE C does NOT over-fuzz the genuinely-unfuzzable leaves",
      len(oC) == 0, f"over_fuzz={oC}")

# DELIBERATE "would this fix under-fuzz X?" probe, demanded by the brief:
# Take a should-be-fuzzed internal leaf and a stdlib external transform; confirm
# the SAFE candidate (C) keeps BOTH fuzzed.
print("\n--- DELIBERATE under-fuzz probe on CANDIDATE C ---")
probe_leaves = [l for l in corpus if l.should_be_fuzzed]
all_kept_fuzzed = True
for leaf in probe_leaves:
    _, mode = route_candidate_C(leaf)
    kept = (mode == "fuzzed")
    all_kept_fuzzed = all_kept_fuzzed and kept
    print(f"   {leaf.name:32s} should_be_fuzzed=True -> kept_fuzzed={kept}")
check("PROBE: CANDIDATE C keeps EVERY should-be-fuzzed leaf fuzzed (no fuzz-dodge)",
      all_kept_fuzzed)

# Guardrail probe: show that retyping to ANY bypass type without the
# imports_external gate is what creates the catch-all. The gate is the guardrail.
print("\n--- GUARDRAIL: the imports_external gate is what prevents the catch-all ---")
gated_target, gated_mode = route_candidate_C(corpus[0])     # stdlib external
ungated_target, ungated_mode = route_candidate_B(corpus[0]) # naive bypass
check("Removing the unfuzzable-gate turns the hatch into a fuzz-dodging catch-all",
      gated_mode == "fuzzed" and ungated_mode == "bypass",
      f"gated={gated_mode} ungated={ungated_mode}")

print("\n" + "="*78)
print("SUMMARY")
print("="*78)
passed = sum(1 for _, p, _ in results if p)
total = len(results)
for name, p, detail in results:
    print(f"  [{'PASS' if p else 'FAIL'}] {name}")
print(f"\n{passed}/{total} assertions passed")
sys.exit(0 if passed == total else 1)
