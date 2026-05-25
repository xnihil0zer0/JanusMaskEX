"""PreToolUse hook for the Claude worker (P2 / HOOK-22).

Supersedes ``harness/hook_pre_tool.py`` (which is now a thin shim
delegating to ``legacy_dispatch`` and ``main`` herein). Implements the
full tool-allowlist + Write-dispatch matrix from sub-plan 02 §4.3:

    Global:    deny any tool not in {Read, Glob, Grep, Write}
    Read-ish:  allow iff path under JANUSMASK_WORK_DIR, $STATE_DIR,
               or a whitelisted docs root; else deny
    Write:     dispatch by outbox basename to the matching rpc/* verb
               (submit_code, submit_plan_draft, submit_reconciliation,
               clarification, error_report); mode-gated so synthesis
               can't ship a plan_draft etc.

Rate limits are derived from the per-session ledger
(``harness.hooks._ledger``) so hook short-lived processes stay
counter-free. AST rejection emits both an ``outcome=deny`` ledger row
(for audit + replay) and the ``synthesis/ast_rejection`` track-record
event (HOOK-14). Rate-limit denials use a distinct ``rate_limited``
outcome and never touch the track-record book.

Write-dispatch deciders (submission/plan_draft/reconciliation/
error_report) and the Read/Glob/Grep gate live in
``harness.hooks._decide_common``; this module wraps them with the
Claude-specific ``_journal`` (tool=Write) and
``_allow_with_warning_context`` envelope builders.

``_decide_clarification`` stays local: its happy-path allow envelope
is flat ``{decision, tool_input}`` (via ``_common.decision_payload``)
rather than Gemini's nested ``hookSpecificOutput.tool_input`` wrap,
and that divergence does not collapse into a single callable.

PostToolUse (HOOK-23) handles persistence into
``state/sessions/`` — this hook is validation + gating only, never
writes the canonical submission.

``legacy_dispatch`` (below, module-level) preserves the MCP-era
PreToolUse semantics used by the ``harness/hook_pre_tool.py`` shim
for the legacy ``{tool_name}``-only payload shape. See HOOK-45.
"""

from __future__ import annotations

import os
import pathlib
import sys
from typing import Any, TextIO

from harness.safe_subpath import is_safe_subpath

from .. import _common, _decide_common, _ledger, _paths, _state_gates
from ..rpc import clarification as rpc_clarification
from . import _env
from harness import hooks_equivalence

_HOOK_NAME = "PreToolUse"

ALLOWED_TOOLS: frozenset[str] = frozenset({"Read", "Glob", "Grep", "Write"})

_OUTBOX_ROUTES = {
    "submission.py",
    "plan_draft.json",
    "reconciliation.json",
    "error.md",
}

# Re-exports: kept as module-level aliases because test partners
# (tests/hooks/invariants/test_ast_retry_prompt_regression.py,
# tests/adversarial/test_P4_ast_retry_prompt_regression.py) reach
# ``claude.pre_tool._format_ast_reason`` directly.
_format_ast_reason = _decide_common.format_ast_reason
_format_plan_reason = _decide_common.format_plan_reason

# Legacy MCP-era allowlists consumed by ``legacy_dispatch`` (HOOK-45
# shim target). Kept module-level so the constants remain inspectable
# from ``harness.hooks.claude.pre_tool`` (mirroring the old
# ``harness/hook_pre_tool.py`` surface area). Retire at P6
# (HOOK-50-retire-mcp).
_LEGACY_ALLOWED_TOOLS: frozenset[str] = frozenset({
    "mcp__janusmask__execute",
    "mcp_janusmask_execute",
})
_LEGACY_ALLOWED_SUBAGENT_TOOLS: frozenset[str] = frozenset({
    "read_file", "list_directory", "grep_search", "glob",
    "Read", "Glob", "Grep",
})


def legacy_dispatch(payload: dict) -> dict:
    """Legacy MCP-era PreToolUse dispatch for the old ``{tool_name}``
    payload shape (HOOK-45 shim target).

    Returns the decision dict that the caller writes to stdout.
    Preserves the semantics of the original ``_legacy_dispatch`` body
    from ``harness/hook_pre_tool.py``: only ``mcp__janusmask__execute``
    (and its underscore variant) are allowed under the default
    ``synthesis`` mode; under non-synthesis modes the agent/subagent
    read-like tools are additionally permitted. Retire at P6
    (HOOK-50-retire-mcp).
    """
    tool_name = payload.get("tool_name")
    mode = os.environ.get("JANUSMASK_MODE", "synthesis")
    allowed = set(_LEGACY_ALLOWED_TOOLS)
    if mode != "synthesis":
        allowed |= {"Agent", "generalist", "codebase_investigator"}
        allowed |= set(_LEGACY_ALLOWED_SUBAGENT_TOOLS)
    if tool_name in allowed:
        return _common.decision_payload("allow")
    return _common.decision_payload(
        "deny",
        reason=(
            f"Only the janusmask MCP tool and sub-agents are permitted. "
            f"Blocked tool: {tool_name}. You MUST use mcp__janusmask__execute "
            f"to interact with the system, or spawn a sub-agent."
        ),
    )


