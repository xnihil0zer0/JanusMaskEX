#!/usr/bin/env python3
"""
AGENT-2 / s3 — Two STALE-PRECONDITION / DEVIATION checks:

(A) §1A + §7 default-operating-point: doc repeatedly states "default 4 concurrent
    pairs (parallel_cap: 4)" and "agy_pool size >= parallel_cap". Verify against
    live harness/config.yaml.

(B) §4/§7 STATUS columns: doc marks P1.2 ☐, P1.3 ☐, P2.1 children all ☐, and
    §8 says "Zero P0/P1/P2 contracts have landed besides P0.2(JM)". Verify the
    ACTUAL landed state via git log in BOTH repos.

(C) §4 P1.2 'semantic_verdict(...,sig="")→confirmed (RED today vacuous)' and the
    §8 G10 'sig=""→confirmed vacuity remains' claim — check live detonation.py.
"""
import re
import subprocess

JM = "/home/xnihil0zer0/JanusMaskJR"
NGV2 = "/home/xnihil0zer0/NobleGreedv2"

print("=" * 72)
print("s3 (A): default operating point — parallel_cap / agy_pool vs live config")
print("=" * 72)
cfg = open(f"{JM}/harness/config.yaml").read()
for key in ("parallel_cap:", "claude_parallel_cap:", "agy_pool:"):
    for line in cfg.splitlines():
        if line.strip().startswith(key):
            print(f"  live: {line.strip()}")
m = re.search(r"agy_pool:\s*\n(?:.*\n)*?\s*enabled:\s*(\w+)\s*\n\s*size:\s*(\d+)", cfg)
if m:
    print(f"  agy_pool.enabled={m.group(1)}  size={m.group(2)}")
print("  DOC says: parallel_cap: 4 (§1A, §7 'default 4 concurrent pairs')")
print("  DOC §1A prereq: agy_pool OFF by default (must be set). LIVE shows enabled:true.")

print("\n" + "=" * 72)
print("s3 (B): contract STATUS drift — what actually landed (git, both repos)")
print("=" * 72)

def grep_commits(repo, pat):
    out = subprocess.run(["git", "-C", repo, "log", "--oneline", "--all", "--grep", pat],
                         capture_output=True, text=True).stdout.strip()
    return out

checks = [
    ("P1.2 detonation_authenticity_provenance (doc=☐)", NGV2,
     ["p12-classify-poc-authenticity-provenance", "p12-detonation-verdict-provenance-impl"]),
    ("P1.3 wire_loopback_per_cwe_channels (doc=☐)", NGV2,
     ["wire-loopback-per-cwe-channels-impl", "impl-loopback-listener"]),
    ("P2.1-c0 scaffold (doc: epic ☐, MEMORY says c0 landed)", NGV2,
     ["p21-c0-fsm-evidence-scaffold", "p21-c0-fsm-scaffold-oracle"]),
    ("P2.1-c3 fsm_jail_build (doc=☐)", NGV2,
     ["p21-c3-fsm-jail-build"]),
]
for label, repo, pats in checks:
    print(f"\n  {label}:")
    for p in pats:
        c = grep_commits(repo, p)
        print(f"    grep '{p}': {c if c else '(none)'}")

print("\n" + "=" * 72)
print("s3 (C): semantic_verdict empty-sig — is the §4-P1.2 / §8-G10 'sig=\"\"→confirmed")
print("        vacuous-confirm RED' claim still true in live detonation.py?")
print("=" * 72)
det = open(f"{NGV2}/ngv2/detonation.py").read()
# find the empty-sig guard
guard = re.search(r"if not expected_fs_signature[^\n]*:\s*\n\s*return\s+([^\n]+)", det)
print("  empty-sig guard in semantic_verdict:")
sv = det[det.index("def semantic_verdict("):det.index("def semantic_verdict(")+900]
for ln in sv.splitlines()[:18]:
    print("    ", ln)
print(f"\n  guard present (rejects empty/whitespace sig): {bool(guard)}")
if guard:
    print(f"  empty-sig returns: {guard.group(1).strip()}")
