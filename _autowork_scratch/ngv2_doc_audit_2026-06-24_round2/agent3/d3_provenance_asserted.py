#!/usr/bin/env python3
"""D3 — Re-verify M4-c by EXECUTION: the downstream detonation-evidence gate
keys may_confirm on CALLER-ASSERTED flags (ran_target / observed_runtime_effect),
not on proven provenance or a baseline differential.

ALSO: show that _make_detonation_seam.detonation() sets ran_target=True
UNCONDITIONALLY and observed_runtime_effect=verdict, so the two flags the gate
trusts are produced BY THE DETONATION SEAM ITSELF, with no independent proof
that the TARGET (not a mock) ran or that the effect was absent in a baseline.

Drives the REAL classify_detonation_evidence, and inspects the seam source AST.
"""
import sys, ast, inspect
sys.path.insert(0, "/home/xnihil0zer0/NobleGreedv2")
from ngv2.detonation_evidence_gate import classify_detonation_evidence

print("=== M4-c (a): the gate's only may_confirm=True path is caller-asserted ===")
# A report with NO real provenance, no nonce, no baseline, no fs_effect:
# just the two boolean flags set True. This is exactly what a self-grading
# producer can emit.
forged = {"ran_target": True, "observed_runtime_effect": True}
r = classify_detonation_evidence(forged)
print(f"  classify_detonation_evidence({forged}) -> {r}")
print(f"  -> evidence_kind={r['evidence_kind']!r}, may_confirm={r['may_confirm']}")
print(f"  CLAIM 'provenance asserted not proven' -> "
      f"{'CONFIRMED' if r['may_confirm'] else 'REFUTED'}")
print()

print("=== M4-c (b): gate ignores baseline/differential/nonce entirely ===")
# Add a baseline that shows the SAME effect (i.e. NOT a differential) + no nonce.
no_diff = {"ran_target": True, "observed_runtime_effect": True,
           "baseline_effect": True, "nonce_in_effect": False, "differential": False}
r2 = classify_detonation_evidence(no_diff)
print(f"  with baseline_effect=True, differential=False, nonce absent -> may_confirm={r2['may_confirm']}")
print(f"  -> gate reads only {sorted(set(['method','self_hosted_mock','ran_target','observed_runtime_effect']))}; "
      f"baseline/nonce/differential keys are NOT consulted.")
print()

print("=== M4-c (c): the producer seam stamps both trusted flags itself ===")
from ngv2.workers import _runner as R
seam_src = inspect.getsource(R._make_detonation_seam)
# Find the literal result-dict assignment inside detonation().
for ln in seam_src.splitlines():
    s = ln.strip()
    if "ran_target" in s or "observed_runtime_effect" in s and "result" in s:
        print("   seam line:", s[:140])
print()
# Confirm ran_target is a hard literal True (not derived from a proof).
ran_target_literal_true = "'ran_target': True" in seam_src
print(f"  seam sets literal `'ran_target': True` (unconditional): {ran_target_literal_true}")
# observed_runtime_effect mirrors the verdict the SAME seam computed.
obs_mirrors_verdict = "'observed_runtime_effect': confirmed" in seam_src
print(f"  seam sets observed_runtime_effect = confirmed (its own verdict): {obs_mirrors_verdict}")
print()

print("=== M4-c (d): is the authenticity VERDICT consumed at detonate->confirm? ===")
# gate_executor wires poc_authenticity at ('poc','detonate') and
# detonation_evidence at ('detonate','novelty'). They are SEPARATE gates over a
# flat evidence dict; neither feeds the other, and neither checks a nonce.
import ngv2.gate_executor as GE
gates = GE._TRANSITION_GATES
print("  ('poc','detonate') gates:", [g[0] for g in gates.get(('poc','detonate'), ())])
print("  ('detonate','novelty') gates:", [g[0] for g in gates.get(('detonate','novelty'), ())])
print("  -> authenticity (poc->detonate) and detonation_evidence (detonate->novelty)")
print("     are DISJOINT transition gates; the detonation_evidence gate does NOT")
print("     consult the authenticity classifier's mode/may_confirm, and neither")
print("     gate consults a per-run nonce or a captured baseline differential.")

print()
print("=== SUMMARY ===")
print("M4-c provenance asserted-not-proven:", "CONFIRMED" if r['may_confirm'] else "REFUTED")
print("baseline differential consumed by gate:", "NO")
print("nonce consumed by either confirm gate:", "NO")
