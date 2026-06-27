#!/usr/bin/env python3
"""Prove (a) brief_status now adds a brief-sha freshness/staleness dimension that the
README §7 'purely from the ledger + tasks files' description omits, and (b) the CLI
label set is still exactly the 5 the README lists. Read-only."""
import sys, inspect, re, pathlib
sys.path.insert(0, '/home/xnihil0zer0/JanusMaskJR')

import harness.brief_status as bs

print("=== compute_brief_status source: does it hash the brief & gate on sha freshness? ===")
src = inspect.getsource(bs.compute_brief_status)
for needle in ('hashlib.sha256', 'source_brief_sha256', 'plan_stale', 'p.read_bytes()'):
    print(f"  {needle!r:30} present={needle in src}")

print()
print("=== the staleness branches (sha mismatch -> has_plan=False / accept not counted) ===")
for ln in src.splitlines():
    if any(k in ln for k in ('plan_stale = True', 'has_plan = False', 'accept_sha != stamped', 'current_sha = hashlib')):
        print("   " + ln.strip())

print()
print("=== _normalize_accept_ts exists (new accept-ts normalize helper)? ===")
print("  has _normalize_accept_ts referenced in module:", 'def _normalize_accept_ts' in pathlib.Path(bs.__file__).read_text())

print()
print("=== CLI label set in scripts/brief_status.py (must be exactly the 5 README lists) ===")
cli = pathlib.Path('/home/xnihil0zer0/JanusMaskJR/scripts/brief_status.py').read_text()
m = re.search(r"state_to_label\s*=\s*\{(.*?)\}", cli, re.S)
labels = sorted(set(re.findall(r"'([A-Z][A-Z-]+)'", m.group(1)))) if m else []
# add EPIC which is assigned separately
epic = bool(re.search(r"'EPIC'", cli))
allset = sorted(set(labels) | ({'EPIC'} if epic else set()))
print("  labels mapped:", allset)
readme_set = sorted(['NEEDS-PLAN','PENDING','EPIC','DONE','ORPHAN-PLAN'])
print("  README §7 claims:", readme_set)
print("  EXACT MATCH:", allset == readme_set)

print()
print("=== internal 7 states (README claims 'seven internal states') ===")
states = sorted(set(re.findall(r"state = '([a-z_]+)'", src)))
print("  states assigned in compute_brief_status:", states, "count=", len(states))
