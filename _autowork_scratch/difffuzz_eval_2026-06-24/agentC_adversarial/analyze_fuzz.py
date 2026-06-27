#!/usr/bin/env python3
"""
Adversarial analysis of differential-fuzzing false-positive risk on retyped
EXTERNAL-build impl tasks (data_model after ac505d7 flip 2026-06-22).

READ-ONLY. Streams state/impl_progress.jsonl line by line.
Re-run: python3 analyze_fuzz.py [path-to-jsonl]
"""
import json, sys, datetime as dt
from collections import defaultdict, Counter, OrderedDict

LEDGER = sys.argv[1] if len(sys.argv) > 1 else "/home/xnihil0zer0/JanusMaskJR/state/impl_progress.jsonl"

# 2026-06-22 = day data_model flipped bypass_fuzzer True->False (commit ac505d7)
FLIP_EPOCH = dt.datetime(2026, 6, 22, 0, 0, 0, tzinfo=dt.timezone.utc).timestamp()

FUZZ_OUTCOMES = {"fuzz_error_r1", "stateful_fuzz_divergence"}

def to_epoch(ts):
    """Handle epoch-float or ISO-8601 'Z' string. Returns float or None."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        s = ts.strip()
        try:
            return float(s)
        except ValueError:
            pass
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            return dt.datetime.fromisoformat(s).timestamp()
        except Exception:
            return None
    return None

def iso(ep):
    if ep is None:
        return "?"
    return dt.datetime.fromtimestamp(ep, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

total = 0
bad = 0
# per-task event streams (ordered by epoch)
task_events = defaultdict(list)  # task_id -> list of (epoch, dict)
fuzz_fail_events = []            # raw fuzz-failure events
fuzz_coverage_events = []
accepted_tasks = set()           # task_ids that ever reached phase=accepted
auto_commit_tasks = set()        # task_ids that ever got auto_commit event (landed)

with open(LEDGER) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        total += 1
        try:
            o = json.loads(line)
        except Exception:
            bad += 1
            continue
        ep = to_epoch(o.get("ts"))
        tid = o.get("task_id")
        ev = o.get("event")
        oc = o.get("outcome")
        if tid is not None:
            task_events[tid].append((ep if ep is not None else 0.0, o))
        if oc in FUZZ_OUTCOMES:
            fuzz_fail_events.append((ep, o))
        if ev == "fuzz_coverage":
            fuzz_coverage_events.append((ep, o))
        if o.get("phase") == "accepted":
            accepted_tasks.add(tid)
        if ev == "auto_commit":
            auto_commit_tasks.add(tid)

print("=" * 78)
print("SCHEMA / TOTALS")
print("=" * 78)
print(f"total_lines        : {total}")
print(f"malformed_skipped  : {bad}")
print(f"distinct_task_ids  : {len(task_events)}")
print(f"tasks_ever_accepted: {len(accepted_tasks)}")
print(f"tasks_auto_commit  : {len(auto_commit_tasks)}")

# "landed" = ever reached accepted OR got an auto_commit
def landed(tid):
    return tid in accepted_tasks or tid in auto_commit_tasks

print()
print("=" * 78)
print("(a) FUZZ-FAILURE EVENTS  (outcome in fuzz_error_r1 / stateful_fuzz_divergence)")
print("=" * 78)
print(f"total fuzz-failure terminal events: {len(fuzz_fail_events)}")
oc_counter = Counter(o.get("outcome") for _, o in fuzz_fail_events)
for k, v in oc_counter.most_common():
    print(f"   {k}: {v}")

# distinct tasks with a fuzz failure
fuzz_fail_tasks = OrderedDict()
for ep, o in fuzz_fail_events:
    tid = o.get("task_id")
    fuzz_fail_tasks.setdefault(tid, []).append((ep, o))
print(f"\ndistinct task_ids hitting a fuzz failure: {len(fuzz_fail_tasks)}")
for tid, evs in fuzz_fail_tasks.items():
    eps = [e for e, _ in evs if e]
    first = iso(min(eps)) if eps else "?"
    last = iso(max(eps)) if eps else "?"
    ocs = Counter(o.get("outcome") for _, o in evs)
    landed_flag = "LANDED" if landed(tid) else "NOT-LANDED"
    post_flip = "POST-FLIP" if (eps and max(eps) >= FLIP_EPOCH) else "pre-flip"
    print(f"   - {tid}")
    print(f"        fails={dict(ocs)} first={first} last={last} {post_flip} {landed_flag}")

print()
print("=" * 78)
print("(c) TRAJECTORY: wire_loopback / P1.3 / fuzz_error_r1 case")
print("=" * 78)
# match any task whose id hints at wire_loopback
targets = [t for t in task_events if "loopback" in t.lower() or "wire_loopback" in t.lower()]
print(f"matching task_ids: {targets}")
for tid in targets:
    print(f"\n--- TRAJECTORY for {tid} (landed={landed(tid)}) ---")
    evs = sorted(task_events[tid], key=lambda x: x[0])
    for ep, o in evs:
        ev = o.get("event")
        oc = o.get("outcome", "")
        ph = o.get("phase", "")
        det = o.get("detail", "")
        if isinstance(det, dict):
            det = json.dumps(det)
        det = str(det)[:120]
        extra = f" outcome={oc}" if oc else ""
        print(f"   {iso(ep)}  phase={ph:<12} event={ev:<22}{extra}  {det}")

print()
print("=" * 78)
print("(d) SELF-HEAL: fuzz-failed tasks that ultimately LANDED")
print("=" * 78)
healed = []
not_healed = []
for tid in fuzz_fail_tasks:
    if landed(tid):
        healed.append(tid)
    else:
        not_healed.append(tid)
print(f"fuzz-failed & LANDED (self-healed)   : {len(healed)}")
for t in healed:
    print(f"   + {t}")
print(f"fuzz-failed & NEVER LANDED (parked)  : {len(not_healed)}")
for t in not_healed:
    # show its terminal-ish history
    evs = sorted(task_events[t], key=lambda x: x[0])
    last_evs = [o.get("event") for _, o in evs][-4:]
    eps = [e for e, _ in evs if e]
    print(f"   - {t}  last_events={last_evs} last_ts={iso(max(eps)) if eps else '?'}")

print()
print("=" * 78)
print("(d2) POST-FLIP (>=2026-06-22) fuzz-failed tasks: landed vs parked")
print("=" * 78)
pf_fail = [tid for tid, evs in fuzz_fail_tasks.items()
           if any((e and e >= FLIP_EPOCH) for e, _ in evs)]
pf_healed = [t for t in pf_fail if landed(t)]
pf_parked = [t for t in pf_fail if not landed(t)]
print(f"post-flip distinct fuzz-failed tasks : {len(pf_fail)}")
print(f"   of those LANDED                   : {len(pf_healed)}  {pf_healed}")
print(f"   of those PARKED (not landed)      : {len(pf_parked)}  {pf_parked}")

print()
print("=" * 78)
print("(e) FUZZ COVERAGE / ACCEPT TREND (latest fuzz_coverage snapshots)")
print("=" * 78)
fuzz_coverage_events.sort(key=lambda x: (x[0] or 0))
for ep, o in fuzz_coverage_events[-6:]:
    d = o.get("detail", {})
    print(f"   {iso(ep)} {o.get('task_id'):<40} accepted={d.get('accepted_total')} "
          f"fuzzed={d.get('fuzzed')} fp_rate={d.get('fp_rate')} "
          f"win_fuzzed={d.get('window_fuzzed')}/{d.get('window_accepted')}")

# retyped-external heuristic: external staging seen in stderr/stdout, or ngv2/P1.x slugs
print()
print("=" * 78)
print("(b/d) EXTERNAL-BUILD heuristic: tasks whose events reference external_staging / NobleGreedv2")
print("=" * 78)
external_tasks = set()
with open(LEDGER) as f:
    for line in f:
        if "external_staging" in line or "NobleGreedv2" in line:
            try:
                o = json.loads(line)
                external_tasks.add(o.get("task_id"))
            except Exception:
                pass
print(f"distinct task_ids referencing external_staging/NobleGreedv2: {len(external_tasks)}")
ext_fuzz_fail = [t for t in fuzz_fail_tasks if t in external_tasks]
print(f"   of those that hit a fuzz failure: {len(ext_fuzz_fail)} -> {ext_fuzz_fail}")
for t in ext_fuzz_fail:
    print(f"        {t}: landed={landed(t)}")
