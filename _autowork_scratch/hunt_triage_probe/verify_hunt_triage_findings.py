"""ADVERSARIAL verification of the hunt->triage findings wiring (fe8384c).

Independently drives build_default_seams -> build_evidence -> gate_executor
for the ('hunt','triage') transition. Tests:
  POS: non-empty prior_findings -> gate ADVANCES, value TRACEABLE (not constant)
  NEG: empty/absent prior_findings -> gate BLOCKS (findings:missing_evidence)
  ANTI-GAMING: the derived value must equal the supplied findings, by sentinel.

Run: cd /home/xnihil0zer0/NobleGreedv2 && .venv/bin/python \
  /home/xnihil0zer0/JanusMaskJR/_autowork_scratch/hunt_triage_probe/verify_hunt_triage_findings.py
"""
import json
import sys
from ngv2.conductor_seams import build_default_seams
from ngv2 import gate_executor

SENT = "ADVERSARIAL_SENTINEL_0xCAFEF00D"
fails = []


def banner(t):
    print("\n" + "=" * 60)
    print(t)
    print("=" * 60)


# ---- POSITIVE: non-empty prior_findings ----
banner("POSITIVE CASE: non-empty prior_findings")
finding = {"id": "F-POS-1", "title": "SQLi", "category": "CWE-89",
           "description": "carries marker " + SENT,
           "expected_signature": "os.system(cmd)"}
state_pos = {"session_id": "s1", "phase": "hunt",
             "prior_findings": [finding], "evidence": {}}
seams = build_default_seams("s1", None, None, {"session_id": "s1"})
ev_pos = seams["build_evidence"](state_pos)
print("'findings' in evidence:", "findings" in ev_pos)
print("evidence['findings'] type:", type(ev_pos.get("findings")).__name__)
print("evidence['findings'][0]['id']:", (ev_pos.get("findings") or [{}])[0].get("id"))
print("sentinel in derived desc:", SENT in json.dumps(ev_pos.get("findings")))
# Drive the REAL gate executor directly (not via seam, to be independent)
g_pos = gate_executor.run_gates("hunt", "triage", ev_pos)
print("GATE advance:", g_pos.get("advance"))
print("GATE blocked_by:", g_pos.get("blocked_by"))
print("GATE results:", g_pos.get("results"))
if not ("findings" in ev_pos):
    fails.append("POS: 'findings' not in evidence")
if not (g_pos.get("advance") is True and not g_pos.get("blocked_by")):
    fails.append("POS: gate did NOT advance")
# Traceability: derived findings must be the SAME object/content we supplied
if SENT not in json.dumps(ev_pos.get("findings")):
    fails.append("POS: sentinel NOT traceable in derived findings (constant?)")
if ev_pos.get("findings") != [finding]:
    fails.append("POS: derived findings != supplied prior_findings")

# ---- NEGATIVE: empty prior_findings (THE anti-gaming test) ----
banner("NEGATIVE CASE: empty prior_findings (anti-gaming)")
state_neg = {"session_id": "s1", "phase": "hunt",
             "prior_findings": [], "evidence": {}}
ev_neg = seams["build_evidence"](state_neg)
print("'findings' in evidence:", "findings" in ev_neg)
print("evidence.get('findings'):", repr(ev_neg.get("findings")))
g_neg = gate_executor.run_gates("hunt", "triage", ev_neg)
print("GATE advance:", g_neg.get("advance"))
print("GATE blocked_by:", g_neg.get("blocked_by"))
if g_neg.get("advance") is True:
    fails.append("NEG: GAMED -- gate advanced with NO prior_findings")
if not any("findings" in b for b in (g_neg.get("blocked_by") or [])):
    fails.append("NEG: blocked_by has no findings requirement")

# ---- NEGATIVE 2: prior_findings absent entirely ----
banner("NEGATIVE CASE 2: prior_findings key ABSENT")
state_abs = {"session_id": "s1", "phase": "hunt", "evidence": {}}
ev_abs = seams["build_evidence"](state_abs)
print("'findings' in evidence:", "findings" in ev_abs)
g_abs = gate_executor.run_gates("hunt", "triage", ev_abs)
print("GATE advance:", g_abs.get("advance"))
print("GATE blocked_by:", g_abs.get("blocked_by"))
if g_abs.get("advance") is True:
    fails.append("NEG2: GAMED -- gate advanced with absent prior_findings")

# ---- ANTI-GAMING 3: distinct findings produce DISTINCT evidence ----
banner("ANTI-GAMING 3: distinct findings -> distinct evidence (not constant)")
alt = {"id": "F-ALT-XYZ", "title": "PathTrav", "description": "different_marker_ZZZ"}
state_alt = {"session_id": "s1", "phase": "hunt",
             "prior_findings": [alt], "evidence": {}}
ev_alt = seams["build_evidence"](state_alt)
print("ev_pos findings id:", ev_pos["findings"][0]["id"])
print("ev_alt findings id:", ev_alt["findings"][0]["id"])
if ev_pos["findings"][0]["id"] == ev_alt["findings"][0]["id"]:
    fails.append("ANTI-GAMING: two distinct inputs yield SAME findings (constant!)")

banner("RESULT")
if fails:
    print("FAIL")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL ASSERTIONS PASS -- findings derived from carried state, gate gated correctly")
sys.exit(0)
