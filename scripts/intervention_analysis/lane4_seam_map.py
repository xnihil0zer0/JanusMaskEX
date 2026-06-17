#!/usr/bin/env python3
"""Lane 4 (automation-surface) seam mapper.

Greps the JanusMask harness + planner + config for the pipeline seams where an
automated intervention policy could be injected, and emits a JSON map of
seam -> [file:line, ...]. Pure read-only; writes only to stdout (or --out).

Run:
    PYTHONPATH=. python scripts/intervention_analysis/lane4_seam_map.py [--out map.json]

The patterns below are the canonical anchors a future auto-intervention handler
would attach to. Each key is a seam; the value is the regex used to locate it.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# seam name -> (regex, [search roots relative to repo])
SEAMS: dict[str, tuple[str, list[str]]] = {
    # --- daemon control-loop intervention points (operator files/flags) ---
    "pause_flag": (r"control. / .autowork. / .pause.|_pause_flag_path", ["harness"]),
    "full_stop": (r"_full_stop_path|autowork. / .full_stop", ["harness"]),
    "auto_promote_allowlist": (r"auto_promote\.allowlist|_auto_promote_allowlist", ["harness"]),
    "auto_promote_disabled": (r"auto_promote\.disabled|_auto_promote_disabled", ["harness"]),
    "retry_blocked_budget": (r"_retry_blocked_tasks|max_attempts", ["harness"]),
    "inactivity_watchdog": (r"_check_inactivity_watchdog|inactivity_escalated", ["harness"]),
    "dispatch_circuit_breaker": (r"_dispatch_timestamps|quarantine", ["harness"]),
    # --- approval / decision-file seams ---
    "decision_file": (r"control. / .decisions|await_decision|_apply_approval_granted", ["harness"]),
    "auto_approve_sensitive": (r"_auto_approve_sensitive_eligible|auto_approve_sensitive", ["harness"]),
    "require_approval": (r"require_approval_for|require_approval", ["harness"]),
    # --- planner normalize-pass pipeline (PRIMARY injection seam) ---
    "normalize_plan_pipeline": (r"def normalize_plan|^    normalized = _|^    tasks = _", ["harness/planner"]),
    "normalize_passes": (r"^def _(strip|split|dedupe|drop|enforce|correct|canonicalize|sanitize|force|inject)_", ["harness/planner"]),
    "plan_validate_reject": (r"PlanViolation|def validate_plan", ["harness/planner"]),
    # --- staging / spawn seams ---
    "stage_task": (r"def stage_task|stage_task\(", ["harness"]),
    "spawn_worker": (r"_spawn_worker|orchestrator_worker|spawn_agent", ["harness"]),
    # --- self-heal harvest / eligibility seams ---
    "selfheal_harvest": (r"_harvest_selfheal_briefs|_synthesize_selfheal_plan", ["harness"]),
    "selfheal_eligibility": (r"_selfheal_auto_promote_enabled|selfheal_auto_promote", ["harness"]),
    # --- accept / wire-up gate seams ---
    "wire_up_gate": (r"_run_wire_up_gate|_wire_up_gate_enabled|orphan_unwired|def check_wired", ["harness"]),
    "auto_commit_accept": (r"_auto_commit_accepted|commit_accepted_output", ["harness"]),
    "archive_spent_briefs": (r"_reap_spent_briefs_safe|archive_spent_briefs", ["harness"]),
    # --- interceptors / hooks seams ---
    "interceptor_registry": (r"class InterceptorRegistry|registry\.register|def pre_tool_use", ["harness"]),
    "pre_tool_hook": (r"def main\(|legacy_dispatch|hook_event_name", ["harness/hooks", "harness/hook_pre_tool.py"]),
    # --- NGv2 boundary references in harness (should be ~empty: no runtime import) ---
    "ngv2_runtime_refs": (r"\bngv2\.|NobleGreedv2|NGV2_SESSION|JANUSMASK_WORKING_DIR", ["harness"]),
}


def grep(pattern: str, roots: list[str]) -> list[str]:
    hits: list[str] = []
    targets = []
    for r in roots:
        p = os.path.join(REPO, r)
        if os.path.exists(p):
            targets.append(p)
    if not targets:
        return hits
    cmd = ["grep", "-rnE", "--include=*.py", pattern] + targets
    try:
        out = subprocess.run(cmd, capture_output=True, text=True).stdout
    except Exception as exc:  # pragma: no cover
        return [f"<grep-error: {exc}>"]
    for line in out.splitlines():
        # normalize to relative file:line
        m = re.match(r"^(.*?):(\d+):", line)
        if m:
            rel = os.path.relpath(m.group(1), REPO)
            hits.append(f"{rel}:{m.group(2)}")
    return hits


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    result: dict[str, list[str]] = {}
    for seam, (pattern, roots) in SEAMS.items():
        result[seam] = grep(pattern, roots)
    payload = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(payload)
        print(f"wrote {args.out}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
