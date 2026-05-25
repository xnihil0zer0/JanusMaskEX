#!/usr/bin/env python3
"""Extract one task from a plan_hooks_*.json multi-task plan into a single
state/tasks/queued/<task_id>.json file for orchestrator dispatch.

Usage:
    scripts/impl_plan_to_queue.py <plan.json> --task <task_id> [--state-dir state]

The orchestrator scans top-level ``state/tasks/*.json`` (see
``harness/orchestrator.py:533``); ``state/tasks/queued/`` is a legacy
directory that ``scripts/impl_dispatch_once.sh:38-42`` auto-promotes
to the canonical path on dispatch. This tool writes to the legacy
queued/ subdir by default to match the canonical staging convention;
pass ``--canonical`` to write directly to ``state/tasks/<task_id>.json``.

Refuses to overwrite an existing output file. Performs no validation
beyond schema_present + filename_match — ``harness/planner/plan_validator``
already validated the source plan.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan", type=Path, help="path to plan_hooks_*.json with tasks[]")
    ap.add_argument("--task", required=True, help="task_id to extract")
    ap.add_argument("--state-dir", type=Path, default=Path("state"))
    ap.add_argument("--canonical", action="store_true",
                    help="write to state/tasks/<task_id>.json (orchestrator scan path) "
                         "instead of state/tasks/queued/<task_id>.json (legacy)")
    parsed = ap.parse_args(argv)

    plan = json.loads(parsed.plan.read_text(encoding="utf-8"))
    tasks = plan.get("tasks") or []
    matches = [t for t in tasks if t.get("task_id") == parsed.task]
    if not matches:
        sys.stderr.write(f"task_id {parsed.task!r} not found in {parsed.plan} "
                         f"(have: {[t.get('task_id') for t in tasks]})\n")
        return 2
    if len(matches) > 1:
        sys.stderr.write(f"task_id {parsed.task!r} appears {len(matches)}x in {parsed.plan}\n")
        return 2
    task = matches[0]

    if parsed.canonical:
        out = parsed.state_dir / "tasks" / f"{parsed.task}.json"
    else:
        out = parsed.state_dir / "tasks" / "queued" / f"{parsed.task}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        sys.stderr.write(f"refuse: {out} already exists\n")
        return 2
    out.write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
    print(str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
