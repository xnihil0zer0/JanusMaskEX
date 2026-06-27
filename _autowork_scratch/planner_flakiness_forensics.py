#!/usr/bin/env python3
"""Forensic: when did the planner start getting flaky? Rate over time + provenance.

Reads state/impl_progress.jsonl. Planner-health events:
  plan_kickoff               -> planner produced a plan (SUCCESS)
  planner_validation_rejected-> planner subprocess failed (FAIL); detail carries reason=rc=N + wall
  plan_timeout               -> planner hit synthesis timeout (FAIL, hang)
  inactivity_watchdog_triggered -> daemon detected a stuck planner/worker
  timeout                    -> generic timeout (worker or plan)
"""
import json, time, re, collections, datetime as dt

LED = "state/impl_progress.jsonl"
NOW = time.time()
H = 3600

rows = []
for l in open(LED):
    l = l.strip()
    if not l:
        continue
    try:
        r = json.loads(l)
    except Exception:
        continue
    if isinstance(r.get("ts"), (int, float)):
        rows.append(r)

span_lo = min(r["ts"] for r in rows)
span_hi = max(r["ts"] for r in rows)
def hms(ts): return dt.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
print(f"LEDGER: {len(rows)} ts-rows  span {hms(span_lo)} .. {hms(span_hi)}  ({(span_hi-span_lo)/H:.1f}h)")
print(f"NOW = {hms(NOW)}\n")

PLANNER_FAIL = {"planner_validation_rejected", "plan_timeout"}
PLANNER_OK   = {"plan_kickoff"}
WATCH = {"inactivity_watchdog_triggered"}

# ---- 1. EVERY planner attempt (kickoff/rejected/timeout), chronological, last 72h ----
print("=== EVERY planner attempt event (last 72h), chronological ===")
print(f"{'when':<13} {'event':<28} {'rc/wall/detail':<55}")
win = NOW - 72*H
def parse_detail(d):
    if not d: return ""
    m_rc = re.search(r"reason=(rc=-?\d+)", d)
    m_wall = re.search(r"wall=([\d.]+)", d)
    slug = d.split()[0] if d.split() else ""
    bits = []
    if m_wall: bits.append(f"wall={float(m_wall.group(1)):.0f}s")
    if m_rc: bits.append(m_rc.group(1))
    return f"{slug[:22]:<22} {' '.join(bits)}"
for r in rows:
    if r["ts"] < win: continue
    ev = r.get("event")
    if ev in PLANNER_FAIL or ev in PLANNER_OK:
        print(f"{hms(r['ts']):<13} {ev:<28} {parse_detail(r.get('detail',''))[:55]}")

# ---- 2. Per-6h-bin rates over last 72h ----
print("\n=== per-6h-bin planner health (last 72h) ===")
print(f"{'bin start':<13} {'OK':>3} {'FAIL':>4} {'watchdog':>8}  success%")
bins = collections.defaultdict(lambda: collections.Counter())
for r in rows:
    if r["ts"] < NOW - 72*H: continue
    b = int((r["ts"]) // (6*H)) * (6*H)
    ev = r.get("event")
    if ev in PLANNER_OK: bins[b]["ok"] += 1
    elif ev in PLANNER_FAIL: bins[b]["fail"] += 1
    elif ev in WATCH: bins[b]["watch"] += 1
for b in sorted(bins):
    c = bins[b]
    tot = c["ok"] + c["fail"]
    pct = f"{100*c['ok']//tot}%" if tot else "  -"
    print(f"{hms(b):<13} {c['ok']:>3} {c['fail']:>4} {c['watch']:>8}  {pct:>6}")

# ---- 3. failure-mode breakdown (rc reasons) over all planner_validation_rejected ----
print("\n=== planner_validation_rejected failure modes (rc reason), all-time ===")
rc_c = collections.Counter()
walls = []
for r in rows:
    if r.get("event") != "planner_validation_rejected": continue
    d = r.get("detail","")
    m = re.search(r"reason=(rc=-?\d+)", d); rc_c[m.group(1) if m else "?"] += 1
    mw = re.search(r"wall=([\d.]+)", d)
    if mw: walls.append(float(mw.group(1)))
for rc, n in rc_c.most_common():
    print(f"  {rc:<10} {n}")
if walls:
    walls.sort()
    print(f"  wall secs: min={walls[0]:.0f} med={walls[len(walls)//2]:.0f} max={walls[-1]:.0f}  (n={len(walls)})")

# ---- 4. first vs recent: when did FAIL events first appear? ----
print("\n=== inflection: timeline of planner FAIL events (all-time) ===")
fails = [(r["ts"], r.get("event"), r.get("detail","")) for r in rows if r.get("event") in PLANNER_FAIL]
fails.sort()
if fails:
    print(f"  FIRST planner fail ever: {hms(fails[0][0])}  ({fails[0][1]})")
    print(f"  total planner fails: {len(fails)}")
    # bucket by day
    byday = collections.Counter(dt.datetime.fromtimestamp(t).strftime("%m-%d") for t,_,_ in fails)
    for day in sorted(byday): print(f"    {day}: {byday[day]} fails")
oks = [r["ts"] for r in rows if r.get("event") in PLANNER_OK]
oks.sort()
if oks:
    byday_ok = collections.Counter(dt.datetime.fromtimestamp(t).strftime("%m-%d") for t in oks)
    print("  plan_kickoff (success) by day:")
    for day in sorted(byday_ok): print(f"    {day}: {byday_ok[day]} ok")
