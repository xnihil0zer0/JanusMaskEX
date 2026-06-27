#!/usr/bin/env python3
"""S4: Did the agy_pool invariant functions exist AT baseline e5c0f9fb?
And are effective_pool_size / assert_pool_invariant actually CALLED anywhere in
the live harness (i.e. is the invariant runtime-enforced, refuting the README
'comment-only -- NOT runtime-enforced' claim)?"""
import subprocess, pathlib, re
root = pathlib.Path("/home/xnihil0zer0/JanusMaskJR")

base = subprocess.check_output(["git", "show", "e5c0f9fb:harness/agy_pool.py"], cwd=root, text=True)
for sym in ["effective_pool_size", "assert_pool_invariant", "PoolInvariantError"]:
    print(f"baseline e5c0f9fb defines {sym:<22}:", f"def {sym}" in base or f"class {sym}" in base)

print("\n=== callers of effective_pool_size / assert_pool_invariant across harness/ ===")
hits = subprocess.run(
    ["grep", "-rn", "-E", "effective_pool_size|assert_pool_invariant", "harness/", "scripts/", "services/"],
    cwd=root, text=True, capture_output=True)
out = [l for l in hits.stdout.splitlines() if "agy_pool.py" not in l]  # exclude the def site
print("\n".join(out) if out else "  (NO callers outside agy_pool.py itself — invariant is NOT runtime-enforced)")

print("\n=== where is the agy_pool *allocate_slot* fallback to shared HOME actually used? ===")
hits2 = subprocess.run(["grep", "-rn", "-E", "allocate_slot|agy_pool", "harness/"], cwd=root, text=True, capture_output=True)
for l in hits2.stdout.splitlines():
    if "agy_pool.py" not in l:
        print(l)
