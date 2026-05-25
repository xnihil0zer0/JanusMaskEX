"""submit_reconciliation_response verb — extracted from
mcp_server.cmd_submit_reconciliation_response.

Responsibilities:
    * load_valid_diff_ids   -- read planning/current_diff.json → {diff_item_id}
    * validate_responses    -- stance whitelist + diff_item_id cross-check
    * persist               -- atomic write of planning/sessions/{agent}_reconciliation.json

Caller owns single-shot guard (MCP: self.reconciliation_submitted; hook: ledger).
"""

from __future__ import annotations

import json
import os
import pathlib
import uuid
from typing import Any

VALID_STANCES = frozenset({"defend", "concede", "amend"})


def load_valid_diff_ids(state_dir: pathlib.Path) -> set[str]:
    diff_path = pathlib.Path(state_dir) / "planning" / "current_diff.json"
    if not diff_path.exists():
        return set()
    try:
        diff = json.loads(diff_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    return {item.get("diff_item_id") for item in diff.get("items", []) if item.get("diff_item_id")}


def validate_responses(
    responses: Any, *, valid_ids: set[str]
) -> str | None:
    """Returns None on success, or a short human-readable error string."""
    if not isinstance(responses, list):
        return "responses must be a list"
    for resp in responses:
        if not isinstance(resp, dict):
            return "response must be a dict"
        stance = resp.get("stance")
        if stance not in VALID_STANCES:
            return f"Unknown stance: {stance}"
        diff_id = resp.get("diff_item_id")
        if diff_id not in valid_ids:
            return f"Unknown diff item: {diff_id}"
    return None


def persist(
    record: dict[str, Any],
    *,
    state_dir: pathlib.Path,
    agent: str,
) -> pathlib.Path:
    target_dir = pathlib.Path(state_dir) / "planning" / "sessions"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{agent}_reconciliation.json"
    tmp = target.with_suffix(f".tmp.{os.getpid()}.{uuid.uuid4().hex}")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp.rename(target)
    return target


def accepted_payload() -> dict[str, Any]:
    return {"status": "accepted"}
