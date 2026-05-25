"""Unit tests for harness.hooks._decide_common (T2-4 Gate 3 partner).

The shared decider module is dispatched from both
harness.hooks.claude.pre_tool and harness.hooks.gemini.pre_tool via
thin wrappers. These tests exercise the shared primitives directly
with a stub DeciderContext so agent-side envelope differences are
isolated from decision-logic behaviour.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

import harness.hooks._decide_common as decide_common
from harness.hooks._decide_common import DeciderContext


class _JournalRecorder:
    """Collects (verb, outcome, detail) tuples for assertion."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def __call__(
        self,
        verb: str,
        outcome: str,
        *,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.calls.append((verb, outcome, detail))


def _make_ctx(
    *,
    agent: str = "claude",
    phase: str = "synthesis",
    round_number: int = 1,
    allow_with_warnings=None,
) -> tuple[DeciderContext, _JournalRecorder, list[list[dict[str, Any]]]]:
    journal = _JournalRecorder()
    warning_calls: list[list[dict[str, Any]]] = []

    def _default_allow_with_warnings(warnings):
        warning_calls.append(warnings)
        return {"decision": "allow", "marker": "with-warnings"}

    ctx = DeciderContext(
        session_id="sess",
        agent=agent,
        phase=phase,
        round_number=round_number,
        journal=journal,
        allow_with_warnings=allow_with_warnings or _default_allow_with_warnings,
    )
    return ctx, journal, warning_calls


def _stage_state(tmp_path, monkeypatch):
    """Minimal JANUSMASK state_dir for tests that read rpc state."""
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_AGENT", "claude")
    return state


# ---------- format helpers ----------


class TestFormatHelpers:
    def test_ast_reason_with_violations(self):
        payload = {
            "error": "bad",
            "violations": [
                {"line": 3, "rule": "R1", "message": "nope"},
                {"line": 7, "rule": "R2", "message": "also nope"},
            ],
        }
        out = decide_common.format_ast_reason(payload)
        assert out.startswith("bad\n")
        assert "- L3: [R1] nope" in out
        assert "- L7: [R2] also nope" in out

    def test_ast_reason_falls_back_to_message(self):
        assert decide_common.format_ast_reason(
            {"message": "fallback"}
        ) == "fallback"

    def test_ast_reason_default_header_no_violations(self):
        assert decide_common.format_ast_reason({}) == "AST validation failed."

    def test_plan_reason_with_violations(self):
        payload = {
            "error": "plan bad",
            "violations": [
                {"code": "C1", "path": "$.x", "message": "m1"},
            ],
        }
        out = decide_common.format_plan_reason(payload)
        assert out.startswith("plan bad\n")
        assert "- [C1] $.x: m1" in out

    def test_plan_reason_default_header(self):
        assert (
            decide_common.format_plan_reason({})
            == "plan_draft validation failed."
        )


# ---------- decide_submission ----------


class TestDecideSubmission:
    def _write_task(self, inbox: pathlib.Path, *, deterministic=True):
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / "task.json").write_text(
            json.dumps({
                "task_id": "T1",
                "synthesis_target_type": "pure_function",
                "constraints": {"deterministic": deterministic},
            })
        )

    def test_rate_limited_denies_and_journals(self, tmp_path, monkeypatch):
        _stage_state(tmp_path, monkeypatch)
        from harness.hooks import _state_gates
        ctx, journal, _ = _make_ctx()
        inbox = tmp_path / "inbox"
        self._write_task(inbox)
        events = [
            {"verb": "submit_code", "outcome": "allow"}
            for _ in range(_state_gates.MAX_SUBMISSIONS)
        ]
        out = decide_common.decide_submission(ctx, "x = 1\n", events, inbox)
        assert out["decision"] == "deny"
        assert "rate limit" in out["reason"].lower()
        assert journal.calls == [(
            "submit_code",
            "rate_limited",
            {
                "reason": out["reason"],
                "counters": {"submissions": _state_gates.MAX_SUBMISSIONS},
            },
        )]

    def test_ast_errors_deny_and_journal(self, tmp_path, monkeypatch):
        _stage_state(tmp_path, monkeypatch)
        ctx, journal, _ = _make_ctx()
        inbox = tmp_path / "inbox"
        self._write_task(inbox)
        bad_code = "def bad(:\n    x = y\n"
        out = decide_common.decide_submission(ctx, bad_code, [], inbox)
        assert out["decision"] == "deny"
        assert journal.calls
        verb, outcome, detail = journal.calls[0]
        assert (verb, outcome) == ("submit_code", "deny")
        assert detail["error_count"] >= 1
        assert detail["task_id"] == "T1"

    def test_clean_code_allows_no_journal(self, tmp_path, monkeypatch):
        _stage_state(tmp_path, monkeypatch)
        ctx, journal, warning_calls = _make_ctx()
        inbox = tmp_path / "inbox"
        self._write_task(inbox)
        out = decide_common.decide_submission(
            ctx, "def add(a, b):\n    return a + b\n", [], inbox,
        )
        assert out == {"decision": "allow"}
        assert journal.calls == []
        assert warning_calls == []

    def test_warnings_route_through_allow_with_warnings(
        self, tmp_path, monkeypatch
    ):
        _stage_state(tmp_path, monkeypatch)
        ctx, journal, warning_calls = _make_ctx()
        inbox = tmp_path / "inbox"
        self._write_task(inbox)
        # Stub warnings_from_violations so the happy branch routes a
        # non-empty list into allow_with_warnings regardless of what the
        # real AST validator returns for trivially-valid code.
        original = decide_common.rpc_submit_code.warnings_from_violations
        decide_common.rpc_submit_code.warnings_from_violations = lambda _v: [
            {"line": 1, "rule": "R", "message": "warn"}
        ]
        try:
            out = decide_common.decide_submission(
                ctx, "def f():\n    return 1\n", [], inbox,
            )
        finally:
            decide_common.rpc_submit_code.warnings_from_violations = original
        assert warning_calls == [[{"line": 1, "rule": "R", "message": "warn"}]]
        assert out == {"decision": "allow", "marker": "with-warnings"}
        assert journal.calls == []


