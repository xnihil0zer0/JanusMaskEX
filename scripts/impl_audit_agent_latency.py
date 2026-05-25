"""Audit agent wait time, dispatch latency, and idle-time inefficiency.

Parses the implementation ledger (state/impl_progress.jsonl) plus orchestrator
log polling tail to quantify wasted wall-clock time vs. productive activity.

Usage:
    python scripts/impl_audit_agent_latency.py

Outputs:
    - JSON report at state/output/impl_audit_agent_latency.json
    - Human summary on stdout
"""
from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER = REPO_ROOT / "state" / "impl_progress.jsonl"
ORCH_LOG = REPO_ROOT / "logs" / "orchestrator.log"
HARNESS_LOG = REPO_ROOT / "logs" / "harness.log"
OUTPUT_JSON = REPO_ROOT / "state" / "output" / "impl_audit_agent_latency.json"

# Productive events: things that actually move work forward.
PRODUCTIVE_EVENTS = {
    "task_claim",
    "task_start",
    "start",
    "write",
    "auto_commit",
    "phase_gate_pass",
    "adv_pass",
    "test_pass",
    "task_terminal",
    "blocker_resolved",
    "resolution",
}
# Overhead/retry/rejection signals.
OVERHEAD_EVENTS = {
    "agent_status",          # poll / status update, lots in epoch era
    "phase_transition",      # bookkeeping
    "adv_fail",
    "test_fail",
    "blocked",
    "blocker",
    "blocker_discovered",
    "scope_exception",
    "scope_revoke",
    "close_as_noop",
    "observation",
    "stop_allow",
    "adversarial_complete",
    "session_end",
}

IDLE_GAP_THRESHOLD = 300.0   # 5 minutes
SHORT_GAP_THRESHOLD = 30.0   # below this is treated as continuous activity


