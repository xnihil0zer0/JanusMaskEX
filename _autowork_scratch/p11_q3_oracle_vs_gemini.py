"""Q3: does the gemini gate-table candidate actually pass the abstract oracle?
And does the abstract oracle test per-phase keys at all?

We materialize the gemini candidate's ngv2/gate_executor.py (from its manifest) to a
temp module and import the abstract oracle's run_gates expectations against it WITHOUT
pytest plugin overhead, by replicating each abstract-oracle assertion inline.
We use importlib spec.loader.exec_module only.
"""
import importlib.util
import json
import os
import sys

SCRATCH = "/home/xnihil0zer0/JanusMaskJR/_autowork_scratch"


def load_module(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


# Materialize gemini candidate gate_executor.py
cand_holder = load_module("p11_gt_holder",
                          "/home/xnihil0zer0/JanusMaskJR/state/output/p11-gate-table-typed-terminals.py")
manifest = cand_holder.__JANUSMASK_MANIFEST__
ge_src = manifest["ngv2/gate_executor.py"]
ge_path = os.path.join(SCRATCH, "_gemini_gate_executor.py")
with open(ge_path, "w") as fh:
    fh.write(ge_src)
ge = load_module("_gemini_ge", ge_path)

print("gemini PHASE_ORDER:", ge.PHASE_ORDER)
print("gemini run_gates return keys (sample):",
      sorted(ge.run_gates(ge.PHASE_ORDER[0], ge.PHASE_ORDER[1], {}).keys()))

# Replicate abstract oracle key assertions against gemini candidate
results = []

def check(name, fn):
    try:
        fn()
        results.append((name, "PASS"))
    except AssertionError as e:
        results.append((name, f"FAIL: {e}"))
    except Exception as e:
        results.append((name, f"ERROR: {type(e).__name__}: {e}"))

PO = ge.PHASE_ORDER
def consec():
    return [(PO[i], PO[i + 1]) for i in range(len(PO) - 1)]

FULL = {"structural": True, "pre_existing": True}

# oracle test 2: 10 consecutive transitions / 11 phases
check("phase_order_10_consec_11_phases",
      lambda: (_ for _ in ()).throw(AssertionError("len!=11")) if len(PO) != 11 else None)

# oracle test 3: all consecutive fail-closed on {}
def t3():
    for f, t in consec():
        r = ge.run_gates(f, t, {})
        assert r["advance"] is False, f"{f}->{t} advanced on empty"
check("all_consec_fail_closed_empty", t3)

# oracle test 4: results == {} on empty
def t4():
    f, t = consec()[0]
    r = ge.run_gates(f, t, {})
    assert "results" in r, "no results key"
    assert r["results"] == {}, f"results not empty: {r['results']}"
check("missing_gates_absent_from_results", t4)

# oracle test 6: negative control FULL_EVIDENCE advances + results structural/pre_existing True
def t6():
    for f, t in consec():
        r = ge.run_gates(f, t, dict(FULL))
        assert r["advance"] is True, f"{f}->{t} did not advance on FULL_EVIDENCE"
        assert r["results"].get("structural") is True
        assert r["results"].get("pre_existing") is True
check("negative_control_FULL_EVIDENCE_advances", t6)

# oracle test 7: non-consecutive PHASE_ORDER[0]->[2] advances, results {}
def t7():
    r = ge.run_gates(PO[0], PO[2], {})
    assert r["advance"] is True
    assert r["results"] == {}
check("non_consecutive_advances", t7)

print("\n=== gemini candidate vs ABSTRACT oracle assertions ===")
for n, s in results:
    print(f"  [{ 'OK ' if s=='PASS' else 'XX ' }] {n}: {s}")

passes = sum(1 for _, s in results if s == "PASS")
print(f"\n  gemini candidate passes {passes}/{len(results)} of the abstract oracle's core asserts")

print("\n=== Does the abstract oracle test ANY per-phase key? ===")
oracle_src = open("/home/xnihil0zer0/NobleGreedv2/tests/ngv2/test_p11_gate_every_transition_typed_terminals.py").read()
perphase_keys = ["source_ready", "findings", "triage_result", "verify_result",
                 "novelty_result", "report_artifact", "submission_result"]
hits = [k for k in perphase_keys if k in oracle_src]
print("  per-phase keys referenced in abstract oracle source:", hits or "NONE")
typed_terms = ["NO_SOURCE", "NO_FINDINGS", "NO_TRIAGE", "NO_VERIFY", "NO_NOVELTY",
               "NO_REPORT", "NO_APPROVAL", "NO_SUBMISSION", "EMPTY_HUNT", "REFUTED",
               "SERVICE_NO_BIND", "MISSING_EVIDENCE"]
tt_hits = [t for t in typed_terms if t in oracle_src]
print("  per-phase typed-terminal enum names referenced in abstract oracle:", tt_hits or "NONE")
print("  abstract keys referenced:", [k for k in ("structural", "pre_existing") if k in oracle_src])
