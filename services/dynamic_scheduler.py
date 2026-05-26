#!/usr/bin/env python3
"""Dynamic Scheduler — Adjusts cron chain frequency based on ROI."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
STATE_FILE = BASE / "orchestrator" / "state.json"
SCHEDULE_FILE = BASE / "data" / "schedule_config.json"

MIN_INTERVAL = 3
MAX_INTERVAL = 30
DEFAULT_INTERVAL = 5

HIGH_ROI_THRESHOLD = 5.0
LOW_ROI_THRESHOLD = 0.5
PAUSE_THRESHOLD = 0.1

CHAINS = {
    "bug_hunt": {
        "metric_key": "hunt_roi_per_hour",
        "default_interval": 5,
    },
    "mff_hunt": {
        "metric_key": "mff_roi_per_hour",
        "default_interval": 5,
    },
    "adversarial": {
        "metric_key": "adversarial_roi_per_hour",
        "default_interval": 10,
    },
}

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}

def load_schedule() -> dict:
    if SCHEDULE_FILE.exists():
        try:
            return json.loads(SCHEDULE_FILE.read_text())
        except Exception:
            pass
    return {"chains": {}, "updated_at": None}

def save_schedule(schedule: dict):
    schedule["updated_at"] = datetime.now(timezone.utc).isoformat()
    SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULE_FILE.write_text(json.dumps(schedule, indent=2))

def compute_chain_roi(state: dict) -> dict:
    em = state.get("evaluation_metrics", {})
    tt = state.get("time_tracking", {})

    op_hours = tt.get("operation_total_s", 3600) / 3600
    chain_roi = {}

    # Bug hunt
    submittable = em.get("submittable_findings", 0)
    hunt_value = submittable * 500 * 0.5
    hunt_hours = op_hours * 0.6
    chain_roi["bug_hunt"] = {
        "estimated_value": hunt_value,
        "hours": max(hunt_hours, 0.1),
        "roi_per_hour": hunt_value / max(hunt_hours, 0.1),
        "findings": submittable,
    }

    # MFF hunt
    mff_findings = 0
    active_dir = BASE / "operations" / "active"
    if active_dir.exists():
        mff_findings = sum(1 for f in active_dir.glob("task_9*_mff_*") if f.exists())
    mff_value = mff_findings * 2000 * 0.3
    mff_hours = op_hours * 0.3
    chain_roi["mff_hunt"] = {
        "estimated_value": mff_value,
        "hours": max(mff_hours, 0.1),
        "roi_per_hour": mff_value / max(mff_hours, 0.1),
        "findings": mff_findings,
    }

    # Adversarial
    adv = state.get("adversarial", {})
    adv_value = adv.get("rules_written", 0) * 100
    adv_hours = op_hours * 0.1
    chain_roi["adversarial"] = {
        "estimated_value": adv_value,
        "hours": max(adv_hours, 0.1),
        "roi_per_hour": adv_value / max(adv_hours, 0.1),
        "rules_written": adv.get("rules_written", 0),
    }

    return chain_roi

def recommend_schedule() -> dict:
    state = load_state()
    schedule = load_schedule()
    roi = compute_chain_roi(state)

    recommendations = {}
    for name, config in CHAINS.items():
        chain_roi = roi.get(name, {}).get("roi_per_hour", 0.0)
        current_interval = schedule.get("chains", {}).get(name, {}).get("interval", config["default_interval"])

        if chain_roi >= HIGH_ROI_THRESHOLD:
            new_interval = max(MIN_INTERVAL, int(current_interval * 0.5))
            status = "accelerate"
        elif chain_roi <= PAUSE_THRESHOLD:
            new_interval = current_interval
            status = "paused"
        elif chain_roi <= LOW_ROI_THRESHOLD:
            new_interval = min(MAX_INTERVAL, int(current_interval * 1.5))
            status = "decelerate"
        else:
            new_interval = current_interval
            status = "maintain"

        recommendations[name] = {
            "roi_per_hour": round(chain_roi, 2),
            "current_interval": current_interval,
            "recommended_interval": new_interval,
            "status": status,
        }

    return {
        "recommendations": recommendations,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

def apply_recommendations() -> dict:
    rec = recommend_schedule()
    schedule = load_schedule()
    
    for name, data in rec["recommendations"].items():
        if name not in schedule["chains"]:
            schedule["chains"][name] = {}
        schedule["chains"][name]["interval"] = data["recommended_interval"]
        schedule["chains"][name]["status"] = data["status"]
        schedule["chains"][name]["last_roi"] = data["roi_per_hour"]

    save_schedule(schedule)
    return schedule

def main():
    parser = argparse.ArgumentParser(description="Dynamic Scheduler")
    parser.add_argument("command", choices=["recommend", "report", "apply"])
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        rec = recommend_schedule()
        assert "recommendations" in rec
        print("SELF-TEST: PASS")
        sys.exit(0)

    if args.command == "recommend":
        rec = recommend_schedule()
        print(json.dumps(rec, indent=2))
    elif args.command == "apply":
        sched = apply_recommendations()
        print(json.dumps(sched, indent=2))
    elif args.command == "report":
        state = load_state()
        roi = compute_chain_roi(state)
        print("=== ROI REPORT ===")
        for name, data in roi.items():
            print(f"{name}: ROI=${data['roi_per_hour']:.2f}/hr (value=${data['estimated_value']:.2f}, hrs={data['hours']:.1f})")

if __name__ == "__main__":
    main()
