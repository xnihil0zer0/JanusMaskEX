#!/usr/bin/env python3
"""Agent-B (intent & correct-classification lens) analytic harness.

READ-ONLY on production. This script imports the LIVE META_TASK_POLICY,
prints the empirical policy table, classifies each meta_task_type by whether
DIFFERENTIAL FUZZING can meaningfully validate dual-agent synthesis of that
kind of code, and then PROTOTYPES the proposed routing fix (an orthogonal
``smoke_gated`` task flag honored by the fuzz-gate) against 3 representative
leaf descriptors -- proving data_model stays fuzzed while side-effecting
external survivors route to oracle+smoke. Nothing here mutates production.
"""
import sys
import os

JM_ROOT = "/home/xnihil0zer0/JanusMaskJR"
sys.path.insert(0, JM_ROOT)

from harness.planner.taxonomies import (
    META_TASK_POLICY,
    BYPASS_FUZZER_TYPES,
    SIDE_EFFECT_META_TYPES,
    SKIP_SMOKE_GATE_TYPES,
)

# ---------------------------------------------------------------------------
# (a) POLICY DUMP -- the empirical, code-of-record table (README is STALE).
# ---------------------------------------------------------------------------
def policy_dump():
    print("=" * 100)
    print("LIVE META_TASK_POLICY DUMP (harness/planner/taxonomies.py @ HEAD)")
    print("=" * 100)
    hdr = f"{'meta_task_type':22s} {'bypass_fuzzer':13s} {'skip_smoke':11s} {'skip_decomp':12s} {'stateful':9s} {'skip_ifz':9s}"
    print(hdr)
    print("-" * 100)
    for k in sorted(META_TASK_POLICY):
        v = META_TASK_POLICY[k]
        print(
            f"{k:22s} "
            f"{str(v.get('bypass_fuzzer')):13s} "
            f"{str(v.get('skip_smoke_gates', False)):11s} "
            f"{str(v.get('skip_structural_decomp', False)):12s} "
            f"{str(v.get('stateful_fuzz', False)):9s} "
            f"{str(v.get('skip_interface_fuzz', False)):9s}"
        )
    print("-" * 100)
    print(f"BYPASS_FUZZER_TYPES (NOT diff-fuzzed): {sorted(BYPASS_FUZZER_TYPES)}")
    print(f"data_model in BYPASS_FUZZER_TYPES?     {'data_model' in BYPASS_FUZZER_TYPES}   "
          f"(ac505d7 made it False => data_model IS diff-fuzzed)")
    print()


# ---------------------------------------------------------------------------
# Intent classification: SHOULD dual-agent synthesis of this kind of code be
# validated by DIFFERENTIAL FUZZING? Pure/deterministic transforms => YES.
# Side-effecting I/O / network / orchestration / env setup => NO (diff-fuzz is
# the wrong tool; oracle+smoke+wireup is the best-useful gate).
#   value: ('FUZZ'|'NO-FUZZ', rationale)
# This is the analyst's intent judgement -- printed alongside the empirical
# policy so divergences (policy says X, intent says Y) are visible.
# ---------------------------------------------------------------------------
INTENT = {
    "data_model":        ("FUZZ",    "pure deterministic structures/transforms -- diff-fuzz validates equivalence well"),
    "cli_tooling":       ("FUZZ",    "arg-parsing/formatting are largely pure transforms"),
    "refactor":          ("FUZZ",    "behavior-preserving by definition -> equivalence is exactly what fuzz checks"),
    "logging_observability": ("FUZZ", "formatters/serializers are pure-ish; fuzz catches divergent output"),
    "validation":        ("FUZZ",    "predicate/normalizer logic is deterministic"),
    "test_authoring":    ("NO-FUZZ", "authors an oracle, not impl; skip_interface_fuzz; non-vacuity mutant gate instead"),
    "state_machine":     ("FUZZ*",   "fuzzable but SEQUENCE-based -> stateful_fuzz path, not plain interface fuzz"),
    "io_adapter":        ("FUZZ*",   "fuzzed but side-effecting; relies on no skip_structural_decomp churn"),
    "sandbox_infra":     ("NO-FUZZ?","env/jail setup -- side-effecting; policy currently FUZZes it (debatable)"),
    "orchestration":     ("NO-FUZZ?","control-flow over side effects; policy currently FUZZes it (debatable)"),
    "harness_plumbing":  ("NO-FUZZ?","internal wiring; imports site-packages; policy FUZZes it (debatable)"),
    "planner_tooling":   ("NO-FUZZ?","plan-shaping side effects; policy FUZZes it (debatable)"),
    "harness_self_fix":  ("NO-FUZZ?","self-edits; policy FUZZes it (debatable)"),
    "mcp_server_change": ("NO-FUZZ", "server I/O wiring; bypass; smoke+narrow gates"),
    "mcp_plumbing":      ("NO-FUZZ", "transport plumbing; bypass+skip_decomp; smoke ON"),
    "config_schema":     ("NO-FUZZ", "schema wiring; bypass; smoke skipped"),
    "hooks_integration": ("NO-FUZZ", "event hooks side-effecting; bypass"),
    "docs_writing":      ("NO-FUZZ", "prose; nothing to fuzz; bypass"),
    "epic_planning":     ("NO-FUZZ", "meta-planning; bypass+skip_decomp+skip_smoke"),
    "test_unit":         ("NO-FUZZ", "authored tests; bypass"),
    "test_integration":  ("NO-FUZZ", "authored tests; bypass"),
    "test_e2e":          ("NO-FUZZ", "authored tests; bypass"),
    "test_acceptance":   ("NO-FUZZ", "authored tests; bypass"),
}


