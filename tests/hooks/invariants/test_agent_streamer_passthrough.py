"""P4 invariant: agent-streamer parsers survive both legacy and
hook-era tool_use shapes (HOOK-44).

Sub-plan 04 §3.10 option (a): keep the execute tool_use wrapper as a
thin pass-through in P4; delete the dead code in P6.  That makes the
parsers' job to accept both shapes without crashing:

  * Legacy MCP: ``{"command": "submit_code", "args": "<json>"}``
  * Hook-era:   Write/Edit tool_use with ``{"file_path": "...",
                "content": "..."}`` (Claude) or write_file/replace with
                ``{"absolute_path": "...", "content": "..."}`` (Gemini)

The parser must log something reasonable for the legacy shape and
gracefully fall through for the new shape.  It must NEVER raise — a
parser exception would kill the stream thread and the orchestrator
would lose all live telemetry.
"""

from __future__ import annotations

import io
import json
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from harness import agent_streamer as strm  # noqa: E402


# ---------------------------------------------------------------------------
# Legacy MCP shape — execute with command/args — regression guard.
# ---------------------------------------------------------------------------

def test_claude_parser_handles_execute_submit_code(capsys):
    parser = strm.ClaudeStreamParser(agent="claude")
    parser._tool_input_buffer = json.dumps(
        {"command": "submit_code", "args": json.dumps({"code": "x = 1\n"})}
    )
    parser._show_tool_input()  # must not raise
    out = capsys.readouterr().err
    assert "command:" in out
    assert "submit_code" in out


def test_gemini_parser_handles_execute_tool_use(capsys):
    parser = strm.GeminiStreamParser(agent="gemini")
    event = {
        "type": "tool_use",
        "tool_name": "mcp__janusmask__execute",
        "tool_id": "abc",
        "parameters": {
            "command": "submit_code",
            "args": json.dumps({"code": "x = 1\n"}),
        },
    }
    parser.handle_event(event)
    out = capsys.readouterr().err
    assert "command:" in out
    assert "submit_code" in out


# ---------------------------------------------------------------------------
# Hook-era shapes — parser must NOT crash even though command/args are
# absent.  Any logging is a nice-to-have, not a hard requirement.
# ---------------------------------------------------------------------------

def test_claude_parser_survives_write_tool_use():
    parser = strm.ClaudeStreamParser(agent="claude")
    parser._tool_input_buffer = json.dumps(
        {"file_path": "outbox/submission.py", "content": "x = 1\n"}
    )
    parser._show_tool_input()  # must not raise


def test_claude_parser_survives_edit_tool_use():
    parser = strm.ClaudeStreamParser(agent="claude")
    parser._tool_input_buffer = json.dumps(
        {
            "file_path": "outbox/submission.py",
            "old_string": "x = 1",
            "new_string": "x = 2",
        }
    )
    parser._show_tool_input()


def test_gemini_parser_survives_write_file_tool_use():
    parser = strm.GeminiStreamParser(agent="gemini")
    event = {
        "type": "tool_use",
        "tool_name": "write_file",
        "tool_id": "abc",
        "parameters": {
            "absolute_path": "/work/outbox/submission.py",
            "content": "x = 1\n",
        },
    }
    parser.handle_event(event)


def test_gemini_parser_survives_replace_tool_use():
    parser = strm.GeminiStreamParser(agent="gemini")
    event = {
        "type": "tool_use",
        "tool_name": "replace",
        "tool_id": "abc",
        "parameters": {
            "absolute_path": "/work/outbox/submission.py",
            "old_string": "x = 1",
            "new_string": "x = 2",
        },
    }
    parser.handle_event(event)


# ---------------------------------------------------------------------------
# Malformed inputs — the parser is a thin pass-through, so it must fail
# soft and keep the stream thread alive.
# ---------------------------------------------------------------------------

def test_claude_parser_tolerates_invalid_json_input():
    parser = strm.ClaudeStreamParser(agent="claude")
    parser._tool_input_buffer = "{not valid json"
    parser._show_tool_input()  # must not raise


def test_claude_parser_tolerates_empty_input():
    parser = strm.ClaudeStreamParser(agent="claude")
    parser._tool_input_buffer = ""
    parser._show_tool_input()


def test_gemini_parser_tolerates_parameters_as_raw_string():
    parser = strm.GeminiStreamParser(agent="gemini")
    parser.handle_event({
        "type": "tool_use",
        "tool_name": "x",
        "tool_id": "y",
        "parameters": "not-a-dict",
    })


def test_gemini_parser_tolerates_args_that_fail_to_parse():
    parser = strm.GeminiStreamParser(agent="gemini")
    parser.handle_event({
        "type": "tool_use",
        "tool_name": "x",
        "tool_id": "y",
        "parameters": {"command": "submit_code", "args": "{not valid"},
    })


# ---------------------------------------------------------------------------
# Full stream read — the happy path keeps working and never raises on a
# mixed-shape log.
# ---------------------------------------------------------------------------

def test_stream_agent_output_mixed_shapes_does_not_raise(tmp_path):
    lines = [
        json.dumps({
            "type": "system",
            "subtype": "init",
            "model": "haiku",
            "tools": [{"name": "Write"}, {"name": "mcp__janusmask__execute"}],
        }),
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "content_block": {"type": "tool_use", "name": "Write"},
            },
        }),
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"file_path": "outbox/submission.py", "content": "x=1"}',
                },
            },
        }),
        json.dumps({
            "type": "stream_event",
            "event": {"type": "content_block_stop"},
        }),
        json.dumps({
            "type": "result",
            "subtype": "success",
            "total_cost_usd": 0.01,
            "duration_ms": 500,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }),
    ]
    pipe = io.StringIO("\n".join(lines) + "\n")
    log_path = tmp_path / "log.jsonl"
    strm.stream_agent_output(pipe, "claude", log_path=log_path)  # must not raise
    assert log_path.is_file()
    # All five NDJSON lines should have been mirrored to the raw log.
    assert len(log_path.read_text(encoding="utf-8").splitlines()) == 5
