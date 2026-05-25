"""PostToolUse hook for the Claude worker (P2 / HOOK-23).

Owns the persistence half of the MCP verbs whose validation moved to
PreToolUse (HOOK-22). Fires after a ``Write`` tool returns; re-reads
the on-disk outbox file (never trusts ``tool_input.content``, since
the agent could have mutated it between PreToolUse and the Write),
stamps locked fields (session_id, agent_identity, round_number,
timestamp) from env + STATE, calls the appropriate ``rpc.*.persist``
to atomically land the canonical ``state/sessions/`` record, appends
an ``outcome=allow`` ledger row with a sha256 digest, emits the
``clean_success`` track-record event, and pushes a console event
to stderr for UI parity with the old MCP ``ConsoleStreamer`` path.

PostToolUse can never block retroactively — the worst case on any
error is to return ``{"decision": "allow"}`` and skip persistence.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import pathlib
import re
import sys
from typing import Any, TextIO

from harness.safe_subpath import is_safe_subpath

from .. import _common, _ledger, _paths, _state_gates
from ..console import ConsoleStreamer
from ..rpc import (
    clarification as rpc_clarification,
    error_report as rpc_error_report,
    submit_code as rpc_submit_code,
    submit_plan_draft as rpc_submit_plan_draft,
    submit_reconciliation as rpc_submit_reconciliation,
)
from . import _env

_HOOK_NAME = "PostToolUse"

_CLARIFICATION_RE = re.compile(r"^clarification_(\d+)\.md$")


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _sha256(data: str) -> str:
    return "sha256:" + hashlib.sha256(data.encode("utf-8")).hexdigest()


def _read_file(path: pathlib.Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None


def _locked_fields(session_id: str, agent: str, round_number: int) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "agent_identity": agent,
        "round_number": round_number,
        "timestamp": _now_iso(),
    }


def _allow(stdout: TextIO) -> int:
    _common.write_decision(_common.decision_payload("allow"), stdout)
    return 0


# -- per-verb persistence -------------------------------------------------


def _persist_submission(
    *,
    session_id: str,
    agent: str,
    round_number: int,
    phase: str,
    content: str,
    explanation: str,
    events: list[dict[str, Any]],
) -> None:
    task = _paths.load_inbox_task(_env.inbox_dir(session_id))
    task_id = str(task.get("task_id") or "default")
    synthesis_target_type = str(task.get("synthesis_target_type", "") or "")
    # Mirror _decide_submission's allow_nondet derivation so PreToolUse and
    # the persist-time gate agree on which submissions pass.
    constraints = task.get("constraints", {})
    if not isinstance(constraints, dict):
        sys.stderr.write(
            "WARNING: malformed constraints payload (expected dict, got "
            f"{type(constraints).__name__})\n"
        )
        constraints = {}
    allow_nondet = constraints.get("deterministic") is False
    if not allow_nondet:
        mtt = task.get("meta_task_type") or constraints.get("meta_task_type")
        if mtt in {"io_adapter", "logging_observability"}:
            allow_nondet = True

    # Persist-time AST gate (B3 blocker #8): PreToolUse may have been
    # bypassed by --permission-mode bypassPermissions / yolo, so we must
    # re-validate disk_content here before any state/sessions/ write.
    try:
        rpc_submit_code.ensure_valid(content, allow_nondeterminism=allow_nondet)
    except rpc_submit_code.AstValidationError as exc:
        errors = [v for v in exc.violations if getattr(v, "severity", "") == "error"]
        violation_dicts = [
            {"rule": v.rule, "severity": v.severity, "line": v.line, "message": v.message}
            for v in errors
        ]
        _ledger.append_hook_event(
            session_id,
            agent,
            "submit_code",
            "deny",
            hook=_HOOK_NAME,
            tool="Write",
            round_number=round_number,
            phase=phase,
            detail={
                "reason": "persist_time_ast_gate",
                "task_id": task_id,
                "error_count": len(errors),
                "violations": violation_dicts,
            },
        )
        rpc_submit_code.emit_ast_rejection(
            agent=agent,
            task_id=task_id,
            synthesis_target_type=synthesis_target_type,
            state_dir=_paths.state_dir(),
        )
        sys.stderr.write(f"PostToolUse persist-time AST gate denied submission: {exc}\n")
        return

    submissions_so_far = _ledger.count_verb(events, "submit_code", outcome="allow")
    submission_number = submissions_so_far + 1

    args = dict(_locked_fields(session_id, agent, round_number))
    args["code"] = content
    args["explanation"] = explanation

    try:
        record = rpc_submit_code.build_record(args, submission_number=submission_number)
        rpc_submit_code.persist(
            record, state_dir=_paths.state_dir(), agent=agent, task_id=task_id
        )
    except rpc_submit_code.SchemaError as exc:
        sys.stderr.write(f"PostToolUse submit_code schema error: {exc}\n")
        _ledger.append_hook_event(
            session_id,
            agent,
            "submit_code",
            "invalid",
            hook=_HOOK_NAME,
            tool="Write",
            round_number=round_number,
            phase=phase,
            digest=_sha256(content),
            detail={
                "reason": "schema_error",
                "task_id": task_id,
                "error": str(exc),
            },
        )
        return

    rpc_submit_code.emit_clean_success(
        agent=agent,
        task_id=task_id,
        synthesis_target_type=synthesis_target_type,
        state_dir=_paths.state_dir(),
    )
    _ledger.append_hook_event(
        session_id,
        agent,
        "submit_code",
        "allow",
        hook=_HOOK_NAME,
        tool="Write",
        round_number=round_number,
        phase=phase,
        counters={"submissions": submission_number},
        digest=_sha256(content),
        detail={"task_id": task_id, "submission_number": submission_number},
    )
    try:
        ConsoleStreamer(agent).on_submit_accepted(
            content, submission_number, rpc_submit_code.MAX_SUBMISSIONS,
            round_number, warnings=[],
        )
    except Exception:
        # Console I/O must never break persistence.
        pass


def _persist_clarification(
    *,
    file_path: str,
    session_id: str,
    agent: str,
    round_number: int,
    phase: str,
    content: str,
) -> None:
    basename = pathlib.Path(file_path).name
    m = _CLARIFICATION_RE.match(basename)
    if not m:
        return
    number = int(m.group(1))
    args = dict(_locked_fields(session_id, agent, round_number))
    args["question"] = content
    try:
        record = rpc_clarification.build_record(args, clarification_number=number)
        rpc_clarification.persist(
            record,
            state_dir=_paths.state_dir(),
            agent=agent,
            clarification_number=number,
        )
    except rpc_clarification.SchemaError as exc:
        sys.stderr.write(f"PostToolUse clarification schema error: {exc}\n")
        _ledger.append_hook_event(
            session_id,
            agent,
            "clarification",
            "invalid",
            hook=_HOOK_NAME,
            tool="Write",
            round_number=round_number,
            phase=phase,
            digest=_sha256(content),
            detail={
                "reason": "schema_error",
                "clarification_number": number,
                "error": str(exc),
            },
        )
        return
    _ledger.append_hook_event(
        session_id,
        agent,
        "clarification",
        "allow",
        hook=_HOOK_NAME,
        tool="Write",
        round_number=round_number,
        phase=phase,
        counters={"clarifications": number},
        digest=_sha256(content),
        detail={"clarification_number": number},
    )
    remaining = rpc_clarification.MAX_CLARIFICATIONS - number
    try:
        ConsoleStreamer(agent).on_clarification(content, number, remaining)
    except Exception:
        pass


def _persist_error_report(
    *,
    session_id: str,
    agent: str,
    round_number: int,
    phase: str,
    content: str,
) -> None:
    args = dict(_locked_fields(session_id, agent, round_number))
    args["error"] = content
    try:
        record = rpc_error_report.build_record(args)
        rpc_error_report.persist(
            record, state_dir=_paths.state_dir(), agent=agent
        )
    except rpc_error_report.SchemaError as exc:
        sys.stderr.write(f"PostToolUse error_report schema error: {exc}\n")
        _ledger.append_hook_event(
            session_id,
            agent,
            "error",
            "invalid",
            hook=_HOOK_NAME,
            tool="Write",
            round_number=round_number,
            phase=phase,
            digest=_sha256(content),
            detail={"reason": "schema_error", "error": str(exc)},
        )
        return
    _ledger.append_hook_event(
        session_id,
        agent,
        "error",
        "allow",
        hook=_HOOK_NAME,
        tool="Write",
        round_number=round_number,
        phase=phase,
        digest=_sha256(content),
    )
    try:
        ConsoleStreamer(agent).on_error_report(content)
    except Exception:
        pass


def _persist_plan_draft(
    *,
    session_id: str,
    agent: str,
    round_number: int,
    phase: str,
    content: str,
) -> None:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"PostToolUse plan_draft JSON decode error: {exc}\n")
        _ledger.append_hook_event(
            session_id,
            agent,
            "plan_draft",
            "invalid",
            hook=_HOOK_NAME,
            tool="Write",
            round_number=round_number,
            phase=phase,
            digest=_sha256(content),
            detail={"reason": "json_decode_error", "error": str(exc)},
        )
        return
    try:
        rpc_submit_plan_draft.persist(
            parsed, state_dir=_paths.state_dir(), agent=agent
        )
    except OSError as exc:
        sys.stderr.write(f"PostToolUse plan_draft persist error: {exc}\n")
        _ledger.append_hook_event(
            session_id,
            agent,
            "plan_draft",
            "invalid",
            hook=_HOOK_NAME,
            tool="Write",
            round_number=round_number,
            phase=phase,
            digest=_sha256(content),
            detail={"reason": "persist_error", "error": str(exc)},
        )
        return
    _ledger.append_hook_event(
        session_id,
        agent,
        "plan_draft",
        "allow",
        hook=_HOOK_NAME,
        tool="Write",
        round_number=round_number,
        phase=phase,
        digest=_sha256(content),
    )


def _persist_reconciliation(
    *,
    session_id: str,
    agent: str,
    round_number: int,
    phase: str,
    content: str,
) -> None:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"PostToolUse reconciliation JSON decode error: {exc}\n")
        _ledger.append_hook_event(
            session_id,
            agent,
            "reconciliation",
            "invalid",
            hook=_HOOK_NAME,
            tool="Write",
            round_number=round_number,
            phase=phase,
            digest=_sha256(content),
            detail={"reason": "json_decode_error", "error": str(exc)},
        )
        return
    try:
        rpc_submit_reconciliation.persist(
            parsed, state_dir=_paths.state_dir(), agent=agent
        )
    except OSError as exc:
        sys.stderr.write(f"PostToolUse reconciliation persist error: {exc}\n")
        _ledger.append_hook_event(
            session_id,
            agent,
            "reconciliation",
            "invalid",
            hook=_HOOK_NAME,
            tool="Write",
            round_number=round_number,
            phase=phase,
            digest=_sha256(content),
            detail={"reason": "persist_error", "error": str(exc)},
        )
        return
    _ledger.append_hook_event(
        session_id,
        agent,
        "reconciliation",
        "allow",
        hook=_HOOK_NAME,
        tool="Write",
        round_number=round_number,
        phase=phase,
        digest=_sha256(content),
    )


# -- dispatcher ----------------------------------------------------------


def main(stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    try:
        payload = _common.read_input(stdin)
    except _common.HookInputError as exc:
        sys.stderr.write(f"PostToolUse: malformed stdin: {exc}\n")
        return _allow(stdout)

    tool_name = str(payload.get("tool_name") or "")
    # Write-only by design (T2-12 option b). The worker allowlist
    # (pre_tool.ALLOWED_TOOLS + config/claude_worker_hooks.json deny
    # list) prevents Edit/NotebookEdit from ever reaching the worker,
    # so anything other than Write here is a benign pass-through
    # (Read/Glob/Grep). Outbox submissions are whole-file atomic
    # writes; supporting Edit would require an AST-reconstruction
    # path equivalent to Gemini's _reconstruct_replace with no
    # matching runtime benefit (see brief_hooks_schema_drift_fix_plan
    # §3 T2-12).
    if tool_name != "Write":
        return _allow(stdout)

    tool_input = payload.get("tool_input") or {}
    tool_response = payload.get("tool_response") or {}
    if tool_response.get("success") is False:
        return _allow(stdout)

    file_path = str(tool_input.get("file_path") or tool_response.get("filePath") or "")
    if not file_path:
        return _allow(stdout)

    session_id = str(payload.get("session_id") or "")
    agent = _paths.agent() or "claude"
    state = _state_gates.read_state_besteffort()
    round_number = _state_gates.current_round(state)
    phase = _state_gates.current_phase(state) or _paths.mode()

    # Defence-in-depth: even though PreToolUse would have denied
    # anything outside the outbox, never persist writes we didn't gate.
    outbox = _env.outbox_dir(session_id).resolve()
    if not is_safe_subpath(file_path, str(outbox)):
        return _allow(stdout)

    disk_content = _read_file(pathlib.Path(file_path))
    if disk_content is None:
        # File vanished between Write and PostToolUse; surface but allow.
        sys.stderr.write(
            f"PostToolUse: file missing at {file_path}; skipping persistence.\n"
        )
        return _allow(stdout)

    try:
        rel = pathlib.Path(file_path).resolve().relative_to(outbox).as_posix()
    except ValueError:
        return _allow(stdout)

    events = _ledger.read_events(session_id, agent)

    if rel == "submission.py":
        explanation = str(tool_input.get("explanation") or "")
        _persist_submission(
            session_id=session_id,
            agent=agent,
            round_number=round_number,
            phase=phase,
            content=disk_content,
            explanation=explanation,
            events=events,
        )
    elif rel.startswith("clarification_") and rel.endswith(".md"):
        _persist_clarification(
            file_path=file_path,
            session_id=session_id,
            agent=agent,
            round_number=round_number,
            phase=phase,
            content=disk_content,
        )
    elif rel == "error.md":
        _persist_error_report(
            session_id=session_id,
            agent=agent,
            round_number=round_number,
            phase=phase,
            content=disk_content,
        )
    elif rel == "plan_draft.json":
        _persist_plan_draft(
            session_id=session_id,
            agent=agent,
            round_number=round_number,
            phase=phase,
            content=disk_content,
        )
    elif rel == "reconciliation.json":
        _persist_reconciliation(
            session_id=session_id,
            agent=agent,
            round_number=round_number,
            phase=phase,
            content=disk_content,
        )
    # Unknown rel: silently allow (not the hook's job to gate here).

    return _allow(stdout)


if __name__ == "__main__":
    raise SystemExit(main())
