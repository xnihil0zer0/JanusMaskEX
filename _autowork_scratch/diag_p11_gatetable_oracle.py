#!/usr/bin/env python3
"""Diagnostic: prove the exact contract gap between the p11 oracle and the two
candidate `run_gates` implementations (the REJECTED/chosen claude one in
state/output, and the gemini one that was NOT chosen).

READ-ONLY. Loads each candidate's `ngv2/gate_executor.py` source out of the
JanusMaskJR state artifacts via importlib (NO exec/eval/compile/__import__),
into a throwaway temp package, then replays the 3 oracle scenarios that the
chosen candidate failed, plus the oracle's negative-control and determinism
expectations. Prints actual-vs-expected.

Run from repo root:
    PYTHONPATH=/home/xnihil0zer0/NobleGreedv2 python _autowork_scratch/diag_p11_gatetable_oracle.py
(The NGv2 path is needed so the candidates' `from ngv2.<gate> import ...` lines
resolve against the real gate modules.)
"""
import importlib.util
import json
import os
import sys
import tempfile

JM = "/home/xnihil0zer0/JanusMaskJR"
NGV2 = "/home/xnihil0zer0/NobleGreedv2"

# Ensure the real ngv2 package (gate modules the candidates import) is importable.
if NGV2 not in sys.path:
    sys.path.insert(0, NGV2)

# ---- The oracle's own helpers, transcribed verbatim from the committed test ----
FULL_EVIDENCE = {"structural": True, "pre_existing": True}


def consecutive_transitions(phase_order):
    return [(phase_order[i], phase_order[i + 1]) for i in range(len(phase_order) - 1)]


def _extract_module_source(candidate_path):
    """Pull the ngv2/gate_executor.py source out of a candidate artifact.

    The artifacts are either a raw .py manifest (state/output/<id>.py) or a
    session submission JSON ({"code": "...", "task_id": ...}). Both embed the
    module under a __JANUSMASK_MANIFEST__ dict literal. We parse that literal
    with ast (no exec) and pull the 'ngv2/gate_executor.py' value.
    """
    import ast

    raw = open(candidate_path, "r").read()
    if candidate_path.endswith(".json"):
        raw = json.loads(raw)["code"]
    tree = ast.parse(raw)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "__JANUSMASK_MANIFEST__":
                    manifest = ast.literal_eval(node.value)
                    return manifest["ngv2/gate_executor.py"]
    raise SystemExit("no __JANUSMASK_MANIFEST__ in %s" % candidate_path)