def parse_ts(value: Any) -> float | None:
    """Normalize ISO-or-epoch timestamps to epoch seconds (UTC)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip().rstrip("Z")
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            return None
    return None


def load_ledger(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            rec["_ts"] = parse_ts(rec.get("ts"))
            if rec["_ts"] is None:
                continue
            events.append(rec)
    events.sort(key=lambda r: r["_ts"])
    return events


def load_commit_map() -> list[tuple[float, str, str]]:
    """Return [(epoch, sha, subject), ...] sorted ascending."""
    try:
        out = subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "log", "--format=%H %ct %s"],
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    rows: list[tuple[float, str, str]] = []
    for line in out.splitlines():
        parts = line.split(" ", 2)
        if len(parts) < 3:
            continue
        sha, ts, subject = parts
        try:
            rows.append((float(ts), sha, subject))
        except ValueError:
            continue
    rows.sort(key=lambda r: r[0])
    return rows


def commit_at(commits: list[tuple[float, str, str]], ts: float) -> dict[str, Any] | None:
    """Last commit with epoch <= ts."""
    lo, hi = 0, len(commits) - 1
    best = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if commits[mid][0] <= ts:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    if best < 0:
        return None
    epoch, sha, subj = commits[best]
    return {"sha": sha[:12], "epoch": epoch, "subject": subj}


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def analyze_tasks(events: list[dict[str, Any]]) -> dict[str, Any]:
    per_task: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "events": [],
        "claims": 0,
        "terminals": 0,
        "phase_transitions": 0,
        "rejections": 0,
        "productive": 0,
        "overhead": 0,
        "agents_seen": set(),
        "first_ts": None,
        "last_ts": None,
        "phases_visited": [],
    })

    for rec in events:
        tid = rec.get("task_id") or ""
        if not tid:
            continue
        t = per_task[tid]
        t["events"].append(rec)
        ts = rec["_ts"]
        if t["first_ts"] is None or ts < t["first_ts"]:
            t["first_ts"] = ts
        if t["last_ts"] is None or ts > t["last_ts"]:
            t["last_ts"] = ts
        ev = rec.get("event") or ""
        if ev == "task_claim":
            t["claims"] += 1
        elif ev == "task_terminal":
            t["terminals"] += 1
        elif ev == "phase_transition":
            t["phase_transitions"] += 1
            phase = rec.get("phase") or rec.get("phase_transition", {}).get("to")
            if phase:
                t["phases_visited"].append(phase)
            if phase == "rejected":
                t["rejections"] += 1
        if ev in PRODUCTIVE_EVENTS:
            t["productive"] += 1
        elif ev in OVERHEAD_EVENTS:
            t["overhead"] += 1
        ag = rec.get("agent")
        if ag:
            t["agents_seen"].add(ag)

    rows = []
    for tid, t in per_task.items():
        duration = (t["last_ts"] - t["first_ts"]) if (t["first_ts"] and t["last_ts"]) else 0.0
        total = t["productive"] + t["overhead"]
        prod_ratio = t["productive"] / total if total else 0.0
        rows.append({
            "task_id": tid,
            "claims": t["claims"],
            "terminals": t["terminals"],
            "phase_transitions": t["phase_transitions"],
            "rejections": t["rejections"],
            "productive_events": t["productive"],
            "overhead_events": t["overhead"],
            "productive_ratio": round(prod_ratio, 3),
            "duration_sec": round(duration, 2),
            "first_ts": t["first_ts"],
            "last_ts": t["last_ts"],
            "agents": sorted(t["agents_seen"]),
            "phases_visited": t["phases_visited"],
            "retry": t["claims"] > 1,
        })
    rows.sort(key=lambda r: r["duration_sec"], reverse=True)
    return {"per_task": rows, "task_count": len(rows)}


def analyze_gaps(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Inter-event gaps across the whole ledger."""
    gaps: list[float] = []
    idle_windows: list[dict[str, Any]] = []
    prev = None
    for rec in events:
        ts = rec["_ts"]
        if prev is not None:
            gap = ts - prev["_ts"]
            gaps.append(gap)
            if gap >= IDLE_GAP_THRESHOLD:
                idle_windows.append({
                    "start_ts": prev["_ts"],
                    "end_ts": ts,
                    "gap_sec": round(gap, 2),
                    "before_event": prev.get("event"),
                    "before_task": prev.get("task_id"),
                    "after_event": rec.get("event"),
                    "after_task": rec.get("task_id"),
                })
        prev = rec
    idle_windows.sort(key=lambda r: r["gap_sec"], reverse=True)
    total_wall = events[-1]["_ts"] - events[0]["_ts"] if len(events) > 1 else 0.0
    total_idle = sum(w["gap_sec"] for w in idle_windows)
    return {
        "ledger_span_sec": round(total_wall, 2),
        "total_idle_sec": round(total_idle, 2),
        "idle_fraction": round(total_idle / total_wall, 4) if total_wall else 0.0,
        "idle_window_count": len(idle_windows),
        "longest_idle_windows": idle_windows[:10],
        "gap_stats": {
            "count": len(gaps),
            "median_sec": round(statistics.median(gaps), 3) if gaps else 0.0,
            "p95_sec": round(percentile(gaps, 0.95), 3) if gaps else 0.0,
            "p99_sec": round(percentile(gaps, 0.99), 3) if gaps else 0.0,
            "max_sec": round(max(gaps), 3) if gaps else 0.0,
        },
    }


