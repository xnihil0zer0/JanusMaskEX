import copy
from pathlib import Path
from typing import Any, Dict, List

from harness.planner.diff_model import PlanDiff, DiffKind
from harness.planner.reconciliation import ReconciliationResult


def _emit_attribution_lifecycle(task_id: str, kind, state_dir: Path | None = None) -> None:
    """Append an attribution row to state/planning/planner_progress.jsonl.

    META-D2c: replaces the old `print('DEBUG: task_id=...')` at line 57.
    Best-effort write -- swallows OSError per W113. Mirrors the
    cli._emit_planner_lifecycle convention (Path('state') fallback).
    """
    try:
        import time as _time
        from harness._journal import write_jsonl_row
        target = (state_dir or Path("state")) / "planning" / "planner_progress.jsonl"
        write_jsonl_row(target, {
            "ts": _time.time(),
            "kind": "attribution",
            "payload": {"task_id": task_id, "diff_kind": str(kind)},
        })
    except OSError:
        pass


class StampingError(Exception):
    """Raised when attribution stamping encounters an inconsistent state."""
    pass


def stamp_attribution(
    merged_tasks: List[Dict[str, Any]],
    plan_diff: PlanDiff,
    reconciliation_result: ReconciliationResult,
    bootstrap: bool
) -> List[Dict[str, Any]]:
    """
    Stamp attribution_metadata.proposed_by and spec_author on each merged task.
    """
    if not merged_tasks:
        return []

    stamped_tasks = []
    
    # Pre-compute task_id to diff_item mapping for faster lookup
    diff_map = {}
    for item in plan_diff.items:
        for t in (item.claude_task, item.gemini_task):
            if t and "task_id" in t:
                diff_map[t["task_id"]] = item

    # Also build a set of unresolved task ids to ensure we don't stamp them
    unresolved_ids = set()
    for item in reconciliation_result.unresolved_items:
        for t in (item.claude_task, item.gemini_task):
            if t and "task_id" in t:
                unresolved_ids.add(t["task_id"])

    for task in merged_tasks:
        task_id = task.get("task_id")
        if not task_id:
            # Should not happen in a valid plan, but just in case
            continue

        if "spec_author" in task and task["spec_author"] is not None:
            raise StampingError(f"Task {task_id} already has a non-null spec_author.")

        if task_id in unresolved_ids:
            raise StampingError(f"Task {task_id} is in unresolved_items but also in merged_tasks.")

        diff_item = diff_map.get(task_id)
        if not diff_item:
            raise StampingError(f"Task {task_id} not found in PlanDiff.")

        _emit_attribution_lifecycle(task_id, diff_item.kind)

        stamped = copy.deepcopy(task)
        metadata = {}
        spec_author = None
        stamping_reason = ""

        if diff_item.kind == DiffKind.convergent:
            metadata["proposed_by"] = "convergent"
            metadata["reconciled"] = False
            metadata["diff_resolution"] = None
            stamping_reason = "Task was convergent between both agents."
            # Spec author matches proposed_by for convergent (the one who proposed the winning version, but it's convergent so pick claude or gemini based on which it matches, but they are identical, so we just use the one it matched? Wait, spec says:
            # "otherwise it matches proposed_by (except convergent/reconciled which pick the agent that initially proposed the winning version)."
            if not bootstrap:
                if diff_item.claude_task and diff_item.claude_task.get("spec") == task.get("spec"):
                    spec_author = "claude"
                elif diff_item.gemini_task and diff_item.gemini_task.get("spec") == task.get("spec"):
                    spec_author = "gemini"
                else:
                    spec_author = "convergent"
        elif diff_item.kind == DiffKind.claude_only:
            metadata["proposed_by"] = "claude"
            metadata["reconciled"] = False
            metadata["diff_resolution"] = None
            stamping_reason = "Task was only proposed by Claude."
            if not bootstrap:
                spec_author = "claude"
        elif diff_item.kind == DiffKind.gemini_only:
            metadata["proposed_by"] = "gemini"
            metadata["reconciled"] = False
            metadata["diff_resolution"] = None
            stamping_reason = "Task was only proposed by Gemini."
            if not bootstrap:
                spec_author = "gemini"
        elif diff_item.kind in (DiffKind.divergent, DiffKind.ambiguous_match):
            metadata["proposed_by"] = "reconciled"
            metadata["reconciled"] = True
            # We cannot distinguish concession vs tiebreaker without logs, default to reconciled.
            metadata["diff_resolution"] = "reconciled"
            stamping_reason = "Task was divergent and resolved via reconciliation."
            
            if not bootstrap:
                # pick the agent that initially proposed the winning version
                if diff_item.claude_task and diff_item.claude_task.get("spec") == task.get("spec"):
                    spec_author = "claude"
                elif diff_item.gemini_task and diff_item.gemini_task.get("spec") == task.get("spec"):
                    spec_author = "gemini"

        stamped["attribution_metadata"] = metadata
        stamped["spec_author"] = spec_author
        
        # Add debug reasoning
        stamped["_debug_stamping_reason"] = stamping_reason

        stamped_tasks.append(stamped)

    return stamped_tasks
