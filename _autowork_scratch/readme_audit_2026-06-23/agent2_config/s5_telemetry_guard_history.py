#!/usr/bin/env python3
"""S5: Did the agy_pool_invariant_violated telemetry guard exist at README
baseline e5c0f9fb? If it pre-dates the README, the 'NOT runtime-enforced'
caveat was ALREADY imprecise at write time (still a candidate correction, but
NOT 'drift since baseline'). If it post-dates, it's fresh drift."""
import subprocess, pathlib
root = pathlib.Path("/home/xnihil0zer0/JanusMaskJR")

base = subprocess.check_output(["git", "show", "e5c0f9fb:harness/autowork_daemon.py"], cwd=root, text=True)
print("baseline e5c0f9fb autowork_daemon.py mentions 'agy_pool_invariant_violated':",
      "agy_pool_invariant_violated" in base)
print("baseline e5c0f9fb autowork_daemon.py mentions '_agy_pool_assign'           :",
      "_agy_pool_assign" in base)

print("\n=== commit that INTRODUCED 'agy_pool_invariant_violated' ===")
log = subprocess.check_output(
    ["git", "log", "--oneline", "-S", "agy_pool_invariant_violated", "--", "harness/autowork_daemon.py"],
    cwd=root, text=True)
print(log or "  (not found)")

print("=== date of that commit relative to README baseline e5c0f9fb (2026-06-20) ===")
log2 = subprocess.check_output(
    ["git", "log", "-1", "--format=%h %ci %s", "-S", "agy_pool_invariant_violated", "--", "harness/autowork_daemon.py"],
    cwd=root, text=True)
print(log2)
base_date = subprocess.check_output(["git", "log", "-1", "--format=%ci", "e5c0f9fb"], cwd=root, text=True)
print("README baseline e5c0f9fb date:", base_date.strip())
