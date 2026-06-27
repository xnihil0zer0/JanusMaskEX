#!/usr/bin/env python
"""Compact oversight digest for the epic-contracts run. Prints per-slug state +
recent blocker/accept events for my 18 slugs only. Token-cheap."""
import json, glob, os, pathlib, sys

ROOT = pathlib.Path("/home/xnihil0zer0/JanusMaskJR")
SLUGS = [p.stem.replace("brief_hooks_", "") for p in ROOT.glob("brief_hooks_fix_*.md")]
TASK_IDS = set()
for p in ROOT.glob("brief_hooks_fix_*.md"):
    txt = p.read_text(errors="ignore")
    for line in txt.splitlines():
        if "required_task_ids" in line:
            import re
            TASK_IDS.update(re.findall(r"[\"']([a-z0-9-]+)[\"']", line))

# brief_status ground truth
try:
    from harness.brief_status import compute_brief_status
    state_dir = ROOT / "state"
    rows = {}
    for slug in sorted(SLUGS):
        try:
            st = compute_brief_status(ROOT, state_dir) if False else None
        except Exception:
            st = None
except Exception:
    pass

# Cheaper: scan ledger tail for my task_ids
EVENTS = ("plan_kickoff","planner_hallucination_discarded","planner_validation_rejected",
          "plan_timeout","extract","launch","launch_sequential","auto_commit","verification_failed",
          "task_blocked","retry_exhausted","dependency_failed","orphan_unwired",
          "inactivity_watchdog_triggered","empty_plan")
ledger = ROOT/"state"/"impl_progress.jsonl"
recent = []
accepted = set(); blocked = {}
# read only the tail (last ~4000 lines) for speed
import collections
with open(ledger, "rb") as f:
    try:
        f.seek(-2_000_000, os.SEEK_END)
    except OSError:
        f.seek(0)
    tail = f.read().decode("utf-8", "ignore").splitlines()
for line in tail:
    try:
        r = json.loads(line)
    except Exception:
        continue
    ev = r.get("event"); tid = r.get("task_id","")
    if ev not in EVENTS:
        continue
    is_mine = (tid in TASK_IDS) or any(tid.replace("-","_")==t.replace("-","_") for t in TASK_IDS) or (r.get("slug","").replace("-","_") in [s.replace("-","_") for s in SLUGS])
    if not is_mine:
        continue
    if ev == "auto_commit" and r.get("phase")=="accepted":
        accepted.add(tid)
    if ev in ("task_blocked","retry_exhausted","verification_failed","orphan_unwired","planner_hallucination_discarded","planner_validation_rejected","plan_timeout","dependency_failed","empty_plan"):
        blocked[tid or r.get("slug","?")] = ev + ":" + str(r.get("outcome") or r.get("detail",""))[:60]
    recent.append((r.get("ts"), ev, tid, str(r.get("outcome") or r.get("detail") or "")[:60]))

print(f"my slugs: {len(SLUGS)} briefs | my task_ids: {len(TASK_IDS)}")
print(f"ACCEPTED ({len(accepted)}): {sorted(accepted)}")
print(f"BLOCKED/ATTN ({len(blocked)}):")
for k,v in sorted(blocked.items()):
    print(f"   {k}: {v}")
print("--- last 12 of my events ---")
for ts,ev,tid,d in recent[-12:]:
    print(f"   {ev:32s} {tid:42s} {d}")

# queue snapshot
q = list((ROOT/"state"/"tasks").glob("*.json"))
proc = list((ROOT/"state"/"tasks").glob("*.processing"))
blk = list((ROOT/"state"/"tasks"/"blocked").glob("*.json"))
print(f"--- queue: {len(q)} queued, {len(proc)} processing, {len(blk)} blocked ---")
for p in proc: print(f"   PROCESSING {p.name}")
# unplanned briefs (no plan_hooks)
planned = {p.stem.replace("plan_hooks_","") for p in ROOT.glob("plan_hooks_*.json")} & set(SLUGS)
unplanned = [s for s in SLUGS if s not in planned]
print(f"--- planned: {len(planned)} of my plans exist; unplanned briefs: {len(unplanned)} ---")
