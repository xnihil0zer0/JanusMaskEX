import copy
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from harness.planner.plan_validator import validate_plan

logger = logging.getLogger("janusmask.planner.auto_amend")

ALLOW_LIST = {
    "increase_test_count",
    "add_edge_case",
    "add_non_goal",
    "tighten_token_budget",
    "add_dependency"
}

@dataclass
class AmendmentResult:
    amended_plan: Dict[str, Any]
    applied: List[str]
    skipped: List[Dict[str, Any]]
    rolled_back: bool
    reason: Optional[str] = None


def _apply_patch(task: Dict[str, Any], patch: Dict[str, Any]) -> None:
    op = patch.get("op")
    val = patch.get("value")

    if op == "increase_test_count":
        if "test_spec" not in task:
            task["test_spec"] = {}
        current = task["test_spec"].get("minimum_test_count", 0)
        try:
            task["test_spec"]["minimum_test_count"] = current + int(val)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid value for increase_test_count: {val}")

    elif op == "add_edge_case":
        if "spec" not in task:
            task["spec"] = {}
        if "edge_cases" not in task["spec"]:
            task["spec"]["edge_cases"] = []
        task["spec"]["edge_cases"].append(str(val))

    elif op == "add_non_goal":
        if "spec" not in task:
            task["spec"] = {}
        if "non_goals" not in task["spec"]:
            task["spec"]["non_goals"] = []
        task["spec"]["non_goals"].append(str(val))

    elif op == "tighten_token_budget":
        if "token_budget_ratio" not in task:
            task["token_budget_ratio"] = {}
        if isinstance(val, dict):
            task["token_budget_ratio"].update(val)
        else:
            raise ValueError(f"Invalid value for tighten_token_budget: {val}")

    elif op == "add_dependency":
        if "dependencies" not in task:
            task["dependencies"] = []
        task["dependencies"].append(str(val))

    else:
        raise ValueError(f"Unsupported op: {op}")


def auto_amend(
    merged_plan: Dict[str, Any],
    critique_path: Path,
    config: Dict[str, Any],
    state_dir: Path
) -> AmendmentResult:
    
    planner_cfg = config.get("planner", {})
    if not planner_cfg.get("auto_amend_enabled", False):
        report = {"applied": [], "skipped": [], "rolled_back": False, "reason": None}
        report_path = state_dir / "planning" / "amendment_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        return AmendmentResult(merged_plan, [], [], False, None)

    if not critique_path.exists():
        report = {"applied": [], "skipped": [], "rolled_back": False, "reason": "no_critique"}
        report_path = state_dir / "planning" / "amendment_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        return AmendmentResult(merged_plan, [], [], False, "no_critique")

    try:
        with open(critique_path, "r", encoding="utf-8") as f:
            critique = json.load(f)
    except Exception as e:
        logger.error(f"Failed to read critique.json: {e}")
        return AmendmentResult(merged_plan, [], [], False, "malformed_critique")

    findings = critique.get("findings", [])
    if not isinstance(findings, list):
        findings = []

    # Sort deterministic
    try:
        findings.sort(key=lambda x: str(x.get("finding_id", "")))
    except Exception:
        pass

    original_violations = len(validate_plan(merged_plan))

    amended_plan = copy.deepcopy(merged_plan)
    
    tasks_by_id = {
        t.get("task_id"): t 
        for t in amended_plan.get("tasks", []) 
        if isinstance(t, dict) and t.get("task_id")
    }

    applied = []
    skipped = []

    for finding in findings:
        if not isinstance(finding, dict):
            continue
            
        finding_id = finding.get("finding_id")
        task_id = finding.get("task_id")
        patch = finding.get("suggested_patch")

        if not finding_id:
            continue

        if not patch:
            skipped.append({"finding_id": finding_id, "reason": "no_patch"})
            continue
            
        if not isinstance(patch, dict):
            skipped.append({"finding_id": finding_id, "reason": "malformed_patch"})
            continue

        op = patch.get("op")
        if op not in ALLOW_LIST:
            skipped.append({"finding_id": finding_id, "reason": "unsupported_op"})
            continue

        task = tasks_by_id.get(task_id)
        if not task:
            skipped.append({"finding_id": finding_id, "reason": "task_not_found"})
            continue

        try:
            _apply_patch(task, patch)
            applied.append(finding_id)
        except Exception as e:
            skipped.append({"finding_id": finding_id, "reason": "malformed_patch", "details": str(e)})

    rolled_back = False
    reason = None
    
    if applied:
        new_violations = len(validate_plan(amended_plan))
        if new_violations > original_violations:
            rolled_back = True
            reason = "would_regress_validator"
            amended_plan = merged_plan

    report = {
        "applied": applied,
        "skipped": skipped,
        "rolled_back": rolled_back,
    }
    if reason:
        report["reason"] = reason

    report_path = state_dir / "planning" / "amendment_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return AmendmentResult(
        amended_plan=amended_plan,
        applied=applied if not rolled_back else [],
        skipped=skipped,
        rolled_back=rolled_back,
        reason=reason
    )