def classification_table():
    print("=" * 100)
    print("CLASSIFICATION: intent (should-diff-fuzz?) vs empirical policy")
    print("=" * 100)
    print(f"{'meta_task_type':22s} {'INTENT':10s} {'POLICY-fuzzes?':15s} {'best-useful gate if NO-FUZZ'}")
    print("-" * 100)
    for k in sorted(META_TASK_POLICY):
        v = META_TASK_POLICY[k]
        policy_fuzzes = not v.get("bypass_fuzzer") and not v.get("skip_interface_fuzz")
        intent, _ = INTENT.get(k, ("?", ""))
        if intent.startswith("FUZZ"):
            gate = "(diff-fuzz)"
        else:
            smoke = "smoke" if not v.get("skip_smoke_gates", False) else "NO-smoke"
            gate = f"oracle + {smoke} + embedded + narrow-fuzz + wire-up"
        flag = "" if (intent.startswith("FUZZ") == policy_fuzzes) else "   <== INTENT/POLICY DIVERGE"
        print(f"{k:22s} {intent:10s} {str(policy_fuzzes):15s} {gate}{flag}")
    print()


# ---------------------------------------------------------------------------
# (b) ROUTING PROTOTYPE.
#
# Current production gate (orchestrator_worker.py:816, orchestrator.py:1468/
# 1693/3388, diff_fuzzer.py:231) keys the fuzz-vs-bypass decision SOLELY on:
#       mtt in BYPASS_FUZZER_TYPES
# (plus stateful_fuzz / skip_interface_fuzz). No per-task field is consulted.
#
# PROPOSED DECOUPLING (option iii): introduce an ORTHOGONAL task field
# ``smoke_gated`` that the gate ORs into the bypass decision, so meta_task_type
# stays SEMANTICALLY TRUE. The escape-hatch then sets smoke_gated=True on the
# external survivor and STOPS retyping it to data_model.
#
# current_route():  the production routing logic, faithfully reproduced.
# proposed_route(): production logic + the orthogonal smoke_gated OR.
# Neither touches production; both are pure functions over a task dict.
# ---------------------------------------------------------------------------
def _stateful(mtt):
    return bool(META_TASK_POLICY.get(mtt, {}).get("stateful_fuzz"))


def _skip_ifz(mtt):
    return bool(META_TASK_POLICY.get(mtt, {}).get("skip_interface_fuzz"))


def current_route(task):
    """Reproduce production: which gate does this task hit TODAY?"""
    mtt = task.get("meta_task_type")
    if _stateful(mtt):
        return "stateful_fuzz"
    if mtt in BYPASS_FUZZER_TYPES or _skip_ifz(mtt):
        return "smoke+embedded+narrow (bypass_fuzzer)"
    return "diff-fuzz"


def proposed_route(task):
    """Production logic + orthogonal ``smoke_gated`` OR (the proposed fix)."""
    mtt = task.get("meta_task_type")
    if _stateful(mtt):
        return "stateful_fuzz"
    # THE ONE NEW CLAUSE: an explicit per-task smoke_gated flag bypasses fuzz
    # WITHOUT lying about the task's semantic meta_task_type.
    if task.get("smoke_gated") is True:
        return "smoke+embedded+narrow (smoke_gated)"
    if mtt in BYPASS_FUZZER_TYPES or _skip_ifz(mtt):
        return "smoke+embedded+narrow (bypass_fuzzer)"
    return "diff-fuzz"


def escape_hatch_current(survivor):
    """What the production escape-hatch does today: retype to data_model."""
    out = dict(survivor)
    out["meta_task_type"] = "data_model"
    return out


