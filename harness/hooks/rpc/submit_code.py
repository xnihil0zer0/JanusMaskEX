"""submit_code verb — extracted from mcp_server.cmd_submit_code.

Responsibilities (shared between MCP and Claude/Gemini hooks):
    * validate        -- AST gate via harness.ast_enforcer.validate_code
    * build_record    -- assemble canonical submission dict (strict schema)
    * persist         -- atomic write under state/sessions/
    * rejected_payload / accepted_payload -- response shapes

Out of scope (caller's job):
    * submission counter enforcement (MCP: self.submissions; hook: ledger)
    * console streaming
    * locked-field injection (caller stamps session_id/agent_identity/
      round_number/timestamp BEFORE calling build_record)

Canonical submission schema (mcp_server.py:648-658):
    session_id, agent_identity, round_number, timestamp,
    submission_number, code, explanation
"""

from __future__ import annotations

import json
import os
import pathlib
import uuid
from typing import Any

from harness.ast_enforcer import Violation, validate_code
from harness.session_namer import generate_submission_filename

# Public constant — mirrors JanusMaskServer.MAX_SUBMISSIONS for callers that
# want to drive the cap from this module.
MAX_SUBMISSIONS = 5

# Ordered schema per mcp_server.py:648-658; required for every submission.
_REQUIRED_LOCKED = ("session_id", "agent_identity", "round_number", "timestamp")
_REQUIRED_CONTENT = ("code", "explanation")

_SCHEMA_REF = "mcp_server.py:648-658"


class SchemaError(ValueError):
    """Raised when a submission payload is missing required schema fields."""


class AstValidationError(Exception):
    """Raised by ensure_valid() when AST validation finds error-severity
    violations. The full violation list (errors + any warnings produced in
    the same pass) is carried on the ``violations`` attribute so persist-
    layer callers can emit a deny ledger row that mirrors the same payload
    PreToolUse would have surfaced to the agent."""

    def __init__(self, violations: list[Violation]) -> None:
        # Defensive copy: callers may mutate the list (e.g. truncate for
        # display) without affecting other handlers downstream.
        self.violations: list[Violation] = list(violations)
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        errors = [v for v in self.violations if getattr(v, "severity", "") == "error"]
        if not errors:
            return "AST validation failed"
        previews = [f"[{v.rule}] {v.message} @L{v.line}" for v in errors[:5]]
        suffix = "" if len(errors) <= 5 else f" (+{len(errors) - 5} more)"
        return "AST validation failed: " + "; ".join(previews) + suffix

    def __str__(self) -> str:
        return self._format_message()


def validate(code: str, *, allow_nondeterminism: bool = False, relax_external_constructs: bool = False) -> list[Violation]:
    """Run the AST gate on the submission. Returns list of Violation; empty
    means clean. Warnings are retained so callers can surface them to the
    agent without blocking the write.

    ``relax_external_constructs`` (REV22 §4-3) is threaded straight through to
    ``validate_code``: when True (external target), eval/exec/__import__ are
    allowed while credentials/os_system/bare_except/nondeterminism stay strict.
    """
    return validate_code(
        code,
        allow_nondeterminism=allow_nondeterminism,
        relax_external_constructs=relax_external_constructs,
    )


def ensure_valid(
    code: str, allow_nondeterminism: bool = False, relax_external_constructs: bool = False
) -> list[Violation]:
    """Persist-time AST gate. Raises ``AstValidationError`` carrying the
    full violation list when any error-severity violation is found; returns
    the (possibly empty) list of warning-only violations otherwise.

    This is the gate the post_tool layer must call BEFORE writing the
    submission record to ``state/sessions/`` — closing the asymmetry where
    PreToolUse correctly denied a submission but a CLI in bypass-permissions
    mode let the Write reach disk anyway, leaving the orchestrator to
    re-reject the same bytes and burn retries.

    ``relax_external_constructs`` (REV22 §4-3) is threaded through to
    ``validate_code`` so external targets pass the eval/exec/__import__ relax
    at persist-time too.
    """
    violations = validate_code(
        code,
        allow_nondeterminism=allow_nondeterminism,
        relax_external_constructs=relax_external_constructs,
    )
    if any(getattr(v, "severity", "") == "error" for v in violations):
        raise AstValidationError(violations)
    return violations


def build_record(args: dict[str, Any], submission_number: int) -> dict[str, Any]:
    """Build the canonical submission dict. Raises SchemaError on any missing
    required field, with `mcp_server.py:648-658` in the message so the agent
    can look up the schema."""
    missing: list[str] = []
    for key in _REQUIRED_LOCKED + _REQUIRED_CONTENT:
        if key not in args:
            missing.append(key)
    if missing:
        raise SchemaError(
            f"submit_code args missing required fields {missing}; "
            f"canonical schema is at {_SCHEMA_REF} "
            f"(session_id, agent_identity, round_number, timestamp, "
            f"submission_number, code, explanation)."
        )
    code = args.get("code")
    if not isinstance(code, str) or code == "":
        raise SchemaError(
            f"submit_code 'code' must be a non-empty string; see {_SCHEMA_REF}."
        )
    return {
        "session_id": args["session_id"],
        "agent_identity": args["agent_identity"],
        "round_number": args["round_number"],
        "timestamp": args["timestamp"],
        "submission_number": submission_number,
        "code": code,
        "explanation": args["explanation"],
    }