# ---------- decide_plan_draft ----------


class TestDecidePlanDraft:
    def test_single_shot_denies(self):
        ctx, journal, _ = _make_ctx()
        events = [{"verb": "plan_draft", "outcome": "allow"}]
        out = decide_common.decide_plan_draft(ctx, "{}", events)
        assert out["decision"] == "deny"
        assert "single-shot" in out["reason"]
        assert journal.calls[0][:2] == ("plan_draft", "deny")

    def test_invalid_json_denies(self):
        ctx, journal, _ = _make_ctx()
        out = decide_common.decide_plan_draft(ctx, "{not json", [])
        assert out["decision"] == "deny"
        assert "valid JSON" in out["reason"]
        assert journal.calls[0][:2] == ("plan_draft", "invalid")

    def test_validation_violations_denies(self, tmp_path, monkeypatch):
        _stage_state(tmp_path, monkeypatch)
        ctx, journal, _ = _make_ctx()
        fake_violations = [
            {"code": "C1", "path": "$.x", "message": "m"},
            {"code": "C2", "path": "$.y", "message": "n"},
        ]
        original_validate = decide_common.rpc_submit_plan_draft.validate
        original_rejected = decide_common.rpc_submit_plan_draft.rejected_payload
        decide_common.rpc_submit_plan_draft.validate = (
            lambda parsed: fake_violations
        )
        decide_common.rpc_submit_plan_draft.rejected_payload = (
            lambda violations, *, max_show: {
                "error": "plan_draft validation failed.",
                "violations": violations,
            }
        )
        try:
            out = decide_common.decide_plan_draft(ctx, json.dumps({}), [])
        finally:
            decide_common.rpc_submit_plan_draft.validate = original_validate
            decide_common.rpc_submit_plan_draft.rejected_payload = (
                original_rejected
            )
        assert out["decision"] == "deny"
        assert "[C1] $.x: m" in out["reason"]
        assert journal.calls[0][0] == "plan_draft"
        assert journal.calls[0][1] == "deny"
        assert journal.calls[0][2] == {"violation_count": 2}

    def test_happy_path_allows(self, tmp_path, monkeypatch):
        ctx, journal, _ = _make_ctx()
        original = decide_common.rpc_submit_plan_draft.validate
        decide_common.rpc_submit_plan_draft.validate = lambda parsed: []
        try:
            out = decide_common.decide_plan_draft(ctx, json.dumps({}), [])
        finally:
            decide_common.rpc_submit_plan_draft.validate = original
        assert out == {"decision": "allow"}
        assert journal.calls == []


# ---------- decide_reconciliation ----------


