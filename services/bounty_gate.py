#!/usr/bin/env python3
"""bounty_gate.py — Check expected bounty payout for a repo+CWE and return GO/SKIP."""
from __future__ import annotations

import json
import sys
from pathlib import Path

BOUNTY_FILE = Path(__file__).resolve().parent.parent / "data" / "huntr_repo_bounties.json"

ZERO_PAYOUT_OVERRIDES = {
    "prefecthq/prefect": {"CWE-502", "CWE-94"},
    "invoke-ai/invokeai": {"medium", "low"},
    "fastai/fastai": {"high", "critical"},
}

def load_bounties():
    if not BOUNTY_FILE.exists():
        return {"repos": {}, "formats": {}, "format_tiers": {}, "tiers": {}, "not_eligible_confirmed": []}
    try:
        with open(BOUNTY_FILE) as f:
            return json.load(f)
    except Exception:
        return {"repos": {}, "formats": {}, "format_tiers": {}, "tiers": {}, "not_eligible_confirmed": []}

def normalize_repo(repo: str) -> str:
    return repo.lower().strip()

def get_severity_payout(repo_data: dict, severity: str) -> int | None:
    observed = repo_data.get("observed_payouts", {})
    return observed.get(severity.lower())

def check_zero_override(repo_key: str, cwe: str, severity: str) -> bool:
    overrides = ZERO_PAYOUT_OVERRIDES.get(repo_key, set())
    if cwe.upper() in overrides:
        return True
    if severity.lower() in overrides:
        return True
    return False

def gate(owner_repo: str, cwe: str, severity: str = "HIGH") -> dict:
    data = load_bounties()
    repo_key = normalize_repo(owner_repo)

    if owner_repo.upper().startswith("FORMAT:"):
        fmt_name = owner_repo.split(":", 1)[1].strip().lower()
        formats = data.get("formats", {})
        fmt_data = formats.get(fmt_name)
        if fmt_data is None:
            return {
                "decision": "UNKNOWN",
                "expected_payout": None,
                "tier": None,
                "reasoning": f"Format '{fmt_name}' not found."
            }
        tier_name = fmt_data.get("tier", "MFF_A")
        format_tiers = data.get("format_tiers", {})
        tier_data = format_tiers.get(tier_name, {})
        payout = tier_data.get(severity.lower(), fmt_data.get("bounty"))
        return {
            "decision": "GO",
            "expected_payout": payout,
            "tier": tier_name,
            "reasoning": f"MFF track: {fmt_name} {severity} = ${payout}"
        }

    not_eligible = [r.lower() for r in data.get("not_eligible_confirmed", [])]
    if repo_key in not_eligible:
        return {
            "decision": "SKIP",
            "expected_payout": 0,
            "tier": None,
            "reasoning": f"{owner_repo} is confirmed NOT eligible."
        }

    repos = data.get("repos", {})
    repo_data = None
    for key, val in repos.items():
        if key.lower() == repo_key:
            repo_data = val
            repo_key = key
            break

    if repo_data is None:
        return {
            "decision": "UNKNOWN",
            "expected_payout": None,
            "tier": None,
            "reasoning": f"{owner_repo} not found in bounties. Check manually."
        }

    if not repo_data.get("eligible", False):
        return {
            "decision": "SKIP",
            "expected_payout": 0,
            "tier": repo_data.get("tier"),
            "reasoning": f"{owner_repo} marked not eligible."
        }

    if check_zero_override(normalize_repo(owner_repo), cwe, severity):
        return {
            "decision": "SKIP",
            "expected_payout": 0,
            "tier": repo_data.get("tier"),
            "reasoning": f"{owner_repo} + {cwe}/{severity} pays $0."
        }

    payout = get_severity_payout(repo_data, severity)
    if payout is not None:
        if payout == 0:
            return {
                "decision": "SKIP",
                "expected_payout": 0,
                "tier": repo_data.get("tier"),
                "reasoning": f"{owner_repo} {severity} payout = $0"
            }
        return {
            "decision": "GO",
            "expected_payout": payout,
            "tier": repo_data.get("tier"),
            "reasoning": f"{owner_repo} {severity} payout = ${payout}"
        }

    tier_name = repo_data.get("tier")
    tiers = data.get("tiers", {})
    tier_data = tiers.get(tier_name, {})
    tier_payout = tier_data.get(severity.lower())

    if tier_payout is not None:
        return {
            "decision": "GO",
            "expected_payout": tier_payout,
            "tier": tier_name,
            "reasoning": f"Using tier {tier_name} default = ${tier_payout}"
        }

    max_paid = repo_data.get("max_paid", 0)
    if max_paid > 0:
        return {
            "decision": "GO",
            "expected_payout": max_paid,
            "tier": tier_name,
            "reasoning": f"Custom tier, using max observed = ${max_paid}"
        }

    return {
        "decision": "UNKNOWN",
        "expected_payout": None,
        "tier": tier_name,
        "reasoning": f"No payout data for {owner_repo} at {severity}."
    }

def main():
    if len(sys.argv) < 3:
        print("Usage: bounty_gate.py <repo> <cwe> [severity]")
        sys.exit(1)
    owner_repo = sys.argv[1]
    cwe = sys.argv[2]
    severity = sys.argv[3] if len(sys.argv) > 3 else "HIGH"

    result = gate(owner_repo, cwe, severity)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["decision"] == "GO" else (1 if result["decision"] == "SKIP" else 2))

if __name__ == "__main__":
    main()
