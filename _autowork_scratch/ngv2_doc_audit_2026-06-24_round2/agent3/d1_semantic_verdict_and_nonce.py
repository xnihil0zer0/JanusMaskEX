#!/usr/bin/env python3
"""D1 — Re-verify (by EXECUTION) the two M2/M4-b trust claims on the FS-signature
verdict path:

  (M2) empty/whitespace expected_fs_signature now REFUSES (was 'confirmed').
  (M4-b) the per-run nonce is OPT-IN, not REQUIRED, on the live confirm path:
         DetonationChamber.detonate -> semantic_verdict NEVER passes nonce,
         so a 'confirmed' is reachable with NO nonce anywhere in the evidence.

Drives the REAL ngv2.detonation functions. No stubbing needed (pure stdlib core).
Run from the NobleGreedv2 repo root.
"""
import sys, json
sys.path.insert(0, "/home/xnihil0zer0/NobleGreedv2")

from ngv2.detonation import semantic_verdict, DetonationChamber
from ngv2.contracts import PoC

print("=== D1: semantic_verdict empty-sig (M2) ===")
cases = [
    ("empty sig",        dict(exit_code=0, stdout="VULNERABLE", stderr="", fs_snapshot_diff="A pwned\nM foo", success_marker="VULNERABLE", expected_fs_signature="")),
    ("whitespace sig",   dict(exit_code=0, stdout="VULNERABLE", stderr="", fs_snapshot_diff="A pwned",        success_marker="VULNERABLE", expected_fs_signature="   ")),
    ("real sig present",  dict(exit_code=0, stdout="VULNERABLE", stderr="", fs_snapshot_diff="A pwned_canary", success_marker="VULNERABLE", expected_fs_signature="pwned_canary")),
]
for name, kw in cases:
    v = semantic_verdict(**kw)
    print(f"  [{name}] -> {v!r}   (kw.expected_fs_signature={kw['expected_fs_signature']!r})")

print()
print("=== D1: is the nonce REQUIRED or merely OPT-IN on the live confirm path? ===")
# (a) Call semantic_verdict directly with a real sig, NO nonce kwarg.
v_no_nonce = semantic_verdict(0, "VULNERABLE", "", "A pwned_canary",
                              success_marker="VULNERABLE",
                              expected_fs_signature="pwned_canary")
print(f"  (a) semantic_verdict(real sig, NO nonce arg)            -> {v_no_nonce!r}")
assert v_no_nonce == "confirmed", "expected confirm with no nonce supplied"

# (b) Same evidence WITHOUT the nonce anywhere; supply a nonce that is ABSENT.
v_nonce_absent = semantic_verdict(0, "VULNERABLE", "", "A pwned_canary",
                                  success_marker="VULNERABLE",
                                  expected_fs_signature="pwned_canary",
                                  nonce="RUNNONCE_DEADBEEF")
print(f"  (b) semantic_verdict(real sig, nonce='RUNNONCE...' ABSENT) -> {v_nonce_absent!r}")

# (c) The LIVE confirm path: DetonationChamber.detonate -> semantic_verdict.
#     The runner returns a 5-tuple (exit, out, err, dur, fs_diff). NOTE: detonate()
#     has NO nonce parameter, so it can NEVER pass a nonce to semantic_verdict.
def runner_no_nonce(poc, target_spec):
    # PoC-controlled outputs; NO per-run nonce anywhere.
    return (0, "VULNERABLE", "", 7, "A pwned_canary")

chamber = DetonationChamber(success_marker="VULNERABLE")
poc = PoC(finding_id="F-1", language="python", code="print('x')", entrypoint="")
rep = chamber.detonate(poc, target_spec={}, runner=runner_no_nonce,
                       expected_fs_signature="pwned_canary")
print(f"  (c) DetonationChamber.detonate(...) verdict             -> {rep.verdict!r}")
print(f"      -> Does detonate() even ACCEPT a nonce?  "
      f"{'nonce' in DetonationChamber.detonate.__code__.co_varnames}")

# (d) Prove the gate IS reachable to enforce a nonce when supplied (shows the
#     mechanism EXISTS but is simply never invoked by the live callers).
v_nonce_present = semantic_verdict(0, "VULNERABLE RUNNONCE_DEADBEEF", "",
                                   "A pwned_canary_RUNNONCE_DEADBEEF",
                                   success_marker="VULNERABLE",
                                   expected_fs_signature="pwned_canary",
                                   nonce="RUNNONCE_DEADBEEF")
print(f"  (d) semantic_verdict(.., nonce PRESENT in evidence)     -> {v_nonce_present!r}")

print()
print("=== VERDICT ===")
print("M2 (empty-sig refuses): " +
      ("CONFIRMED" if semantic_verdict(0,'VULNERABLE','','A x',success_marker='VULNERABLE',expected_fs_signature='')=='refuted' else "REFUTED"))
print("M4-b (nonce dead/opt-in on live verdict path): " +
      ("CONFIRMED — live confirm with NO nonce" if rep.verdict=='confirmed' else "REFUTED"))
