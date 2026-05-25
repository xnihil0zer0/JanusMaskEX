"""submit_plan_draft verb — extracted from mcp_server.cmd_submit_plan_draft.

Planning-mode, single-shot. Delegates plan validation to
`harness.planner.plan_validator.validate_plan` (imported lazily so the MCP
side can fail soft if the planner package is not yet importable).

Caller owns idempotency (MCP: self.plan_submitted; hook: ledger flag).
"""

from __future__ import annotations

import json
import os
import pathlib
import uuid
from typing import Any


def validate(args: dict[str, Any]) -> list[Any]:
    """Run the plan validator; returns a list of PlanViolation.

    Lazy import mirrors mcp_server.cmd_submit_plan_draft's defensive check so
    an unavailable planner package degrades to an empty violation list
    (callers can turn this into a runtime error if they prefer)."""
    try:
        from harness.planner.plan_validator import validate_plan
    except ImportError:
        return []
    return list(validate_plan(args))


def persist(
    record: dict[str, Any],
    *,
    state_dir: pathlib.Path,
    agent: str,
) -> pathlib.Path:
    target_dir = pathlib.Path(state_dir) / "planning" / "sessions"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{agent}_draft.json"
    tmp = target.with_suffix(f".tmp.{os.getpid()}.{uuid.uuid4().hex}")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp.rename(target)
    return target


def rejected_payload(
    violations: list[Any], *, max_show: int = 50
) -> dict[str, Any]:
    truncated = False
    if len(violations) > max_show:
        violations = violations[:max_show]
        truncated = True
    violation_dicts = [
        {"code": v.code, "path": v.path, "message": v.message}
        for v in violations
    ]
    msg = "Plan validation failed. Fix these violations and resubmit."
    if truncated:
        msg += f" (Showing first {max_show} violations. There are more errors to fix)."
    return {"status": "rejected", "message": msg, "violations": violation_dicts}


def accepted_payload() -> dict[str, Any]:
    return {"status": "accepted"}
