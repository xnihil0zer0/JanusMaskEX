#!/usr/bin/env python3
"""qualify_target.py — Unified Qualification Gate for NobleJanus targets."""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOUNTY_FILE = PROJECT_ROOT / "data" / "huntr_repo_bounties.json"
FP_PATTERNS_FILE = PROJECT_ROOT / "data" / "fp_patterns.json"
ACTIVE_DIR = PROJECT_ROOT / "operations" / "active"

CAPABILITY_DIRS = [
    PROJECT_ROOT / "services" / "tools",
    PROJECT_ROOT / "knowledge" / "taint_specs" / "library",
    PROJECT_ROOT / "services" / "adversarial",
]
CAPABILITY_FILES = [
    PROJECT_ROOT / "data" / "prompt_hints_log.jsonl",
    PROJECT_ROOT / "services" / "code_audit" / "grounding_config.json",
]

SATURATION_THRESHOLD = 50
FRESHNESS_THRESHOLD_DAYS = 7

def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}

def parse_target(target: str) -> tuple[str, str]:
    if target.upper().startswith("FORMAT:"):
        fmt_name = target.split(":", 1)[1].strip().lower()
        return ("format", fmt_name)
    return ("repo", target.strip())

def check_bounty(target: str, cwe: str, severity: str) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from bounty_gate import gate
    return gate(target, cwe, severity)

def check_saturation(target: str, target_type: str) -> dict:
    data = load_json(BOUNTY_FILE)
    if target_type == "format":
        formats = data.get("formats", {})
        fmt_data = formats.get(target.lower(), {})
        submissions = fmt_data.get("submissions", 0)
    else:
        repos = data.get("repos", {})
        repo_data = None
        for key, val in repos.items():
            if key.lower() == target.lower():
                repo_data = val
                break
        submissions = (repo_data or {}).get("submissions", (repo_data or {}).get("total_advisories", 0))

    status = "SKIP" if submissions >= SATURATION_THRESHOLD else "GO"
    return {
        "submissions": submissions,
        "threshold": SATURATION_THRESHOLD,
        "status": status,
    }

def _newest_capability_mtime() -> float | None:
    newest = None
    for d in CAPABILITY_DIRS:
        if not d.exists():
            continue
        for f in d.iterdir():
            if f.name.startswith(("__pycache__", ".")):
                continue
            try:
                mt = f.stat().st_mtime
                if newest is None or mt > newest:
                    newest = mt
            except Exception:
                pass
    for f in CAPABILITY_FILES:
        if f.exists():
            try:
                mt = f.stat().st_mtime
                if newest is None or mt > newest:
                    newest = mt
            except Exception:
                pass
    return newest

def check_freshness(target: str, target_type: str, purpose: str = "hunt") -> dict:
    if purpose == "submit":
        return {
            "last_audited": None,
            "days_ago": None,
            "threshold": FRESHNESS_THRESHOLD_DAYS,
            "status": "GO",
            "bypassed": "submit",
            "reasoning": "Freshness gate skipped: submitting already-confirmed findings",
        }

    if target_type == "format":
        search_term = target.lower()
    else:
        parts = target.split("/")
        search_term = parts[-1].lower() if parts else target.lower()

    if not ACTIVE_DIR.exists():
        return {
            "last_audited": None,
            "days_ago": None,
            "threshold": FRESHNESS_THRESHOLD_DAYS,
            "status": "GO",
        }

    latest_mtime = None
    latest_file = None

    for task_file in ACTIVE_DIR.glob("task_*"):
        if search_term in task_file.name.lower():
            try:
                mtime = task_file.stat().st_mtime
                if latest_mtime is None or mtime > latest_mtime:
                    latest_mtime = mtime
                    latest_file = task_file.name
            except Exception:
                pass

    if latest_mtime is None:
        return {
            "last_audited": None,
            "days_ago": None,
            "threshold": FRESHNESS_THRESHOLD_DAYS,
            "status": "GO",
        }

    last_dt = datetime.fromtimestamp(latest_mtime, tz=timezone.utc)
    now = datetime.now(tz=timezone.utc)
    days_ago = (now - last_dt).total_seconds() / 86400

    if days_ago < FRESHNESS_THRESHOLD_DAYS:
        if purpose == "retest":
            cap_mtime = _newest_capability_mtime()
            if cap_mtime is not None and cap_mtime > latest_mtime:
                cap_dt = datetime.fromtimestamp(cap_mtime, tz=timezone.utc)
                return {
                    "last_audited": last_dt.isoformat(),
                    "days_ago": round(days_ago, 1),
                    "threshold": FRESHNESS_THRESHOLD_DAYS,
                    "status": "GO",
                    "bypassed": "new_capabilities",
                    "file": latest_file,
                    "reasoning": f"Bypassed: new capability at {cap_dt.isoformat()}",
                }
        return {
            "last_audited": last_dt.isoformat(),
            "days_ago": round(days_ago, 1),
            "threshold": FRESHNESS_THRESHOLD_DAYS,
            "status": "SKIP",
            "file": latest_file,
        }

    return {
        "last_audited": last_dt.isoformat(),
        "days_ago": round(days_ago, 1),
        "threshold": FRESHNESS_THRESHOLD_DAYS,
        "status": "GO",
        "file": latest_file,
    }

