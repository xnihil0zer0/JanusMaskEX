#!/usr/bin/env python3
"""D6 — Retro non-vacuity (X3.5) textual-echo probe.

For each landed closure (impl, oracle) pair, extract the DISTINCTIVE literals
the oracle asserts as EXPECTED (string/number constants that are not trivial),
then check whether the IMPL source echoes those same literals. An impl that
hard-codes its oracle's expected literals (rather than computing them) is the
gaming signature the answer-key leak enabled.

This is a HEURISTIC screen (false-positives possible for legitimately-shared
domain literals like 'confirmed'); it surfaces candidates for a real mutation
recheck, which is what X3.5 mandates.
"""
import ast, pathlib, re
NG = pathlib.Path("/home/xnihil0zer0/NobleGreedv2")

# (impl, oracle) closure pairs landed in the leak era / wave-1+2.
PAIRS = [
    ("ngv2/detonation.py",              "tests/ngv2/test_p12_detonation_verdict_provenance.py"),
    ("ngv2/poc_authenticity_gate.py",   "tests/ngv2/test_p12_classify_poc_authenticity_provenance.py"),
    ("ngv2/detonation.py",              "tests/test_detonation_semantic_verdict.py"),
    ("ngv2/conductor_seams.py",         "tests/test_conductor_seams_wired.py"),
    ("ngv2/fsm_detect.py",              "tests/ngv2/test_fsm_detect.py"),
    ("ngv2/fsm_provision.py",           "tests/ngv2/test_fsm_provision.py"),
    ("ngv2/fsm_jail_build.py",          "tests/ngv2/test_fsm_jail_build.py"),
]

# Domain words that are SHARED-by-design (not a gaming signal).
COMMON = {"confirmed","refuted","error","inconclusive","may_confirm","verdict","mode",
          "real_target","self_contained_mock","network_live","live_execution",
          "static_assertion","mock_execution","unproven","VULNERABLE","ran_target",
          "observed_runtime_effect","exit_code","stdout","stderr","detect","provision",
          "jail_build","advance","blocked_by","results","evidence_kind","downgraded_verdict",
          "advance_gate","phase_artifact_hash","detect_input","prev_artifact","artifact",
          "ok","status","reason","python","py","js","node","bwrap"}

def literals(path):
    src = pathlib.Path(NG, path).read_text()
    out = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out, src
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant):
            v = n.value
            if isinstance(v, str):
                s = v.strip()
                if len(s) >= 6 and s not in COMMON and not s.startswith("#") and " " not in s[:0]:
                    out.add(("str", s))
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                if abs(v) >= 1000 or (isinstance(v, float) and v not in (0.0,1.0)):
                    out.add(("num", v))
    return out, src

print("=== Textual-echo screen: does IMPL echo ORACLE's distinctive expected literals? ===\n")
flagged_any = False
for impl, oracle in PAIRS:
    if not pathlib.Path(NG, impl).exists() or not pathlib.Path(NG, oracle).exists():
        print(f"  SKIP (missing): {impl} | {oracle}")
        continue
    or_lits, _ = literals(oracle)
    _, impl_src = literals(impl)
    echoed = sorted({l for (k,l) in or_lits if isinstance(l,str) and l in impl_src}, key=str)
    echoed += sorted({l for (k,l) in or_lits if not isinstance(l,str) and str(l) in impl_src}, key=str)
    print(f"--- {impl}  <-  {oracle}")
    print(f"    distinctive oracle literals: {len(or_lits)}; echoed verbatim in impl: {len(echoed)}")
    if echoed:
        flagged_any = True
        for e in echoed[:12]:
            print(f"      ECHO: {e!r}")
    else:
        print("      (no distinctive oracle literal echoed verbatim in impl — clean)")
    print()

print("=== INTERPRETATION ===")
print("Echoes here are CANDIDATES for the X3.5 mutation recheck, not proof of gaming.")
print(f"any candidate echo found: {flagged_any}")