def analyze_validation_streaks(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Longest contiguous streaks of overhead events without a productive one."""
    streaks: list[dict[str, Any]] = []
    cur_len = 0
    cur_start = None
    cur_end = None
    cur_task = None
    cur_events: list[str] = []
    for rec in events:
        ev = rec.get("event") or ""
        if ev in OVERHEAD_EVENTS:
            cur_len += 1
            if cur_start is None:
                cur_start = rec["_ts"]
                cur_task = rec.get("task_id")
            cur_end = rec["_ts"]
            cur_events.append(ev)
        else:
            if cur_len >= 5:
                streaks.append({
                    "length": cur_len,
                    "duration_sec": round((cur_end or 0) - (cur_start or 0), 2),
                    "task_id": cur_task,
                    "start_ts": cur_start,
                    "end_ts": cur_end,
                    "event_counts": dict(Counter(cur_events)),
                })
            cur_len = 0
            cur_start = None
            cur_end = None
            cur_task = None
            cur_events = []
    if cur_len >= 5:
        streaks.append({
            "length": cur_len,
            "duration_sec": round((cur_end or 0) - (cur_start or 0), 2),
            "task_id": cur_task,
            "start_ts": cur_start,
            "end_ts": cur_end,
            "event_counts": dict(Counter(cur_events)),
        })
    streaks.sort(key=lambda s: s["length"], reverse=True)
    return {"count": len(streaks), "top": streaks[:10]}


def analyze_dispatch_latency(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Latency from task_claim to first agent_status/auto_commit/task_terminal."""
    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in events:
        tid = rec.get("task_id") or ""
        if tid:
            by_task[tid].append(rec)

    dispatch_latencies: list[float] = []      # claim -> first agent_status
    completion_latencies: list[float] = []    # claim -> task_terminal
    samples: list[dict[str, Any]] = []
    for tid, recs in by_task.items():
        recs.sort(key=lambda r: r["_ts"])
        last_claim_ts: float | None = None
        last_claim_terminal: float | None = None
        first_agent_after_claim: float | None = None
        for rec in recs:
            ev = rec.get("event") or ""
            if ev == "task_claim":
                if last_claim_ts is not None and last_claim_terminal is not None and first_agent_after_claim is not None:
                    dispatch_latencies.append(first_agent_after_claim - last_claim_ts)
                    completion_latencies.append(last_claim_terminal - last_claim_ts)
                    samples.append({
                        "task_id": tid,
                        "claim_ts": last_claim_ts,
                        "dispatch_latency_sec": round(first_agent_after_claim - last_claim_ts, 2),
                        "completion_latency_sec": round(last_claim_terminal - last_claim_ts, 2),
                    })
                last_claim_ts = rec["_ts"]
                last_claim_terminal = None
                first_agent_after_claim = None
            elif ev == "agent_status" and last_claim_ts is not None and first_agent_after_claim is None:
                first_agent_after_claim = rec["_ts"]
            elif ev == "task_terminal" and last_claim_ts is not None:
                last_claim_terminal = rec["_ts"]
        if last_claim_ts is not None and last_claim_terminal is not None:
            if first_agent_after_claim is not None:
                dispatch_latencies.append(first_agent_after_claim - last_claim_ts)
            completion_latencies.append(last_claim_terminal - last_claim_ts)
            samples.append({
                "task_id": tid,
                "claim_ts": last_claim_ts,
                "dispatch_latency_sec": round((first_agent_after_claim - last_claim_ts), 2) if first_agent_after_claim else None,
                "completion_latency_sec": round(last_claim_terminal - last_claim_ts, 2),
            })

    def _stats(values: list[float]) -> dict[str, float]:
        if not values:
            return {"count": 0, "median": 0.0, "p95": 0.0, "max": 0.0}
        return {
            "count": len(values),
            "median": round(statistics.median(values), 3),
            "p95": round(percentile(values, 0.95), 3),
            "max": round(max(values), 3),
        }

    return {
        "dispatch_latency_sec": _stats(dispatch_latencies),
        "completion_latency_sec": _stats(completion_latencies),
        "samples": sorted(samples, key=lambda s: (s.get("completion_latency_sec") or 0), reverse=True)[:15],
    }


def analyze_polling(log_path: Path, label: str) -> dict[str, Any]:
    """Walk an orchestrator log counting `sleeping` debug lines and infer wall-clock spent polling."""
    if not log_path.exists():
        return {"label": label, "exists": False}
    sleeping_pattern = re.compile(r"sleeping (\d+)s")
    no_tasks_pattern = re.compile(r"No tasks available, sleeping")
    pause_pattern = re.compile(r"control pause flag set; sleeping")
    sleep_total = 0
    no_tasks = 0
    pause = 0
    first_ts: str | None = None
    last_ts: str | None = None
    bursts: list[dict[str, Any]] = []
    cur_burst_start: str | None = None
    cur_burst_count = 0
    cur_burst_last: str | None = None
    with log_path.open() as fh:
        for line in fh:
            m = sleeping_pattern.search(line)
            if not m:
                continue
            secs = int(m.group(1))
            sleep_total += secs
            stamp = line[:19]
            if first_ts is None:
                first_ts = stamp
            last_ts = stamp
            if no_tasks_pattern.search(line):
                no_tasks += 1
            if pause_pattern.search(line):
                pause += 1
            if cur_burst_start is None:
                cur_burst_start = stamp
                cur_burst_count = 1
            else:
                cur_burst_count += 1
            cur_burst_last = stamp
    if cur_burst_start is not None:
        bursts.append({"start": cur_burst_start, "end": cur_burst_last, "polls": cur_burst_count})
    return {
        "label": label,
        "exists": True,
        "first_sleep_log_ts": first_ts,
        "last_sleep_log_ts": last_ts,
        "total_sleep_lines": no_tasks + pause,
        "no_tasks_polls": no_tasks,
        "pause_polls": pause,
        "approx_sleep_seconds": sleep_total,
        "approx_sleep_hours": round(sleep_total / 3600.0, 2),
    }


def annotate_with_commits(rows: list[dict[str, Any]], commits: list[tuple[float, str, str]]) -> None:
    for row in rows:
        ts = row.get("first_ts") or row.get("start_ts") or row.get("claim_ts")
        if ts is None:
            continue
        c = commit_at(commits, float(ts))
        if c:
            row["build_state_commit"] = c


def main() -> int:
    if not LEDGER.exists():
        print(f"ledger not found: {LEDGER}", file=sys.stderr)
        return 2
    events = load_ledger(LEDGER)
    commits = load_commit_map()

    task_data = analyze_tasks(events)
    gap_data = analyze_gaps(events)
    streak_data = analyze_validation_streaks(events)
    dispatch_data = analyze_dispatch_latency(events)

    # Top-10 wasted-time tasks: long duration with low productive ratio OR retries.
    waste_candidates = [
        r for r in task_data["per_task"]
        if r["duration_sec"] >= 60 and (r["productive_ratio"] < 0.5 or r["retry"] or r["rejections"] > 0)
    ]
    waste_candidates.sort(
        key=lambda r: r["duration_sec"] * (1.0 - r["productive_ratio"]) + r["rejections"] * 300,
        reverse=True,
    )
    top_wasted = waste_candidates[:10]
    annotate_with_commits(top_wasted, commits)
    annotate_with_commits(gap_data["longest_idle_windows"], commits)
    annotate_with_commits(streak_data["top"], commits)
    annotate_with_commits(dispatch_data["samples"], commits)

    polling_orch = analyze_polling(ORCH_LOG, "logs/orchestrator.log")
    polling_harness = analyze_polling(HARNESS_LOG, "logs/harness.log")

    # System-wide rollups.
    total_productive = sum(r["productive_events"] for r in task_data["per_task"])
    total_overhead = sum(r["overhead_events"] for r in task_data["per_task"])
    total_events = total_productive + total_overhead
    productive_fraction = total_productive / total_events if total_events else 0.0

    # Approximate "productive wall-clock": for each task, sum of intra-task gaps < SHORT_GAP_THRESHOLD.
    productive_wall = 0.0
    for tid_row in task_data["per_task"]:
        recs = sorted(
            [r for r in events if (r.get("task_id") or "") == tid_row["task_id"]],
            key=lambda r: r["_ts"],
        )
        for a, b in zip(recs, recs[1:]):
            d = b["_ts"] - a["_ts"]
            if d <= SHORT_GAP_THRESHOLD:
                productive_wall += d

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ledger_path": str(LEDGER),
        "ledger_events": len(events),
        "unique_tasks": task_data["task_count"],
        "productive_event_fraction": round(productive_fraction, 3),
        "approx_productive_wall_sec": round(productive_wall, 2),
        "ledger_span_sec": gap_data["ledger_span_sec"],
        "approx_productive_fraction_wall": round(productive_wall / gap_data["ledger_span_sec"], 4) if gap_data["ledger_span_sec"] else 0.0,
        "polling_orchestrator": polling_orch,
        "polling_harness": polling_harness,
        "dispatch_latency": dispatch_data,
        "idle_gaps": gap_data,
        "overhead_streaks": streak_data,
        "top_wasted_tasks": top_wasted,
        "tasks_with_retries": [r for r in task_data["per_task"] if r["retry"]],
        "tasks_with_rejections": [r for r in task_data["per_task"] if r["rejections"] > 0],
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(summary, indent=2, default=str))

    # Human summary -------------------------------------------------------
    out = []
    out.append("=== JanusMask Agent Latency Audit ===")
    out.append(f"Ledger: {LEDGER}")
    out.append(f"Events: {len(events)}    Unique tasks: {task_data['task_count']}")
    out.append(
        f"Ledger span: {gap_data['ledger_span_sec']:.0f}s "
        f"({gap_data['ledger_span_sec'] / 3600:.1f}h)"
    )
    out.append(
        f"Productive wall-clock estimate: {productive_wall:.0f}s "
        f"({productive_wall / 3600:.2f}h, "
        f"{summary['approx_productive_fraction_wall'] * 100:.2f}% of span)"
    )
    out.append(f"Productive-event fraction: {productive_fraction * 100:.1f}%")
    out.append("")
    out.append("--- Idle gaps (>5min) ---")
    out.append(
        f"Total idle: {gap_data['total_idle_sec']:.0f}s "
        f"({gap_data['total_idle_sec'] / 3600:.2f}h, "
        f"{gap_data['idle_fraction'] * 100:.2f}% of span)"
    )
    out.append(
        f"Inter-event gap p50={gap_data['gap_stats']['median_sec']:.2f}s "
        f"p95={gap_data['gap_stats']['p95_sec']:.2f}s "
        f"max={gap_data['gap_stats']['max_sec']:.2f}s"
    )
    out.append("Top 5 idle windows:")
    for w in gap_data["longest_idle_windows"][:5]:
        c = w.get("build_state_commit", {}).get("sha", "?")
        out.append(
            f"  {w['gap_sec']:.0f}s  {w['before_event']}({w['before_task'] or '-'})"
            f" -> {w['after_event']}({w['after_task'] or '-'})  @ commit {c}"
        )
    out.append("")
    out.append("--- Dispatch latency (task_claim -> first agent_status) ---")
    dl = dispatch_data["dispatch_latency_sec"]
    cl = dispatch_data["completion_latency_sec"]
    out.append(f"Dispatch  n={dl['count']}  p50={dl['median']:.2f}s  p95={dl['p95']:.2f}s  max={dl['max']:.2f}s")
    out.append(f"Complete  n={cl['count']}  p50={cl['median']:.2f}s  p95={cl['p95']:.2f}s  max={cl['max']:.2f}s")
    out.append("")
    out.append("--- Orchestrator polling overhead ---")
    for p in (polling_orch, polling_harness):
        if not p.get("exists"):
            out.append(f"  {p['label']}: missing")
            continue
        out.append(
            f"  {p['label']}: {p['total_sleep_lines']} poll-sleeps "
            f"(no_tasks={p['no_tasks_polls']}, pause={p['pause_polls']}); "
            f"~{p['approx_sleep_hours']}h cumulative sleep"
        )
    out.append("")
    out.append("--- Tasks reclaimed (= retried) ---")
    for r in summary["tasks_with_retries"]:
        c = r.get("build_state_commit", {}).get("sha", "?")
        out.append(f"  {r['task_id']}: claims={r['claims']} rejections={r['rejections']} dur={r['duration_sec']:.0f}s")
    out.append("")
    out.append("--- Top 10 wasted-time tasks ---")
    for r in top_wasted:
        c = r.get("build_state_commit", {}).get("sha", "?")
        out.append(
            f"  {r['task_id']}: dur={r['duration_sec']:.0f}s "
            f"prod_ratio={r['productive_ratio']:.2f} "
            f"claims={r['claims']} rej={r['rejections']} @ {c}"
        )
    out.append("")
    out.append("--- Longest validation-without-progress streaks ---")
    for s in streak_data["top"][:5]:
        c = s.get("build_state_commit", {}).get("sha", "?")
        out.append(
            f"  len={s['length']} dur={s['duration_sec']:.0f}s task={s['task_id'] or '-'} "
            f"events={s['event_counts']} @ {c}"
        )
    out.append("")
    out.append(f"Full JSON: {OUTPUT_JSON}")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
