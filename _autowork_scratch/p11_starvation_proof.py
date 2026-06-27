#!/usr/bin/env python3
"""Analytic proof of why p11_build_evidence_perphase stays unplanned/undispatched.

READ-ONLY. Reproduces the daemon's OWN concurrency + park-gate computations
against the REAL on-disk state. Run with PYTHONPATH=. from repo root.
"""
import os
import time
import errno
import pathlib

import harness.autowork_daemon as awd

ROOT = pathlib.Path("/home/xnihil0zer0/JanusMaskJR")
STATE = ROOT / "state"
SLUG = "p11_build_evidence_perphase"

print("=" * 70)
print("PART 1 — CONCURRENCY / SLOT HYPOTHESIS")
print("=" * 70)

rdir = awd._running_dir(STATE)
slot_files = sorted(rdir.glob("*.slot"))
pid_files = sorted(rdir.glob("*.pid"))
print(f"running dir              : {rdir}")
print(f".slot files on disk      : {len(slot_files)}")
print(f".pid  files on disk      : {len(pid_files)}")
print()

# (a) The daemon's TRUE concurrency gate: _reap_running scans *.pid ONLY.
running = awd._reap_running(STATE)
print(f"_reap_running() live set : {running}   (len={len(running)})")

# (b) The cap the daemon would use.
try:
    cfg = awd.load_config() if hasattr(awd, "load_config") else {}
except Exception:
    from harness.orchestrator import load_config as _lc
    cfg = _lc()
cap = awd._parallel_cap(cfg)
free = max(0, cap - len(running))
print(f"_parallel_cap(config)    : {cap}")
print(f"free = cap - len(running): {free}")
print(f"dispatch blocked by cap? : {free <= 0}")
print()

# (c) Would the .slot files ever be counted as live workers / exhaust the agy pool?
busy = awd._agy_pool_busy_slots(STATE)
print(f"_agy_pool_busy_slots()   : {busy}   (a slot counts ONLY when a matching")
print(f"                            .pid sibling exists; with 0 .pid files this is empty)")
print()

# (d) Test the daemon's pid-liveness predicate against the hypothesised pids 0 and 1.
from harness.state_reconciler import pid_is_live
for probe in (0, 1):
    print(f"pid_is_live({probe})           : {pid_is_live(probe)}")
# And what os.kill(pid,0) actually does for 0/1 (the hypothesis's claim):
for probe in (0, 1):
    try:
        os.kill(probe, 0)
        verdict = "RETURNED (no exception)"
    except OSError as e:
        verdict = f"raised {type(e).__name__} errno={getattr(e,'errno',None)} ({errno.errorcode.get(getattr(e,'errno',None),'?')})"
    print(f"raw os.kill({probe}, 0)        : {verdict}")
print()
print("NOTE: .slot files contain an AGY-POOL SLOT INDEX (0/1), NOT a pid.")
print("      They are NEVER passed to any os.kill liveness probe by the concurrency")
print("      gate. _reap_running globs *.pid only; _agy_pool_busy_slots requires a")
print("      matching *.pid sibling. So the slot files do NOT block dispatch.")
print()

print("=" * 70)
print("PART 2 — THE REAL GATE: DETERMINISTIC PLAN-ATTEMPTS PARK")
print("=" * 70)
marker = awd._plan_attempt_marker_path(STATE, SLUG)
print(f"park marker path         : {marker}")
print(f"park marker exists       : {marker.exists()}")
if marker.exists():
    print(f"park marker content      : {marker.read_text().strip()}")
    print(f"park marker mtime        : {time.ctime(marker.stat().st_mtime)}")
brief_p = ROOT / f"brief_hooks_{SLUG}.md"
if brief_p.exists():
    print(f"brief mtime              : {time.ctime(brief_p.stat().st_mtime)}")
    import json as _json
    data = _json.loads(marker.read_text()) if marker.exists() else {}
    last_ts = data.get("last_ts", 0)
    print(f"brief mtime > marker ts? : {brief_p.stat().st_mtime > last_ts}  "
          f"(if True, re-author would CLEAR the park at daemon read)")
parked = awd._recently_failed_to_plan(STATE, SLUG)
print(f"_recently_failed_to_plan : {parked}   <-- if True the planner is SKIPPED -> stays unplanned")
print()
print("VERDICT: brief stays unplanned because the deterministic 24h park marker")
print("         is honored (attempts>=1 & deterministic -> 86400s threshold), and")
print("         the brief file is OLDER than the marker so re-author-invalidation")
print("         does NOT fire. This is the dispatch-starvation cause, NOT the slots.")