def check_fp_risk(target: str, cwe: str, target_type: str) -> dict:
    fp_data = load_json(FP_PATTERNS_FILE)
    patterns = fp_data.get("patterns", [])
    matches = []
    for pat in patterns:
        pat_cwe = pat.get("cwe", "")
        if pat_cwe.upper() == cwe.upper():
            matches.append({
                "id": pat.get("id"),
                "reason": pat.get("reason"),
            })
    return {
        "matches": len(matches),
        "patterns": matches,
        "status": "GO",
    }

def qualify(target: str, cwe: str, severity: str = "HIGH", purpose: str = "hunt") -> dict:
    target_type, normalized = parse_target(target)
    bounty = check_bounty(target, cwe, severity)

    if bounty["decision"] == "SKIP":
        return {
            "decision": "SKIP",
            "target": target,
            "target_type": target_type,
            "purpose": purpose,
            "bounty": bounty,
            "reasoning": f"Bounty gate: {bounty.get('reasoning', 'skipped')}",
        }

    if bounty["decision"] == "UNKNOWN":
        return {
            "decision": "UNKNOWN",
            "target": target,
            "target_type": target_type,
            "purpose": purpose,
            "bounty": bounty,
            "reasoning": f"Bounty gate: {bounty.get('reasoning', 'unknown')}",
        }

    saturation = check_saturation(normalized, target_type)
    if saturation["status"] == "SKIP":
        return {
            "decision": "SKIP",
            "target": target,
            "target_type": target_type,
            "purpose": purpose,
            "bounty": bounty,
            "saturation": saturation,
            "reasoning": f"Saturation: {saturation['submissions']} submissions",
        }

    freshness = check_freshness(normalized, target_type, purpose=purpose)
    if freshness["status"] == "SKIP":
        return {
            "decision": "SKIP",
            "target": target,
            "target_type": target_type,
            "purpose": purpose,
            "bounty": bounty,
            "saturation": saturation,
            "freshness": freshness,
            "reasoning": f"Freshness: audited {freshness['days_ago']} days ago",
        }

    fp_risk = check_fp_risk(normalized, cwe, target_type)

    parts = [
        f"{saturation['submissions']} subs",
        f"Tier {bounty.get('tier')} ${bounty.get('expected_payout')}/{severity}",
    ]
    if freshness.get("days_ago") is not None:
        parts.append(f"last audit {freshness['days_ago']}d ago")
    else:
        parts.append("no prior audit")

    return {
        "decision": "GO",
        "target": target,
        "target_type": target_type,
        "purpose": purpose,
        "bounty": bounty,
        "saturation": saturation,
        "freshness": freshness,
        "fp_risk": fp_risk,
        "reasoning": ", ".join(parts),
    }

def main():
    if len(sys.argv) < 3:
        print("Usage: qualify_target.py <target> <cwe> [severity] [--purpose=hunt|submit|retest]")
        sys.exit(1)

    target = sys.argv[1]
    cwe = sys.argv[2]
    severity = "HIGH"
    purpose = "hunt"

    for arg in sys.argv[3:]:
        if arg.startswith("--purpose="):
            purpose = arg.split("=", 1)[1].strip().lower()
        else:
            severity = arg

    result = qualify(target, cwe, severity, purpose=purpose)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["decision"] == "GO" else (1 if result["decision"] == "SKIP" else 2))

if __name__ == "__main__":
    main()
