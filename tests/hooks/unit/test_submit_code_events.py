"""Unit tests for HOOK-14-track-record-ast-events.

Pins the emit helpers added to harness.hooks.rpc.submit_code:

    emit_ast_rejection(agent, task_id, synthesis_target_type, state_dir=None)
    emit_clean_success(agent, task_id, synthesis_target_type, state_dir=None)

Both call harness.track_record_events.append_hook_event with the canonical
(event_type, book='synthesis', agent, type=synthesis_target_type, task_id,
delta) tuple. Helpers MUST NOT raise on unknown taxonomy — they swallow
EventValidationError so the verb path is never blocked by telemetry hiccups.

See hooks-implementation-plan.md §Phase 1 item 5 and
hooks-implementation-sub-plan-04.md §3.8, §5 step 14.
"""

from __future__ import annotations

import json
import pathlib

import pytest

import harness.hooks.rpc.submit_code as submit_code_mod
from harness.hooks.rpc.submit_code import (
    emit_ast_rejection,
    emit_clean_success,
)


def _read_events(state_dir: pathlib.Path) -> list[dict]:
    path = state_dir / "track_record_events.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


class TestEmitAstRejection:
    def test_appends_row_with_correct_shape(self, tmp_path):
        event = emit_ast_rejection(
            agent="claude",
            task_id="T-1",
            synthesis_target_type="array_transform",
            state_dir=tmp_path,
        )
        assert event is not None
        assert event["event_type"] == "ast_rejection"
        assert event["book"] == "synthesis"
        assert event["agent"] == "claude"
        assert event["type"] == "array_transform"
        assert event["task_id"] == "T-1"
        assert event["delta"] == {"failures": 1, "attempts": 1}

        rows = _read_events(tmp_path)
        assert len(rows) == 1
        assert rows[0]["event_type"] == "ast_rejection"

    def test_unknown_taxonomy_returns_none_without_raising(self, tmp_path):
        # Helpers must NOT break the verb path — swallow EventValidationError.
        out = emit_ast_rejection(
            agent="claude",
            task_id="T-1",
            synthesis_target_type="does_not_exist",
            state_dir=tmp_path,
        )
        assert out is None
        # No row should have been appended.
        assert _read_events(tmp_path) == []

    def test_invalid_agent_returns_none(self, tmp_path):
        out = emit_ast_rejection(
            agent="unknown",
            task_id="T-1",
            synthesis_target_type="array_transform",
            state_dir=tmp_path,
        )
        assert out is None
        assert _read_events(tmp_path) == []


class TestEmitCleanSuccess:
    def test_appends_clean_success_row(self, tmp_path):
        event = emit_clean_success(
            agent="gemini",
            task_id="T-2",
            synthesis_target_type="numerical_computation",
            state_dir=tmp_path,
        )
        assert event is not None
        assert event["event_type"] == "clean_success"
        assert event["book"] == "synthesis"
        assert event["agent"] == "gemini"
        assert event["type"] == "numerical_computation"
        # clean_success never increments failures.
        assert event["delta"] == {"failures": 0, "attempts": 1}

    def test_clean_success_appends_exactly_one_row(self, tmp_path):
        emit_clean_success(
            agent="claude", task_id="T-3",
            synthesis_target_type="string_parsing",
            state_dir=tmp_path,
        )
        rows = _read_events(tmp_path)
        assert len(rows) == 1


class TestRejectionThenSuccessFlow:
    def test_two_events_in_order(self, tmp_path):
        emit_ast_rejection("claude", "T-1", "array_transform", state_dir=tmp_path)
        emit_clean_success("claude", "T-1", "array_transform", state_dir=tmp_path)
        rows = _read_events(tmp_path)
        assert [r["event_type"] for r in rows] == ["ast_rejection", "clean_success"]


class TestModuleSurface:
    def test_helpers_exported(self):
        assert hasattr(submit_code_mod, "emit_ast_rejection")
        assert hasattr(submit_code_mod, "emit_clean_success")

    def test_helpers_callable(self):
        assert callable(submit_code_mod.emit_ast_rejection)
        assert callable(submit_code_mod.emit_clean_success)


class TestIgnoredUnknownTaxonomy:
    """Helpers must not raise for any invalid arg combination — the verb
    path must continue even when telemetry cannot be written."""

    @pytest.mark.parametrize("kwargs", [
        dict(agent="claude",  task_id="T", synthesis_target_type="bogus"),
        dict(agent="martian", task_id="T", synthesis_target_type="array_transform"),
    ])
    def test_emit_ast_rejection_no_raise(self, tmp_path, kwargs):
        assert emit_ast_rejection(state_dir=tmp_path, **kwargs) is None

    @pytest.mark.parametrize("kwargs", [
        dict(agent="claude",  task_id="T", synthesis_target_type="bogus"),
        dict(agent="martian", task_id="T", synthesis_target_type="array_transform"),
    ])
    def test_emit_clean_success_no_raise(self, tmp_path, kwargs):
        assert emit_clean_success(state_dir=tmp_path, **kwargs) is None
