#!/usr/bin/env python3
"""Probe: does the JM static floor FP-storm on EXTERNAL NGv2 (hardcoded JM roots)?"""
import sys
from pathlib import Path
JM = Path("/home/xnihil0zer0/JanusMaskJR"); sys.path.insert(0, str(JM))
from harness.wire_up import discover_modules, _resolved_graph, LIVE_ROOTS
from collections import deque

NG = Path("/home/xnihil0zer0/NobleGreedv2")
mods, _t, _s = discover_modules(NG); mods = list(mods); mset = set(mods)
g = _resolved_graph(NG, mods)
seeded = {r for r in LIVE_ROOTS if r in mset}
print(f"NGv2 source modules: {len(mods)}")
print(f"JM LIVE_ROOTS present in NGv2 module set: {sorted(seeded)}  (count={len(seeded)})")
reach = set(seeded); q = deque(seeded)
while q:
    c = q.popleft()
    for d in g.get(c, ()):
        if d not in reach: reach.add(d); q.append(d)
print(f"reachable-from-JM-roots in NGv2: {len(reach)} / {len(mods)}")
print(f"=> would_be_orphan storm: {len(mods)-len(reach)}/{len(mods)} = "
      f"{100.0*(len(mods)-len(reach))/max(1,len(mods)):.1f}% of NGv2 modules unreachable")
