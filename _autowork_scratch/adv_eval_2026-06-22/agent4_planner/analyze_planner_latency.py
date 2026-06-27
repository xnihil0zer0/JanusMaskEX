#!/usr/bin/env python3
"""Adversarial planner-latency analysis. READ-ONLY: mines existing telemetry only.
Produces (1) distribution of plan_kickoff wall times, (2) per-stage breakdown for
recent plans by diffing consecutive stage timestamps in planner_progress.jsonl.
"""
import json, sys, statistics
from pathlib import Path

ROOT = Path("/home/xnihil0zer0/JanusMaskJR")
IMPL = ROOT / "state/impl_progress.jsonl"
PLAN = ROOT / "state/planning/planner_progress.jsonl"

def iter_jsonl(p):
    with open(p, "rb") as f:
        for raw in f:
            try:
                yield json.loads(raw.decode("utf-8", "replace"))
            except Exception:
                continue

# ---------- 1. plan_kickoff wall distribution ----------
kickoffs = []  # (ts, label, wall)
timeouts = []
rejects = []
for d in iter_jsonl(IMPL):
    ev = d.get("event")
    if ev == "plan_kickoff":
        det = d.get("detail", "")
        wall = None
        label = det
        for tok in det.split():
            if tok.startswith("wall="):
                try: wall = float(tok.split("=",1)[1])
                except: pass
            else:
                if "=" not in tok:
                    label = tok
        kickoffs.append((d.get("ts"), label, wall))
    elif ev == "plan_timeout":
        timeouts.append((d.get("ts"), d.get("detail","")))
    elif ev == "planner_validation_rejected":
        rejects.append((d.get("ts"), d.get("detail","")))

walls = [w for _,_,w in kickoffs if w is not None]
print("="*72)
print("1. PLAN_KICKOFF WALL-TIME DISTRIBUTION (successful plans, from impl_progress.jsonl)")
print("="*72)
print(f"total plan_kickoff rows: {len(kickoffs)}   with wall= detail: {len(walls)}")
if walls:
    ws = sorted(walls)
    def pct(p):
        i = min(len(ws)-1, int(round(p/100*(len(ws)-1))))
        return ws[i]
    print(f"  count = {len(ws)}")
    print(f"  min   = {ws[0]:.1f}s")
    print(f"  p25   = {pct(25):.1f}s")
    print(f"  median= {statistics.median(ws):.1f}s")
    print(f"  mean  = {statistics.mean(ws):.1f}s")
    print(f"  p75   = {pct(75):.1f}s")
    print(f"  p90   = {pct(90):.1f}s")
    print(f"  max   = {ws[-1]:.1f}s")
    # histogram buckets
    import collections
    buckets = collections.Counter()
    for w in ws:
        if w < 60: buckets["<60s"]+=1
        elif w < 180: buckets["60-180s"]+=1
        elif w < 400: buckets["180-400s"]+=1
        elif w < 800: buckets["400-800s"]+=1
        elif w < 1500: buckets["800-1500s"]+=1
        else: buckets[">=1500s"]+=1
    print("  histogram:")
    for k in ["<60s","60-180s","180-400s","400-800s","800-1500s",">=1500s"]:
        if buckets[k]: print(f"    {k:>10}: {buckets[k]}")
print(f"\n  plan_timeout rows: {len(timeouts)}  (last 5):")
for ts,det in timeouts[-5:]:
    print(f"    ts={ts} {det}")
print(f"  planner_validation_rejected rows: {len(rejects)}  (last 3):")
for ts,det in rejects[-3:]:
    print(f"    ts={ts} {det}")

print("\n  --- last 12 plan_kickoff (chronological) ---")
for ts,label,wall in kickoffs[-12:]:
    print(f"    ts={ts}  wall={wall}  label={label}")

# ---------- 2. per-stage breakdown ----------
# planner_progress.jsonl is a single sequential stream (per planner process).
# A plan = the run from a load_brief through persist_plan. Use stage tracker_records.
STAGE_ORDER = ["load_brief","blind_drafts","diff","reconciliation",
               "attribution_stamp","adversarial_review","auto_amend_gate","persist_plan"]
recs = [d for d in iter_jsonl(PLAN) if d.get("kind")=="tracker_record" and "stage" in d and "ts" in d]
# segment into plans: a new plan starts at each persist_plan boundary (end), or
# we walk and group: from a load_brief to the next persist_plan inclusive.
plans = []
cur = []
for d in recs:
    st = d["stage"]
    if st == "load_brief" and cur:
        # new plan started before previous persisted -> close previous
        plans.append(cur); cur=[]
    cur.append((d["ts"], st))
    if st == "persist_plan":
        plans.append(cur); cur=[]
if cur: plans.append(cur)

print("\n"+"="*72)
print("2. PER-STAGE BREAKDOWN — last 8 plans (stage_end_ts diffs)")
print("="*72)
print("(delta = time from this stage's record to the NEXT stage's record)")
for plan in plans[-8:]:
    if len(plan) < 2: continue
    t0 = plan[0][0]; tN = plan[-1][0]
    total = tN - t0
    print(f"\n  plan span {total:7.1f}s  ({plan[0][1]} -> {plan[-1][1]}, {len(plan)} stages)  start_ts={t0:.0f}")
    for i in range(len(plan)-1):
        ts, st = plan[i]
        nxt_ts = plan[i+1][0]
        dt = nxt_ts - ts
        bar = "#"*min(50,int(dt/10))
        print(f"      {st:<20} {dt:8.1f}s  {bar}")
    print(f"      {plan[-1][1]:<20} {'(end)':>8}")

# aggregate per-stage share across recent complete plans
print("\n"+"="*72)
print("3. AGGREGATE STAGE SHARE across last 30 complete plans (load_brief..persist_plan)")
print("="*72)
import collections
agg = collections.defaultdict(list)
complete = [p for p in plans if p[0][1]=="load_brief" and p[-1][1]=="persist_plan" and len(p)>=4]
for plan in complete[-30:]:
    for i in range(len(plan)-1):
        st = plan[i][1]
        dt = plan[i+1][0]-plan[i][0]
        agg[st].append(dt)
total_all = sum(sum(v) for v in agg.values())
print(f"complete plans analyzed: {min(30,len(complete))} (of {len(complete)} total complete)")
print(f"{'stage':<20}{'n':>4}{'sum_s':>10}{'mean_s':>9}{'median_s':>10}{'share%':>8}")
for st in STAGE_ORDER:
    v = agg.get(st,[])
    if not v: continue
    share = 100*sum(v)/total_all if total_all else 0
    print(f"{st:<20}{len(v):>4}{sum(v):>10.1f}{statistics.mean(v):>9.1f}{statistics.median(v):>10.1f}{share:>8.1f}")
print(f"{'TOTAL':<20}{'':>4}{total_all:>10.1f}")
