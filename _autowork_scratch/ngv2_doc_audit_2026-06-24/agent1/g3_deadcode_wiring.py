#!/usr/bin/env python3
"""G3 verification: the doc claims (§2 G3, §3 P1.3, §4 SSRF row, §8A 2026-06-21)
that auth_bootstrap, loopback_listener, and sink_instrument are DEAD CODE
(test-only importers, zero production importers) and that LoopbackListener
"must wire" / is "dead code".

Empirically inventory PRODUCTION (non-test, non-scratch) importers at HEAD.
"""
import subprocess, os

NGV2 = "/home/xnihil0zer0/NobleGreedv2"

def grep_importers(mod):
    # search whole NGv2 repo for import of the module name
    out = subprocess.run(
        ["grep", "-rln", "--include=*.py", mod, "."],
        cwd=NGV2, capture_output=True, text=True).stdout.strip().splitlines()
    return [l for l in out if l]

for mod, dead_claim in [("loopback_listener", "dead code -> must wire (P1.3/G3)"),
                        ("auth_bootstrap", "dead code (G3/P3.1)"),
                        ("sink_instrument", "dead code (G3/P2.1 REACHABILITY)")]:
    print(f"=== {mod}  (doc: {dead_claim}) ===")
    hits = grep_importers(mod)
    prod = [h for h in hits if "/test" not in h.lower() and "_autowork" not in h
            and not os.path.basename(h).startswith("test_")
            and os.path.basename(h) != f"{mod}.py"]
    test = [h for h in hits if h not in prod and os.path.basename(h) != f"{mod}.py"]
    self_def = [h for h in hits if os.path.basename(h) == f"{mod}.py"]
    print(f"  PRODUCTION importers (non-test, non-self): {prod}")
    print(f"  test-only importers: {test}")
    print(f"  self/defining file:  {self_def}")
    if prod:
        print(f"  VERDICT: doc 'dead code' claim is STALE/FALSE -> {mod} now has {len(prod)} production importer(s)")
    else:
        print(f"  VERDICT: doc 'dead code' claim STILL TRUE -> {mod} has 0 production importers")
    print()

# Prove LoopbackListener is actually INSTANTIATED on the live hunt path
print("=== LoopbackListener instantiation in workers/_runner.py ===")
r = subprocess.run(["grep", "-n", "LoopbackListener", "ngv2/workers/_runner.py"],
                   cwd=NGV2, capture_output=True, text=True)
print(r.stdout or "(none)")
print("=== loopback_listener reference in poc_runner_live.py ===")
r = subprocess.run(["grep", "-n", "loopback", "ngv2/poc_runner_live.py"],
                   cwd=NGV2, capture_output=True, text=True)
print(r.stdout or "(none)")
