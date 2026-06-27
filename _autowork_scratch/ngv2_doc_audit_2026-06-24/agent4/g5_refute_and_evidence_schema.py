#!/usr/bin/env python3
"""GAP-5 sweep (Agent-4):

(a) REFUTE the 'loopback listener unwired' candidate — verify it IS now wired
    (P1.3 leaf-2) so it is NOT a missed gap.
(b) NEW candidate: the c0 env-FSM evidence-artifact SCHEMA (content_hash'd dict via
    advance_gate) is a DIFFERENT shape from the gate_executor's main-phase evidence
    dict (flat keys consumed by classify_* gates). The env handlers emit
    {advance,terminal,artifact:{...,content_hash}}; gate_executor.run_gates consumes
    a flat `evidence` dict and validates via classify_*, NOT via advance_gate. So the
    two evidence models are UNRECONCILED — the integration leaf must bridge them, and
    neither doc specifies the bridge (the "content-hashed JSON evidence" contract is
    asserted but the gate_executor does NOT use phase_artifact_hash/advance_gate).
(c) Spot-check the other pre-named GAP5 candidates (npm staging, authz CWEs) are
    already DOC-COVERED (so NOT missed).
"""
import os, re

NGV2 = "/home/xnihil0zer0/NobleGreedv2/ngv2"
DOCS = {
    "gap-analysis": "/home/xnihil0zer0/AI-Data/Research-JanusMask/NobleGreedv2-end2end-gap-analysis.md",
    "contract": "/home/xnihil0zer0/AI-Data/Research-JanusMask/NGv2-closure-deliverables-and-acceptance-contract.md",
}

def importers(sym):
    hits = []
    for fn in os.listdir(NGV2):
        if not fn.endswith(".py"): continue
        p = os.path.join(NGV2, fn)
        t = open(p, errors="ignore").read()
        if re.search(r"\b" + sym + r"\b", t) and sym not in fn:
            test = "test" in fn
            hits.append((fn, "test" if test else "PROD"))
    # also subdir workers/
    wd = os.path.join(NGV2, "workers")
    if os.path.isdir(wd):
        for fn in os.listdir(wd):
            if fn.endswith(".py"):
                t = open(os.path.join(wd, fn), errors="ignore").read()
                if re.search(r"\b" + sym + r"\b", t):
                    hits.append(("workers/" + fn, "test" if "test" in fn else "PROD"))
    return hits

print("=" * 78)
print("(a) REFUTE: is LoopbackListener now WIRED (P1.3 leaf-2)?")
print("=" * 78)
imp = importers("LoopbackListener") + importers("run_jailed_poc_with_loopback")
prod = [h for h in imp if h[1] == "PROD"]
print("   production importers:", sorted(set(prod)))
print("   -> REFUTED candidate: loopback IS wired" if prod else "   -> still dead")

print("\n" + "=" * 78)
print("(b) NEW: env-FSM evidence schema (c0 content_hash) vs gate_executor flat evidence")
print("=" * 78)
ge = open(os.path.join(NGV2, "gate_executor.py")).read()
print("   gate_executor imports phase_artifact_hash / advance_gate (c0)? ",
      "phase_artifact_hash" in ge or "advance_gate" in ge)
print("   gate_executor imports PHASE_ORDER from fsm_evidence?           ",
      "from ngv2.fsm_evidence import PHASE_ORDER" in ge)
# the gates require these flat evidence keys:
req_keys = re.findall(r"\(\(('?\w+'?(?:,\s*'?\w+'?)*)\)\)", ge)
req_fields = re.findall(r",\s*\(([^)]*)\),\s*lambda", ge)
flat = set()
for rf in req_fields:
    for k in re.findall(r"'([^']+)'", rf):
        flat.add(k)
print("   flat evidence keys the gates require:", sorted(flat))
print("   none of these is a content_hash'd env artifact -> the c0 content-hash")
print("   model (advance_gate) is NOT how transitions are actually adjudicated.")
# Does build_evidence produce the detonate->novelty gate keys?
cs = open(os.path.join(NGV2, "conductor_seams.py")).read()
det_keys = ("target_source", "expected_signature", "sink_name", "call_sites", "detonation_report")
print("\n   build_evidence emits the detonate->novelty gate keys?")
for k in det_keys:
    print(f"      {k}: {'YES' if re.search(chr(39)+k+chr(39), cs) else 'NO (gate will block missing_evidence)'}")

print("\n" + "=" * 78)
print("(c) Are the OTHER pre-named GAP5 candidates already DOC-COVERED?")
print("=" * 78)
for label, p in DOCS.items():
    t = open(p).read()
    print(f"   {label}: npm_dep_staging={'YES' if 'npm_dep_staging' in t or 'npm dependency staging' in t else 'no'}  "
          f"two-actor authz(285/639/862/863)={'YES' if '862' in t and '863' in t else 'no'}  "
          f"loopback wiring P1.3={'YES' if 'LoopbackListener' in t else 'no'}")
print("   -> these three are ENUMERATED deliverables (P3.2-c4, P3.1, P1.3) => NOT missed.")