def escape_hatch_proposed(survivor):
    """Proposed escape-hatch: keep semantic type, set orthogonal smoke_gated."""
    out = dict(survivor)
    out["smoke_gated"] = True
    return out


# ---------------------------------------------------------------------------
# (c) 3 representative leaf descriptors + PASS/FAIL assertions.
# ---------------------------------------------------------------------------
def representative_leaves():
    return [
        # 1. PURE data-transform impl that SHOULD fuzz. Semantically data_model.
        dict(task_id="L1", meta_task_type="data_model",
             specification="pure dataclass + normalize() transform, no I/O"),
        # 2. NETWORK-LISTENER external survivor that should NOT fuzz (side effects,
        #    non-deterministic). Its HONEST semantic type is io_adapter (binds a
        #    socket / fs side effects). Under the escape-hatch it is an external
        #    impl survivor sharing its red-pair oracle's test-set.
        dict(task_id="L2", meta_task_type="io_adapter", is_external_survivor=True,
             specification="LoopbackListener: binds a socket, accepts conns, writes fs"),
        # 3. NORMAL internal impl that SHOULD fuzz. cli_tooling (pure-ish).
        dict(task_id="L3", meta_task_type="cli_tooling",
             specification="argparse front-end formatting a report string"),
    ]


def run_assertions():
    print("=" * 100)
    print("ROUTING PROOF: current escape-hatch vs proposed (orthogonal smoke_gated)")
    print("=" * 100)
    leaves = representative_leaves()
    failures = []

    def check(label, cond):
        status = "PASS" if cond else "FAIL"
        print(f"  [{status}] {label}")
        if not cond:
            failures.append(label)

    L1, L2, L3 = leaves

    print("\n-- L1 pure data_model impl: MUST stay diff-fuzzed (reliability guarantee) --")
    check("L1 current route == diff-fuzz", current_route(L1) == "diff-fuzz")
    check("L1 proposed route == diff-fuzz (unchanged)", proposed_route(L1) == "diff-fuzz")

    print("\n-- L2 network-listener external survivor --")
    print(f"     CURRENT escape-hatch retypes -> data_model, then routes:")
    L2_cur = escape_hatch_current(L2)
    cur_route_L2 = current_route(L2_cur)
    print(f"        retyped mtt={L2_cur['meta_task_type']!r}  route={cur_route_L2!r}")
    check("CURRENT: retyped-to-data_model survivor is WRONGLY diff-fuzzed",
          cur_route_L2 == "diff-fuzz")  # demonstrates the BUG: it gets fuzzed
    print(f"     PROPOSED escape-hatch keeps semantic type + sets smoke_gated:")
    L2_prop = escape_hatch_proposed(L2)
    prop_route_L2 = proposed_route(L2_prop)
    print(f"        kept   mtt={L2_prop['meta_task_type']!r}  smoke_gated={L2_prop['smoke_gated']}  route={prop_route_L2!r}")
    check("PROPOSED: survivor routes to smoke (NOT fuzzed)",
          prop_route_L2.startswith("smoke"))
    check("PROPOSED: survivor keeps its HONEST semantic type io_adapter (no data_model lie)",
          L2_prop["meta_task_type"] == "io_adapter")

    print("\n-- L3 normal internal cli_tooling impl: MUST stay diff-fuzzed --")
    check("L3 current route == diff-fuzz", current_route(L3) == "diff-fuzz")
    check("L3 proposed route == diff-fuzz (unchanged)", proposed_route(L3) == "diff-fuzz")

    print("\n-- GLOBAL INVARIANT: proposed fix NEVER reduces fuzz coverage for a "
          "task that is NOT explicitly smoke_gated --")
    cover_ok = True
    for k in META_TASK_POLICY:
        t = dict(task_id="probe", meta_task_type=k)  # no smoke_gated flag
        if current_route(t) != proposed_route(t):
            cover_ok = False
            print(f"        REGRESSION on {k}: {current_route(t)} -> {proposed_route(t)}")
    check("proposed_route == current_route for EVERY mtt when smoke_gated absent",
          cover_ok)

    print("\n" + "=" * 100)
    if failures:
        print(f"RESULT: {len(failures)} FAILED assertion(s): {failures}")
        return 1
    print("RESULT: ALL ASSERTIONS PASSED")
    print("  - data_model & cli_tooling impls STAY diff-fuzzed (guarantee intact)")
    print("  - network-listener survivor: CURRENT=wrongly-fuzzed, PROPOSED=smoke-gated w/ honest type")
    print("  - proposed flag is a strict superset: zero coverage change when smoke_gated is absent")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    policy_dump()
    classification_table()
    rc = run_assertions()
    sys.exit(rc)
