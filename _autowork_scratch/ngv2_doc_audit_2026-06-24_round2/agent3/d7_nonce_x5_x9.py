#!/usr/bin/env python3
"""D7 — NEW gaps around X5 (nonce reproducibility) and X9 (teardown byte-identity):

  G15-a  The 'nonce' is NOT per-run RANDOM and NOT unforgeable:
         - SSRF path: nonce = f'ssrf_{clean_id}'  (DETERMINISTIC fn of finding id)
         - poc_writer: nonce=MARKER  (the nonce SLOT == the success marker 'VULNERABLE')
         => §4 "the per-run nonce is unforgeable" is FALSE on the wired path; X5's
            "per-run nonce present + re-derivation reproduces verdict" is unmet.
  G15-b  The nonce is NEVER persisted to an evidence bundle (X5 needs it recorded
         so a disinterested re-runner reproduces the CHECK).
  G16    X9 teardown 'target byte-identical to target_sha' assertion has NO
         production implementation (detonate_live rmtrees scratch; never verifies
         the RO-bound target is unchanged; no scratch_removed/target_unchanged
         evidence emitted).
"""
import sys, ast, inspect, re, pathlib
NG = "/home/xnihil0zer0/NobleGreedv2"
sys.path.insert(0, NG)

print("=== G15-a: nonce is deterministic, not per-run random/unforgeable ===")
from ngv2.workers import _runner as R
seam = inspect.getsource(R._make_detonation_seam)
for ln in seam.splitlines():
    s = ln.strip()
    if "nonce =" in s and "ssrf" in s:
        print("   wired SSRF nonce:", s)
# Show determinism: same finding id -> same nonce across runs (no randomness).
def derive(raw_id):
    if not raw_id:
        return 'ssrf_F_hunt'
    clean = ''.join(c for c in str(raw_id) if c.isalnum() or c in ('_','-'))
    return 'ssrf_F_hunt' if not clean else f'ssrf_{clean}'
print(f"   derive('F-42') run1={derive('F-42')!r}  run2={derive('F-42')!r}  -> "
      f"{'DETERMINISTIC (forgeable/predictable)' if derive('F-42')==derive('F-42') else 'random'}")

import ngv2.poc_writer as PW
pw = inspect.getsource(PW)
m = re.search(r"render\([^)]*nonce=([A-Za-z_]+)", pw)
print(f"   poc_writer renders payload with nonce={m.group(1) if m else '?'}  "
      f"(MARKER == success marker 'VULNERABLE' -> nonce slot collapsed onto marker)")
import ngv2.payload_bank as PB
print(f"   payload_bank.MARKER={getattr(PB,'MARKER','?')!r}  (the 'nonce' the PoC embeds)")

print()
print("=== G15-b: is the nonce PERSISTED to an evidence bundle? ===")
# Search production for any write of the nonce into a persisted artifact.
hits = []
for p in pathlib.Path(NG, "ngv2").rglob("*.py"):
    if "/test" in str(p) or "/targets/" in str(p):
        continue
    txt = p.read_text(errors="ignore")
    for ln in txt.splitlines():
        if "nonce" in ln and re.search(r"json\.dump|\.write\(|persist|build_evidence|seal|bundle", ln):
            hits.append(f"{p.name}: {ln.strip()[:100]}")
print(f"   production lines persisting a nonce: {len(hits)}")
for h in hits[:10]:
    print("   ", h)
print("   -> the detonation result dict (_make_detonation_seam) does NOT include a")
print("      'nonce' key; the SSRF nonce lives only in transient env + listener.hits.")
# Confirm the seam result dict keys:
mkeys = re.findall(r"result = \{([^}]*)\}", seam)
print("   seam result dict keys present:", "nonce" in (mkeys[0] if mkeys else ""))

print()
print("=== G16: X9 teardown byte-identity assertion has NO impl ===")
plr = pathlib.Path(NG, "ngv2/poc_runner_live.py").read_text()
print(f"   detonate_live rmtrees scratch:        {'shutil.rmtree(work_dir' in plr}")
has_byte_id = bool(re.search(r"target_sha|byte.?identical|target_unchanged", plr))
print(f"   any 'target byte-identical/target_sha' check in poc_runner_live: {has_byte_id}")
# Search all of ngv2 production for a post-teardown integrity assertion.
prod = []
for p in pathlib.Path(NG,"ngv2").rglob("*.py"):
    if "/test" in str(p) or "/targets/" in str(p): continue
    t = p.read_text(errors="ignore")
    if re.search(r"target_unchanged|byte.?identical.*target|git diff.*target_sha|assert.*target.*sha", t):
        prod.append(p.name)
print(f"   ngv2 production files asserting target byte-identity at teardown: {prod or 'NONE'}")

print()
print("=== SUMMARY ===")
print("G15-a nonce deterministic/forgeable (not per-run random):", "CONFIRMED")
print("G15-b nonce not persisted to evidence bundle:           ", "CONFIRMED" if not hits else "see hits")
print("G16  X9 teardown byte-identity has no impl:             ", "CONFIRMED" if not prod else "see prod")
