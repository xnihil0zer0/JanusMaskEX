"""report_error verb — extracted from mcp_server.cmd_report_error.

Named `error_report` (not `error`) to avoid collision with the common name.
"""

from __future__ import annotations

import json
import os
import pathlib
import uuid
from typing import Any

_REQUIRED_LOCKED = ("session_id", "agent_identity", "round_number", "timestamp")


class SchemaError(ValueError):
    """Raised when the error-report payload is missing required fields."""


def build_record(args: dict[str, Any]) -> dict[str, Any]:
    for key in _REQUIRED_LOCKED:
        if key not in args:
            raise SchemaError(
                f"error_report args missing required locked field {key!r}; "
                f"caller must stamp locked fields before calling build_record."
            )
    err = args.get("error")
    if not isinstance(err, str) or err == "":
        raise SchemaError(
            "report_error requires a non-empty 'error' string in args."
        )
    return {
        "session_id": args["session_id"],
        "agent_identity": args["agent_identity"],
        "round_number": args["round_number"],
        "timestamp": args["timestamp"],
        "error": err,
    }


def persist(
    record: dict[str, Any],
    *,
    state_dir: pathlib.Path,
    agent: str,
) -> pathlib.Path:
    sessions_dir = pathlib.Path(state_dir) / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    target = sessions_dir / f"{agent}_error.json"
    tmp = target.with_suffix(f".tmp.{os.getpid()}.{uuid.uuid4().hex}")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp.rename(target)
    return target


def accepted_payload() -> dict[str, Any]:
    return {"status": "acknowledged", "message": "Error report recorded."}