class TestDecideReconciliation:
    def test_single_shot_denies(self):
        ctx, journal, _ = _make_ctx()
        events = [{"verb": "reconciliation", "outcome": "allow"}]
        out = decide_common.decide_reconciliation(ctx, "{}", events)
        assert out["decision"] == "deny"
        assert "single-shot" in out["reason"]
        assert journal.calls[0][:2] == ("reconciliation", "deny")

    def test_invalid_json_denies(self):
        ctx, journal, _ = _make_ctx()
        out = decide_common.decide_reconciliation(ctx, "not json", [])
        assert out["decision"] == "deny"
        assert journal.calls[0][:2] == ("reconciliation", "invalid")

    def test_happy_path_allows(self, tmp_path, monkeypatch):
        _stage_state(tmp_path, monkeypatch)
        ctx, journal, _ = _make_ctx()
        mod = decide_common.rpc_submit_reconciliation
        original_ids = mod.load_valid_diff_ids
        original_validate = mod.validate_responses
        mod.load_valid_diff_ids = lambda _sd: set()
        mod.validate_responses = lambda responses, *, valid_ids: None
        try:
            out = decide_common.decide_reconciliation(
                ctx, json.dumps({"responses": []}), [],
            )
        finally:
            mod.load_valid_diff_ids = original_ids
            mod.validate_responses = original_validate
        assert out == {"decision": "allow"}
        assert journal.calls == []


# ---------- decide_error_report ----------


class TestDecideErrorReport:
    def test_oversize_denies_and_journals(self):
        ctx, journal, _ = _make_ctx()
        big = "x" * (decide_common.ERROR_MAX_BYTES + 1)
        out = decide_common.decide_error_report(ctx, big)
        assert out["decision"] == "deny"
        assert "64 KB cap" in out["reason"]
        assert journal.calls[0][:2] == ("error", "deny")
        assert journal.calls[0][2]["size"] == len(big)

    def test_within_cap_allows_no_journal(self):
        ctx, journal, _ = _make_ctx()
        out = decide_common.decide_error_report(ctx, "short error")
        assert out == {"decision": "allow"}
        assert journal.calls == []


# ---------- decide_read_like ----------


class TestDecideReadLike:
    def test_empty_path_allows(self):
        out = decide_common.decide_read_like(
            {}, [pathlib.Path("/tmp")],
            path_keys=("file_path", "path"),
            tool_name_for_reason="Read/Glob/Grep",
        )
        assert out == {"decision": "allow"}

    def test_path_under_root_allows(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        target = root / "inside.txt"
        out = decide_common.decide_read_like(
            {"file_path": str(target)}, [root],
            path_keys=("file_path", "path"),
            tool_name_for_reason="Read/Glob/Grep",
        )
        assert out == {"decision": "allow"}

    def test_path_outside_root_denies(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside" / "x.txt"
        outside.parent.mkdir()
        out = decide_common.decide_read_like(
            {"file_path": str(outside)}, [root],
            path_keys=("file_path", "path"),
            tool_name_for_reason="Read/Glob/Grep",
        )
        assert out["decision"] == "deny"
        assert "Read/Glob/Grep path outside allowed roots" in out["reason"]
        assert str(outside) in out["reason"]

    def test_gemini_tool_name_in_reason(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside" / "x.txt"
        outside.parent.mkdir()
        out = decide_common.decide_read_like(
            {"absolute_path": str(outside)}, [root],
            path_keys=("absolute_path", "file_path", "path"),
            tool_name_for_reason="read_file/list_directory/grep_search/glob",
        )
        assert out["decision"] == "deny"
        assert (
            "read_file/list_directory/grep_search/glob path outside"
            in out["reason"]
        )

    def test_path_keys_priority_order(self, tmp_path):
        """path_keys tuple determines which field wins when multiple
        candidates are present. Gemini reads absolute_path first so that
        its native tools (which emit absolute_path) get checked ahead of
        fallback keys."""
        root = tmp_path / "root"
        root.mkdir()
        inside = root / "inside.txt"
        outside = tmp_path / "outside" / "x.txt"
        outside.parent.mkdir()
        out_gemini = decide_common.decide_read_like(
            {"absolute_path": str(outside), "file_path": str(inside)},
            [root],
            path_keys=("absolute_path", "file_path", "path"),
            tool_name_for_reason="read_file/list_directory/grep_search/glob",
        )
        assert out_gemini["decision"] == "deny"
        out_claude = decide_common.decide_read_like(
            {"absolute_path": str(outside), "file_path": str(inside)},
            [root],
            path_keys=("file_path", "path"),
            tool_name_for_reason="Read/Glob/Grep",
        )
        assert out_claude["decision"] == "allow"


# ---------- DeciderContext dataclass ----------


class TestDeciderContext:
    def test_frozen_dataclass_rejects_mutation(self):
        ctx, _, _ = _make_ctx()
        with pytest.raises(Exception):
            ctx.session_id = "other"  # type: ignore[misc]

    def test_callables_are_used(self):
        ctx, journal, warning_calls = _make_ctx()
        ctx.journal("verb", "outcome", detail={"k": 1})
        assert journal.calls == [("verb", "outcome", {"k": 1})]
        result = ctx.allow_with_warnings(
            [{"line": 1, "rule": "R", "message": "m"}]
        )
        assert result == {"decision": "allow", "marker": "with-warnings"}
