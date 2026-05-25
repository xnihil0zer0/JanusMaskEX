import json
import logging
import os
import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import subprocess
import time

from harness.orchestrator import spawn_agent, kill_agent
from harness.planner.blind_draft import _PerAgentConfig

logger = logging.getLogger("janusmask.planner.adversarial_review")

@dataclass
class CritiqueFinding:
    finding_id: str
    category: str
    severity: str
    message: str
    task_id: Optional[str] = None
    field_path: Optional[str] = None
    suggested_patch: Optional[Dict[str, Any]] = None

@dataclass
class CritiqueSchema:
    findings: List[CritiqueFinding] = field(default_factory=list)

    @classmethod
    def validate(cls, data: Dict[str, Any]) -> List[str]:
        violations = []
        if not isinstance(data, dict):
            return ["Root must be a dictionary"]

        findings = data.get("findings")
        if findings is None:
            return [] # Empty findings are allowed

        if not isinstance(findings, list):
            return ["'findings' must be a list"]

        categories = {"inflated_benchmark", "test_heavy_violation", "missing_edge_case", "bad_spec_author", "dependency_cycle", "other"}
        severities = {"info", "warn", "error"}

        for i, f in enumerate(findings):
            if not isinstance(f, dict):
                violations.append(f"findings[{i}] is not an object")
                continue

            if "finding_id" not in f:
                violations.append(f"findings[{i}] missing finding_id")
            if f.get("category") not in categories:
                violations.append(f"findings[{i}] invalid category: {f.get('category')}")
            if f.get("severity") not in severities:
                violations.append(f"findings[{i}] invalid severity: {f.get('severity')}")
            if "message" not in f:
                violations.append(f"findings[{i}] missing message")

            if "suggested_patch" in f and f["suggested_patch"] is not None:
                if not isinstance(f["suggested_patch"], dict):
                    violations.append(f"findings[{i}].suggested_patch must be a dict")

        return violations

def run_adversarial_review(merged_plan: Dict[str, Any], config: Dict[str, Any], state_dir: Path, reviewer: str = "claude") -> Path:
    """Spawns a single adversarial review agent and collects its critique."""
    planning_dir = state_dir / "planning"
    planning_dir.mkdir(parents=True, exist_ok=True)

    critique_out_path = planning_dir / "critique.json"

    def write_synthetic_failure(message: str) -> Path:
        synthetic = {
            "findings": [{
                "finding_id": "synthetic_failure",
                "category": "other",
                "severity": "error",
                "message": message
            }]
        }
        with open(critique_out_path, "w", encoding="utf-8") as f:
            json.dump(synthetic, f, indent=2)
        return critique_out_path

    reviewer_dir = planning_dir / "sessions" / reviewer
    reviewer_dir.mkdir(parents=True, exist_ok=True)

    # The reviewer piggybacks on the reconciliation submission verb, so the
    # PostToolUse hook needs a current_diff with the sentinel item the
    # reviewer references in its `responses` array.
    current_diff_path = reviewer_dir / "planning" / "current_diff.json"
    current_diff_path.parent.mkdir(parents=True, exist_ok=True)
    with open(current_diff_path, "w", encoding="utf-8") as f:
        json.dump({"items": [{"diff_item_id": "__critique__"}]}, f)

    derived_config = _PerAgentConfig(copy.deepcopy(config), reviewer_dir, reviewer_dir)
    derived_config.setdefault("agents", {}).setdefault(reviewer, {}).setdefault("env", {})
    # MODE=reconciliation so the PreToolUse hook permits writes to
    # `reconciliation.json` — the reviewer reuses the reconciliation outbox
    # name (the persisted file carries both `responses` and `findings`).
    derived_config["agents"][reviewer]["env"]["JANUSMASK_MODE"] = "reconciliation"

    prompt_file = Path(__file__).parent / "prompts" / "critique_prompt.md"
    prompt_text = prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else "Critique the plan."

    full_prompt = f"{prompt_text}\n\nHere is the merged plan to critique:\n{json.dumps(merged_plan, indent=2)}"

    old_env = os.environ.get("JANUSMASK_MODE")
    os.environ["JANUSMASK_MODE"] = "reconciliation"
    proc = None
    try:
        # Before spawning, verify command exists for early fallback (e.g. gemini not installed)
        cmd = derived_config.get("agents", {}).get(reviewer, {}).get("command")
        if isinstance(cmd, str) and not cmd.startswith("python"):
            # A simple check for binary path - if it's a simple name like "gemini" and not in PATH
            import shutil
            parts = cmd.split()
            if parts and not shutil.which(parts[0]):
                return write_synthetic_failure(f"Command not found: {parts[0]}")

        proc = spawn_agent(reviewer, full_prompt, derived_config)
        timeout = derived_config.get("planning_timeout_seconds", 1800)

        start_time = time.monotonic()
        canonical_path = reviewer_dir / "planning" / "sessions" / f"{reviewer}_reconciliation.json"

        # META-PLAN-OUTBOX-FALLBACK: post_tool may not fire under claude
        # `-p` mode --settings drop, so the reviewer's Write may only land
        # in the per-spawn outbox. Resolver tries proc._work_dir (set at
        # orchestrator.py:229) for THIS reviewer spawn — NOT a broader
        # glob, because R1 reconciliation outboxes share the
        # `reconciliation.json` filename and would falsely match.
        # _resolve_outbox_artifact is intentionally NOT used here.
        def _resolve_submission() -> Optional[Path]:
            if canonical_path.exists():
                return canonical_path
            work_dir = getattr(proc, "_work_dir", None)
            if work_dir is not None:
                direct = Path(work_dir) / "outbox" / "reconciliation.json"
                if direct.is_file():
                    return direct
            return None

        timed_out = False
        submitted_path: Optional[Path] = None
        while True:
            submitted_path = _resolve_submission()
            if submitted_path is not None:
                break
            if proc.poll() is not None:
                time.sleep(0.5)
                submitted_path = _resolve_submission()
                if submitted_path is None:
                    timed_out = True
                break
            if time.monotonic() - start_time > timeout:
                timed_out = True
                break
            time.sleep(1)

        if timed_out:
            return write_synthetic_failure("Reviewer agent timed out or crashed without submitting.")

        if submitted_path is None:
            return write_synthetic_failure("Reviewer agent submission could not be resolved.")
        if submitted_path != canonical_path:
            logger.info(
                "%s reviewer critique recovered from per-spawn outbox: %s",
                reviewer, submitted_path,
            )

        with open(submitted_path, "r", encoding="utf-8") as f:
            submission = json.load(f)

        violations = CritiqueSchema.validate(submission)
        if violations:
            logger.warning("Critique schema validation failed: %s", violations)
            return write_synthetic_failure(f"Schema validation failed: {violations}")

        with open(critique_out_path, "w", encoding="utf-8") as f:
            json.dump(submission, f, indent=2)

        return critique_out_path

    except Exception as e:
        logger.exception("Failed to run adversarial review")
        return write_synthetic_failure(f"Agent spawn or execution failed: {e}")
    finally:
        if proc and proc.poll() is None:
            kill_agent(proc, reviewer, reason='adversarial_review_cleanup')
        if old_env is None:
            del os.environ["JANUSMASK_MODE"]
        else:
            os.environ["JANUSMASK_MODE"] = old_env