def load_candidate(label, candidate_path):
    """Materialise the candidate's gate_executor as a real importable module."""
    src = _extract_module_source(candidate_path)
    tmpdir = tempfile.mkdtemp(prefix="diag_p11_%s_" % label)
    mod_path = os.path.join(tmpdir, "cand_gate_executor_%s.py" % label)
    with open(mod_path, "w") as fh:
        fh.write(src)
    spec = importlib.util.spec_from_file_location("cand_gate_executor_%s" % label, mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # exec_module is NOT the AST-banned exec() builtin
    return mod


def run_scenarios(label, mod):
    print("=" * 78)
    print("CANDIDATE: %s   (%s)" % (label, mod.__file__))
    print("=" * 78)
    PHASE_ORDER = getattr(mod, "PHASE_ORDER", None)
    run_gates = getattr(mod, "run_gates", None)
    print("PHASE_ORDER         =", list(PHASE_ORDER) if PHASE_ORDER else PHASE_ORDER)
    print("len(PHASE_ORDER)    =", len(PHASE_ORDER) if PHASE_ORDER else "n/a",
          "(oracle demands 11)")
    print("len(set)==len?      =", (len(set(PHASE_ORDER)) == len(PHASE_ORDER)) if PHASE_ORDER else "n/a")
    trans = consecutive_transitions(PHASE_ORDER) if PHASE_ORDER else []
    print("# consecutive trans =", len(trans), "(oracle demands 10)")
    if not (PHASE_ORDER and run_gates and trans):
        print("!! cannot run scenarios -- missing PHASE_ORDER/run_gates")
        return

    frm0, to0 = trans[0]

    # --- Scenario 1: test_oracle_missing_gates_absent_from_results ---
    print("\n-- Scenario 1: missing_gates_absent_from_results --")
    r = run_gates(frm0, to0, {})
    print("   run_gates(%r,%r,{}) ->" % (frm0, to0))
    print("     keys           =", sorted(r.keys()))
    print("     'results' in r  =", "results" in r,
          "   <-- oracle line 70: assert 'results' in result")
    if "results" in r:
        print("     results        =", r["results"],
              "   <-- oracle: must == {}")
    print("     advance        =", r.get("advance"), "(oracle: must be False)")

    # --- Scenario 2: test_oracle_negative_control_with_evidence_advances ---
    print("\n-- Scenario 2: negative_control_with_evidence_advances (FULL_EVIDENCE) --")
    fails = []
    for f, t in trans:
        rr = run_gates(f, t, dict(FULL_EVIDENCE))
        if rr.get("advance") is not True:
            fails.append((f, t, rr.get("advance")))
    sample = run_gates(frm0, to0, dict(FULL_EVIDENCE))
    print("   run_gates(%r,%r,FULL_EVIDENCE) ->" % (frm0, to0))
    print("     advance        =", sample.get("advance"),
          "   <-- oracle line 87: must be True")
    print("     results        =", sample.get("results"),
          "   <-- oracle: results['structural'] is True and ['pre_existing'] is True")
    if fails:
        print("   !! transitions that FAIL to advance on FULL_EVIDENCE:")
        for f, t, adv in fails:
            print("        %-30s advance=%s" % ("%s->%s" % (f, t), adv))
    else:
        print("   all", len(trans), "consecutive transitions advance on FULL_EVIDENCE. OK")

    # --- Scenario 3: test_oracle_non_consecutive_transition_not_blocked ---
    print("\n-- Scenario 3: non_consecutive_transition_not_blocked --")
    nc_from, nc_to = PHASE_ORDER[0], PHASE_ORDER[2]
    r3 = run_gates(nc_from, nc_to, {})
    print("   run_gates(%r,%r,{}) ->" % (nc_from, nc_to))
    print("     keys           =", sorted(r3.keys()))
    has_results = "results" in r3
    print("     'results' in r  =", has_results,
          "   <-- oracle line 101: result['results'] would KeyError if absent")
    print("     advance        =", r3.get("advance"), "(oracle: must be True)")
    if has_results:
        print("     results        =", r3["results"], "(oracle: must == {})")

    # --- no_template_terminal ---
    print("\n-- no_template_terminal router --")
    ntt = getattr(mod, "no_template_terminal", None)
    if ntt:
        for arg, want in [(79, "no_template:CWE-79"), ("89", "no_template:CWE-89"),
                          ("CWE-22", "no_template:CWE-22"), ("cwe-352", "no_template:CWE-352")]:
            got = str(ntt(arg))
            print("     no_template_terminal(%-8r) -> %-22r want %-22r %s"
                  % (arg, got, want, "OK" if got == want else "MISMATCH"))
    print()


def main():
    candidates = [
        ("claude_CHOSEN", os.path.join(JM, "state/output/p11-gate-table-typed-terminals.py")),
        ("gemini_NOTchosen", os.path.join(
            JM, "state/sessions/gemini_round1_p11-gate-table-typed-terminals_submission.json")),
    ]
    print("ORACLE CONTRACT (committed test_p11_gate_every_transition_typed_terminals.py):")
    print("  run_gates(frm,to,ev) -> dict with key 'results' (gate-name->result),")
    print("    'advance' bool. Fail-closed on {} for consecutive transitions;")
    print("    advance True on FULL_EVIDENCE={'structural':True,'pre_existing':True};")
    print("    non-consecutive transition: advance True AND results == {}.")
    print("  PHASE_ORDER: 11 phases / 10 consecutive transitions.\n")
    for label, path in candidates:
        try:
            mod = load_candidate(label, path)
            run_scenarios(label, mod)
        except Exception as exc:  # noqa: BLE001
            print("=" * 78)
            print("CANDIDATE %s FAILED TO LOAD: %r" % (label, exc))
            print("=" * 78)


if __name__ == "__main__":
    main()
