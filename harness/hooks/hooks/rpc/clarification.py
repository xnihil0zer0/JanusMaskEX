"""request_clarification verb — extracted from mcp_server.cmd_request_clarification.

Responsibilities: build clarification record + persist. The MAX=2 rate-limit
stays caller-side (MCP: self.clarifications; hook: ledger count).
"""

from __future__ import annotations

import json
import os
import pathlib
import uuid
from typing import Any

MAX_CLARIFICATIONS = 2

_REQUIRED_LOCKED = ("session_id", "agent_identity", "round_number", "timestamp")


class SchemaError(ValueError):
    """Raised when the clarification payload is missing required fields."""


def build_record(args: dict[str, Any], clarification_number: int) -> dict[str, Any]:
    for key in _REQUIRED_LOCKED:
        if key not in args:
            raise SchemaError(
                f"clarification args missing required locked field {key!r}; "
                f"caller must stamp session_id/agent_identity/round_number/timestamp "
                f"before calling build_record."
            )
    question = args.get("question")
    if not isinstance(question, str) or question == "":
        raise SchemaError(
            "request_clarification requires a non-empty 'question' string in args."
        )
    return {
        "session_id": args["session_id"],
        "agent_identity": args["agent_identity"],
        "round_number": args["round_number"],
        "timestamp": args["timestamp"],
        "clarification_number": clarification_number,
        "question": question,
    }


def persist(
    record: dict[str, Any],
    *,
    state_dir: pathlib.Path,
    agent: str,
    clarification_number: int,
) -> pathlib.Path:
    sessions_dir = pathlib.Path(state_dir) / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    target = sessions_dir / f"{agent}_clarification_{clarification_number}.json"
    tmp = target.with_suffix(f".tmp.{os.getpid()}.{uuid.uuid4().hex}")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp.rename(target)
    return target


def accepted_payload(clarification_number: int, remaining: int) -> dict[str, Any]:
    return {
        "status": "acknowledged",
        "message": (
            f"Clarification request #{clarification_number} recorded. "
            f"{remaining} remaining."
        ),
    }