def _read_allowed_roots(session_id: str | None) -> list[pathlib.Path]:
    project = _paths.project_dir()
    return [
        _env.work_dir(session_id),
        _paths.state_dir(),
        project / "docs",
        project / "briefs",
    ]


def _relpath_in_outbox(
    file_path: str, session_id: str | None
) -> str | None:
    """Return the outbox-relative posix path when `file_path` is safely
    under the outbox; None otherwise."""
    outbox = _env.outbox_dir(session_id).resolve()
    if not is_safe_subpath(file_path, str(outbox)):
        return None
    try:
        return pathlib.Path(file_path).resolve().relative_to(outbox).as_posix()
    except ValueError:
        return None


def _allowed_for_mode(rel: str, mode: str) -> bool:
    if rel == "error.md":
        return True
    if mode == "synthesis":
        if rel == "submission.py":
            return True
        return rel.startswith("clarification_") and rel.endswith(".md")
    if mode == "planning":
        return rel == "plan_draft.json"
    if mode == "reconciliation":
        return rel == "reconciliation.json"
    return False


def _journal(
    session_id: str,
    agent: str,
    verb: str,
    outcome: str,
    *,
    round_number: int,
    phase: str,
    detail: dict[str, Any] | None = None,
) -> None:
    _ledger.append_hook_event(
        session_id,
        agent,
        verb,
        outcome,
        hook=_HOOK_NAME,
        tool="Write",
        round_number=round_number,
        phase=phase,
        detail=detail or {},
    )


def _allow_with_warning_context(
    warnings: list[dict[str, Any]], tool_input: dict[str, Any] | None = None
) -> dict[str, Any]:
    payload = _common.decision_payload("allow", tool_input=tool_input)
    bullets = "\n".join(
        f"- L{w['line']}: [{w['rule']}] {w['message']}" for w in warnings
    )
    payload["hookSpecificOutput"] = {
        "hookEventName": _HOOK_NAME,
        "additionalContext": f"AST warnings (non-blocking):\n{bullets}",
    }
    return payload


def _build_decider_ctx(
    session_id: str, agent: str, phase: str, round_number: int,
) -> _decide_common.DeciderContext:
    def _journal_closure(
        verb: str,
        outcome: str,
        *,
        detail: dict[str, Any] | None = None,
    ) -> None:
        _journal(
            session_id, agent, verb, outcome,
            round_number=round_number, phase=phase, detail=detail,
        )

    return _decide_common.DeciderContext(
        session_id=session_id,
        agent=agent,
        phase=phase,
        round_number=round_number,
        journal=_journal_closure,
        allow_with_warnings=_allow_with_warning_context,
    )


# -- per-verb deciders ----------------------------------------------------


def _decide_submission(
    content: str,
    events: list[dict[str, Any]],
    session_id: str,
    agent: str,
    phase: str,
    round_number: int,
) -> dict[str, Any]:
    return _decide_common.decide_submission(
        _build_decider_ctx(session_id, agent, phase, round_number),
        content,
        events,
        _env.inbox_dir(session_id),
    )


def _decide_plan_draft(
    content: str,
    events: list[dict[str, Any]],
    session_id: str,
    agent: str,
    phase: str,
    round_number: int,
) -> dict[str, Any]:
    return _decide_common.decide_plan_draft(
        _build_decider_ctx(session_id, agent, phase, round_number),
        content,
        events,
    )


def _decide_reconciliation(
    content: str,
    events: list[dict[str, Any]],
    session_id: str,
    agent: str,
    phase: str,
    round_number: int,
) -> dict[str, Any]:
    return _decide_common.decide_reconciliation(
        _build_decider_ctx(session_id, agent, phase, round_number),
        content,
        events,
    )


def _decide_clarification(
    tool_input: dict[str, Any],
    events: list[dict[str, Any]],
    session_id: str,
    agent: str,
    phase: str,
    round_number: int,
) -> dict[str, Any]:
    used = _ledger.count_verb(events, "clarification", outcome="allow")
    next_slot = used + 1
    if next_slot > rpc_clarification.MAX_CLARIFICATIONS:
        reason = (
            f"Clarification rate limit reached "
            f"({used}/{rpc_clarification.MAX_CLARIFICATIONS})."
        )
        _journal(
            session_id, agent, "clarification", "rate_limited",
            round_number=round_number, phase=phase,
            detail={"reason": reason, "counters": {"clarifications": used}},
        )
        return _common.decision_payload("deny", reason=reason)
    outbox = _env.outbox_dir(session_id)
    rewritten = dict(tool_input)
    rewritten["file_path"] = str(outbox / f"clarification_{next_slot}.md")
    return _common.decision_payload("allow", tool_input=rewritten)


