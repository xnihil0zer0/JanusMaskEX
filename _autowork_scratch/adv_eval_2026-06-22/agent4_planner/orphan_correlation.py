#!/usr/bin/env python3
"""Test the orphan-contention causation hypothesis from AVAILABLE telemetry only.
READ-ONLY. We cannot resurrect dead processes; we look for any signal that planner
slowness coincided with agy-orphan presence. Honest about unprovability.

Approach:
 1. Pair each recent plan_kickoff (with wall) to its time window
    [kickoff_ts - wall, kickoff_ts].
 2. Search impl_progress.jsonl for any orphan/reap/agy-pool events and worker
    spawns whose lifetime overlaps that window (= contention candidates).
 3. Report overlap counts per plan; compare slow (>800s) vs fast (<200s) plans.
"""
import json, collections
from pathlib import Path

ROOT = Path("/home/xnihil0zer0/JanusMaskJR")
IMPL = ROOT / "state/impl_progress.jsonl"

def iter_jsonl(p):
    with open(p, "rb") as f:
        for raw in f:
            try: yield json.loads(raw.decode("utf-8","replace"))
            except Exception: continue

rows = list(iter_jsonl(IMPL))

# plan windows
plans = []
for d in rows:
    if d.get("event")=="plan_kickoff":
        det = d.get("detail","")
        wall=None; label=det
        for t in det.split():
            if t.startswith("wall="):
                try: wall=float(t.split("=")[1])
                except: pass
            elif "=" not in t: label=t
        try: kts=float(d.get("ts"))
        except (TypeError, ValueError): kts=None
        if wall is not None and kts is not None:
            plans.append({"end":kts,"start":kts-wall,"wall":wall,"label":label})

# events that indicate concurrent worker / orphan activity
SPAWN_EVENTS = {"worker_start","launch","launch_sequential","active"}
EXIT_EVENTS  = {"worker_exit","task_terminal"}
ORPHAN_EVENTS= {"orphan_unwired","watchdog_kill","inactivity_watchdog_triggered","reap","drain_start"}

# tally per plan: how many spawn/exit/orphan events fell inside its window
print("="*78)
print("ORPHAN/CONTENTION CORRELATION — events overlapping each plan's wall window")
print("="*78)
print(f"{'label':<34}{'wall':>7}{'spawns':>8}{'exits':>7}{'orphan':>7}{'concur_pids':>12}")
slow_concur=[]; fast_concur=[]
for pl in sorted(plans, key=lambda x:x["end"])[-14:]:
    s,e = pl["start"], pl["end"]
    spawns=exits=orph=0
    pids_in_window=set()
    for d in rows:
        ts=d.get("ts")
        try: ts=float(ts)
        except (TypeError, ValueError): continue
        if ts<s or ts>e: continue
        ev=d.get("event")
        if ev in SPAWN_EVENTS: spawns+=1
        if ev in EXIT_EVENTS: exits+=1
        if ev in ORPHAN_EVENTS: orph+=1
        if d.get("pid"): pids_in_window.add(d["pid"])
    label = pl["label"][:32]
    print(f"{label:<34}{pl['wall']:>7.0f}{spawns:>8}{exits:>7}{orph:>7}{len(pids_in_window):>12}")
    if pl["wall"]>=800: slow_concur.append(len(pids_in_window))
    elif pl["wall"]<200: fast_concur.append(len(pids_in_window))

import statistics
def avg(x): return statistics.mean(x) if x else float('nan')
print("\n--- SLOW plans (>=800s) vs FAST plans (<200s): mean distinct pids active in window ---")
print(f"  slow plans n={len(slow_concur)}  mean concurrent pids={avg(slow_concur):.1f}")
print(f"  fast plans n={len(fast_concur)}  mean concurrent pids={avg(fast_concur):.1f}")

# Were there any actual orphan/reap events AT ALL near the slow plans?
print("\n--- All orphan/watchdog/reap events in the recent window (last 40) ---")
cnt=0
for d in rows[-20000:]:
    if d.get("event") in ORPHAN_EVENTS:
        cnt+=1
        if cnt<=40:
            print(f"  ts={d.get('ts')} {d.get('event')} {str(d.get('detail',''))[:80]}")
print(f"  total orphan/watchdog/reap events in last 20k rows: {cnt}")
