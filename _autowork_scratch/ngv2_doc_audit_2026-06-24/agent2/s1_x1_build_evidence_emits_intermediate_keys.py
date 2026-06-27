#!/usr/bin/env python3
"""
AGENT-2 / s1 — Test the doc's central X1/P1.1 acceptance claim.

The contract's §8 (2026-06-23 entry) and the §7 ledger assert:
  "_PHASE_COUNT_KEY is **still 3-of-7** and build_evidence still omits
   triage_result/verify_result/novelty_result/report_artifact ... X1 remains
   unclosed; P1.1 stays ◐".
and §4 P1.2 / P1.3 are marked ☐ (not started).

This script empirically checks the CURRENT live NGv2 source for:
  (a) whether persist() bumps the intermediate phase counts
      (triaged/verified/novelties/report_count) — the X1 cross-process gap #1,
  (b) whether build_evidence() emits the intermediate gate keys
      (triage_result/verify_result/novelty_result/report_artifact) — gap #2,
  (c) git log proof that p11-build-evidence-perphase-impl, P1.2, P1.3 landed.

Pure static/source inspection — no NGv2 import needed (avoids dep issues).
"""
import re
import subprocess
import sys

NGV2 = "/home/xnihil0zer0/NobleGreedv2"
SEAMS = f"{NGV2}/ngv2/conductor_seams.py"
GATE = f"{NGV2}/ngv2/gate_executor.py"

src = open(SEAMS).read()

print("=" * 72)
print("s1: X1 cross-process wiring — does the doc's 'still 3-of-7 / X1 unclosed'")
print("    claim (§8 2026-06-23) still hold against live NGv2 source?")
print("=" * 72)

# (a) persist bumps intermediate counts?
print("\n--- (a) persist() intermediate-count bumps ---")
m = re.search(r"count_fields\s*=\s*\{[^}]*\}", src)
print("count_fields literal in persist():", m.group(0) if m else "NOT FOUND")
for k in ("triaged", "verified", "novelties", "report_count"):
    has = bool(re.search(rf"state\[[^\]]*{k}[^\]]*\]\s*=", src)) or (m and k in m.group(0))
    print(f"  persist sets phase-count '{k}': {has}")

# (b) build_evidence emits intermediate gate keys?
print("\n--- (b) build_evidence() intermediate gate-key emission ---")
# locate build_evidence body
be_start = src.index("def build_evidence(")
be_body = src[be_start:]
for k in ("triage_result", "verify_result", "novelty_result", "report_artifact"):
    emits = bool(re.search(rf"ev\[['\"]{k}['\"]\]\s*=", be_body))
    print(f"  build_evidence emits ev['{k}'] = ...: {emits}")

# _PHASE_COUNT_KEY size
m2 = re.search(r"_PHASE_COUNT_KEY\s*=\s*\{[^}]*\}", src)
pck = m2.group(0) if m2 else ""
n_keys = pck.count(":")
print(f"\n  _PHASE_COUNT_KEY literal: {pck}")
print(f"  _PHASE_COUNT_KEY size: {n_keys} keys (doc says 'still 3-of-7')")
print("  NOTE: the doc's gap-1 was that persist did NOT bump the OTHER 4 phases;")
print("        check whether a SEPARATE count_fields dict now covers them (above).")

# (c) git proof
print("\n--- (c) git log: did the impl + P1.2 + P1.3 land? ---")
for pat in ("build-evidence-perphase-impl", "build-evidence-perphase",
            "p12-classify-poc-authenticity-provenance",
            "p12-detonation-verdict-provenance-impl",
            "wire-loopback-per-cwe-channels-impl"):
    out = subprocess.run(
        ["git", "-C", NGV2, "log", "--oneline", "--all", "--grep", pat],
        capture_output=True, text=True).stdout.strip()
    print(f"  grep '{pat}':\n    {out if out else '(no commit)'}")

print("\n=== VERDICT ===")
persist_ok = all(
    (m and k in m.group(0)) for k in ("triaged", "verified", "novelties", "report_count")
)
be_ok = all(
    re.search(rf"ev\[['\"]{k}['\"]\]\s*=", be_body)
    for k in ("triage_result", "verify_result", "novelty_result", "report_artifact")
)
print(f"persist bumps all 4 intermediate counts (count_fields): {persist_ok}")
print(f"build_evidence emits all 4 intermediate gate keys:       {be_ok}")
if persist_ok and be_ok:
    print(">>> The §8 2026-06-23 'still 3-of-7 / build_evidence omits / X1 unclosed'")
    print(">>> claim is STALE. Both cross-process gaps are CLOSED in live source.")
sys.exit(0)