def persist(
    record: dict[str, Any],
    *,
    state_dir: pathlib.Path,
    agent: str,
    task_id: str,
) -> pathlib.Path:
    """Atomically write the submission to state/sessions/<canonical-filename>.

    Idempotent under concurrent calls: uses tmp + rename so the visible file
    is always complete. Raises SchemaError if the record is missing any of
    the canonical schema keys (defence-in-depth; callers normally go through
    build_record first). The `agent` kwarg is accepted for API uniformity
    with the other rpc verbs; the canonical identity lives at
    record["agent_identity"].
    """
    del agent  # unused; record["agent_identity"] is authoritative
    for key in _REQUIRED_LOCKED + _REQUIRED_CONTENT + ("submission_number",):
        if key not in record:
            raise SchemaError(
                f"submission record missing required field {key!r}; "
                f"canonical schema is at {_SCHEMA_REF}."
            )
    sessions_dir = pathlib.Path(state_dir) / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    filename = generate_submission_filename(
        record["agent_identity"], record["round_number"], task_id
    )
    target = sessions_dir / filename
    tmp = target.with_suffix(f".tmp.{os.getpid()}.{uuid.uuid4().hex}")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp.rename(target)
    return target


def rejected_payload(
    violations: list[Violation], *, max_show: int = 50
) -> dict[str, Any]:
    errors = [v for v in violations if getattr(v, "severity", "") == "error"]
    truncated = False
    if len(errors) > max_show:
        errors = errors[:max_show]
        truncated = True
    violation_dicts = [
        {"rule": v.rule, "line": v.line, "message": v.message}
        for v in errors
    ]
    msg = "Fix violations and resubmit."
    if truncated:
        msg += f" (Showing first {max_show} violations. There are more errors to fix)."
    return {
        "status": "rejected",
        "ast_valid": False,
        "violations": violation_dicts,
        "message": msg,
    }


def accepted_payload(warnings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "accepted",
        "ast_valid": True,
        "message": "Code accepted. Awaiting differential fuzzing.",
    }
    if warnings:
        payload["warnings"] = warnings
    return payload


def warnings_from_violations(violations: list[Violation]) -> list[dict[str, Any]]:
    return [
        {"rule": v.rule, "line": v.line, "message": v.message}
        for v in violations
        if getattr(v, "severity", "") == "warning"
    ]


# -- track-record emission (HOOK-14) ---------------------------------------
# Pure-additive bridges into harness.track_record_events. Callers (MCP today,
# Claude/Gemini hooks tomorrow) invoke these after the AST gate so the
# synthesis book stays in sync. EventValidationError is swallowed so a
# missing taxonomy entry or unknown agent never blocks the verb path — the
# goal is telemetry, not correctness.


def _emit_synthesis_event(
    event_type: str,
    *,
    agent: str,
    task_id: str,
    synthesis_target_type: str,
    delta: dict[str, int],
    state_dir: pathlib.Path | None = None,
) -> dict[str, Any] | None:
    from harness.track_record_events import append_track_event, EventValidationError
    try:
        return append_track_event(
            event_type=event_type,
            book="synthesis",
            agent=agent,
            type=synthesis_target_type,
            task_id=task_id,
            delta=delta,
            state_dir=state_dir,
        )
    except EventValidationError:
        return None
    except Exception:
        # Defensive: any other telemetry failure (fs permission, taxonomy load
        # error) must not break the caller's submission path.
        return None


def emit_ast_rejection(
    agent: str,
    task_id: str,
    synthesis_target_type: str,
    state_dir: pathlib.Path | None = None,
) -> dict[str, Any] | None:
    """Emit a `synthesis/ast_rejection` track-record event.

    Mirrors harness.track_record.ast_rejection_event's delta shape
    ({failures: 1, attempts: 1}). Returns the row dict on success, None on
    any validation failure (never raises).
    """
    return _emit_synthesis_event(
        "ast_rejection",
        agent=agent,
        task_id=task_id,
        synthesis_target_type=synthesis_target_type,
        delta={"failures": 1, "attempts": 1},
        state_dir=state_dir,
    )


def emit_clean_success(
    agent: str,
    task_id: str,
    synthesis_target_type: str,
    state_dir: pathlib.Path | None = None,
) -> dict[str, Any] | None:
    """Emit a `synthesis/clean_success` track-record event.

    Mirrors harness.track_record.clean_success_event's delta shape
    ({failures: 0, attempts: 1}). Returns the row dict on success, None on
    any validation failure (never raises).
    """
    return _emit_synthesis_event(
        "clean_success",
        agent=agent,
        task_id=task_id,
        synthesis_target_type=synthesis_target_type,
        delta={"failures": 0, "attempts": 1},
        state_dir=state_dir,
    )