def _decide_error_report(
    content: str,
    session_id: str,
    agent: str,
    phase: str,
    round_number: int,
) -> dict[str, Any]:
    return _decide_common.decide_error_report(
        _build_decider_ctx(session_id, agent, phase, round_number),
        content,
    )


# -- dispatchers ---------------------------------------------------------


def _decide_read_like(
    tool_input: dict[str, Any], session_id: str
) -> dict[str, Any]:
    return _decide_common.decide_read_like(
        tool_input,
        _read_allowed_roots(session_id),
        path_keys=("file_path", "path"),
        tool_name_for_reason="Read/Glob/Grep",
    )


def _decide_write(
    tool_input: dict[str, Any],
    session_id: str,
    agent: str,
    mode: str,
    phase: str,
    round_number: int,
) -> dict[str, Any]:
    file_path = str(tool_input.get("file_path") or "")
    content = tool_input.get("content")
    if not isinstance(content, str):
        content = ""
    if not file_path:
        return _common.decision_payload(
            "deny", reason="Write requires a file_path."
        )
    outbox = _env.outbox_dir(session_id)
    rel = _relpath_in_outbox(file_path, session_id)
    if rel is None:
        return _common.decision_payload(
            "deny",
            reason=f"Write must target {outbox}/; got {file_path}.",
        )
    if not _allowed_for_mode(rel, mode):
        return _common.decision_payload(
            "deny",
            reason=(
                f"Write to {rel!r} not permitted in mode={mode!r}. "
                f"Mode-specific outbox contract: "
                f"synthesis→submission.py|clarification_N.md|error.md, "
                f"planning→plan_draft.json|error.md, "
                f"reconciliation→reconciliation.json|error.md."
            ),
        )

    events = _ledger.read_events(session_id, agent)

    if rel == "submission.py":
        return _decide_submission(
            content, events, session_id, agent, phase, round_number
        )
    if rel == "plan_draft.json":
        return _decide_plan_draft(
            content, events, session_id, agent, phase, round_number
        )
    if rel == "reconciliation.json":
        return _decide_reconciliation(
            content, events, session_id, agent, phase, round_number
        )
    if rel.startswith("clarification_") and rel.endswith(".md"):
        return _decide_clarification(
            tool_input, events, session_id, agent, phase, round_number
        )
    if rel == "error.md":
        return _decide_error_report(
            content, session_id, agent, phase, round_number
        )
    return _common.decision_payload(
        "deny",
        reason=(
            f"Write path not in outbox contract: {rel}. Allowed: "
            "submission.py, plan_draft.json, reconciliation.json, "
            "clarification_N.md, error.md."
        ),
    )


def main(stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    try:
        payload = _common.read_input(stdin)
    except _common.HookInputError as exc:
        _common.write_decision(
            _common.decision_payload(
                "deny", reason=f"Malformed hook stdin: {exc}"
            ),
            stdout,
        )
        return 0

    tool_name = str(payload.get("tool_name") or "")
    tool_input_raw = payload.get("tool_input")
    tool_input = tool_input_raw if isinstance(tool_input_raw, dict) else {}
    session_id = str(payload.get("session_id") or "")
    agent = _paths.agent() or "claude"
    mode = _paths.mode()
    state = _state_gates.read_state_besteffort()
    round_number = _state_gates.current_round(state)
    phase = _state_gates.current_phase(state) or mode

    if tool_input_raw is not None and not isinstance(tool_input_raw, dict):
        sys.stderr.write(
            f"{_HOOK_NAME} tool_input_coerce: non-dict "
            f"{type(tool_input_raw).__name__} coerced to {{}} "
            f"for tool={tool_name!r}\n"
        )
        _ledger.append_hook_event(
            session_id, agent, "tool_input_coerce", "invalid",
            hook=_HOOK_NAME, tool=tool_name,
            round_number=round_number, phase=phase,
            detail={
                "reason": "non_dict_tool_input",
                "type": type(tool_input_raw).__name__,
            },
        )

    if tool_name not in ALLOWED_TOOLS:
        decision_payload = _common.decision_payload(
            "deny",
            reason=(
                f"Tool {tool_name!r} is disallowed for the Claude "
                f"worker. Allowed tools: {sorted(ALLOWED_TOOLS)}."
            ),
        )
    elif tool_name in ("Read", "Glob", "Grep"):
        decision_payload = _decide_read_like(tool_input, session_id)
    else:
        decision_payload = _decide_write(
            tool_input, session_id, agent, mode, phase, round_number
        )

    hooks_equivalence.maybe_record_shadow(
        session_id=session_id or None,
        tool_name=tool_name,
        tool_input=tool_input,
        payload=decision_payload,
    )
    _common.write_decision(decision_payload, stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
