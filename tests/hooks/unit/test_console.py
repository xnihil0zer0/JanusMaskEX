"""Unit tests for harness.hooks.console (HOOK-12-extract-console).

Pins the public surface of the ConsoleStreamer module so MCP and any future
Claude/Gemini hook entrypoints can import from a single source of truth.
The module under test is `harness.hooks.console`; see
``hooks-implementation-plan.md`` §Phase 1 and
``hooks-implementation-sub-plan-02.md`` §3.2.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr

import pytest

import harness.hooks.console as console_mod
from harness.hooks.console import (
    ConsoleStreamer,
    _C,
    _agent_color,
    _agent_label,
    _code_preview,
    _divider,
    _stream,
)


class TestAnsiPalette:
    def test_C_has_reset(self):
        assert _C.RESET == "\033[0m"

    def test_C_agent_colors_distinct(self):
        assert _C.CLAUDE != _C.GEMINI

    def test_agent_color_claude(self):
        assert _agent_color("claude") == _C.CLAUDE

    def test_agent_color_gemini_and_default(self):
        assert _agent_color("gemini") == _C.GEMINI
        assert _agent_color("anything-else") == _C.GEMINI


class TestLabelAndDivider:
    def test_agent_label_contains_upper_name_and_color(self):
        lbl = _agent_label("claude")
        assert "CLAUDE" in lbl
        assert _C.CLAUDE in lbl
        assert lbl.endswith(_C.RESET)

    def test_divider_uses_default_char_and_width(self):
        d = _divider("claude")
        assert d.count("\u2500") == 60

    def test_divider_custom_char_and_width(self):
        d = _divider("gemini", char="=", width=10)
        assert d.count("=") == 10


class TestCodePreview:
    def test_short_preview_keeps_all_lines(self):
        out = _code_preview("a\nb\nc", max_lines=5)
        assert "a" in out and "b" in out and "c" in out
        assert "more lines" not in out

    def test_truncation_marker(self):
        long_code = "\n".join(f"line{i}" for i in range(20))
        out = _code_preview(long_code, max_lines=3)
        assert "more lines" in out

    def test_line_numbers_right_aligned(self):
        out = _code_preview("only\n")
        assert "  1" in out


class TestStream:
    def test_stream_writes_newline_to_stderr(self):
        buf = io.StringIO()
        with redirect_stderr(buf):
            _stream("hello")
        assert buf.getvalue().endswith("hello\n")


@pytest.fixture
def streamer():
    return ConsoleStreamer("claude", "sess-abc")


class TestConsoleStreamer:
    def test_on_connect_emits_session_id(self, streamer):
        buf = io.StringIO()
        with redirect_stderr(buf):
            streamer.on_connect()
        out = buf.getvalue()
        assert "sess-abc" in out
        assert "CLAUDE" in out

    def test_on_task_read_shows_signature_and_spec(self, streamer):
        task = {
            "task_id": "T-1",
            "specification": "do a thing",
            "constraints": {"function_signature": "def f(x): ..."},
        }
        buf = io.StringIO()
        with redirect_stderr(buf):
            streamer.on_task_read(task)
        out = buf.getvalue()
        assert "T-1" in out and "def f(x): ..." in out and "do a thing" in out

    def test_on_submit_accepted_with_warnings(self, streamer):
        warnings = [{"line": 12, "rule": "naming", "message": "short name"}]
        buf = io.StringIO()
        with redirect_stderr(buf):
            streamer.on_submit_accepted("x=1", 2, 5, 3, warnings)
        out = buf.getvalue()
        assert "SUBMITTED CODE" in out
        assert "[2/5, round 3]" in out
        assert "naming" in out and "short name" in out

    def test_on_submit_accepted_no_warnings_prints_passed(self, streamer):
        buf = io.StringIO()
        with redirect_stderr(buf):
            streamer.on_submit_accepted("x=1", 1, 5, 1, [])
        assert "AST validation: passed" in buf.getvalue()

    def test_on_submit_rejected_truncates_beyond_8(self, streamer):
        violations = [{"line": i, "rule": "r", "message": "m"} for i in range(12)]
        buf = io.StringIO()
        with redirect_stderr(buf):
            streamer.on_submit_rejected("x=1", violations)
        out = buf.getvalue()
        assert "SUBMISSION REJECTED" in out
        assert "and 4 more" in out

    def test_on_submit_rate_limited(self, streamer):
        buf = io.StringIO()
        with redirect_stderr(buf):
            streamer.on_submit_rate_limited(5)
        assert "RATE LIMITED" in buf.getvalue()

    def test_on_clarification_shows_counter(self, streamer):
        buf = io.StringIO()
        with redirect_stderr(buf):
            streamer.on_clarification("why?", 1, 1)
        out = buf.getvalue()
        assert "CLARIFICATION REQUEST" in out
        assert "[#1, 1 remaining]" in out
        assert "why?" in out

    def test_on_error_report_truncates_500(self, streamer):
        long_msg = "x" * 900
        buf = io.StringIO()
        with redirect_stderr(buf):
            streamer.on_error_report(long_msg)
        out = buf.getvalue()
        assert "ERROR REPORT" in out
        assert "x" * 500 in out
        assert "x" * 501 not in out

    def test_on_feedback_retrieved_prints_round(self, streamer):
        feedback = {
            "round": 2,
            "code_under_review": "a\nb\nc",
            "review_prompt": "be thorough",
            "previous_fuzz_failures": [{"input": 1}],
        }
        buf = io.StringIO()
        with redirect_stderr(buf):
            streamer.on_feedback_retrieved(feedback)
        out = buf.getvalue()
        assert "FEEDBACK RETRIEVED" in out and "[round 2]" in out
        assert "be thorough" in out
        assert "fuzz failures shown" in out

    def test_on_feedback_unavailable(self, streamer):
        buf = io.StringIO()
        with redirect_stderr(buf):
            streamer.on_feedback_unavailable("no file")
        assert "feedback unavailable: no file" in buf.getvalue()

    def test_on_input_tools_call_summarizes_keys(self, streamer):
        raw = json.dumps({"code": "print(1)", "explanation": "e"})
        msg = {"id": 7, "method": "tools/call",
               "params": {"arguments": {"command": "submit_code", "args": raw}}}
        buf = io.StringIO()
        with redirect_stderr(buf):
            streamer.on_input(msg)
        out = buf.getvalue()
        assert "submit_code" in out
        assert "code(" in out and "explanation" in out
        assert "id=7" in out

    def test_on_output_accepted_status(self, streamer):
        inner = {"status": "accepted", "ast_valid": True, "warnings": [1, 2]}
        msg = {"id": 9, "result": {"content": [{"text": json.dumps(inner)}]}}
        buf = io.StringIO()
        with redirect_stderr(buf):
            streamer.on_output(msg)
        out = buf.getvalue()
        assert "accepted" in out and "ast=True" in out and "warnings=2" in out

    def test_on_output_error_shape(self, streamer):
        msg = {"id": 1, "error": {"code": -32000, "message": "boom"}}
        buf = io.StringIO()
        with redirect_stderr(buf):
            streamer.on_output(msg)
        assert "error -32000: boom" in buf.getvalue()

    def test_on_output_initialize_shape(self, streamer):
        msg = {"id": 0, "result": {"protocolVersion": "2024-11-05"}}
        buf = io.StringIO()
        with redirect_stderr(buf):
            streamer.on_output(msg)
        assert "initialized" in buf.getvalue()
        assert "v=2024-11-05" in buf.getvalue()

    def test_on_disconnect(self, streamer):
        buf = io.StringIO()
        with redirect_stderr(buf):
            streamer.on_disconnect()
        assert "disconnected" in buf.getvalue()


class TestModuleSurface:
    """Lock the module path so imports can't silently drift back to mcp_server."""

    def test_exports_all_public_symbols(self):
        for name in (
            "_C", "_agent_color", "_agent_label", "_divider",
            "_code_preview", "_stream", "ConsoleStreamer",
        ):
            assert hasattr(console_mod, name), f"missing {name}"

    def test_import_harness_hooks_console_works(self):
        import harness.hooks.console as c
        assert c.ConsoleStreamer is ConsoleStreamer
