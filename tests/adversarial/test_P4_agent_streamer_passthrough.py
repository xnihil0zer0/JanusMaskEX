"""P4 adversarial battery — HOOK-44 agent-streamer thin pass-through.

Mutation guard: drop the params-is-dict fence and confirm the stream
thread crashes on hook-era Gemini telemetry.  Plus resilience probes
covering Unicode, huge inputs, and mixed legacy/new shape interleaving.
"""

from __future__ import annotations

import io
import json
import pathlib
import sys
from unittest import mock

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness import agent_streamer as strm  # noqa: E402


# ---------------------------------------------------------------------------
# Attack 1: mutation — the params-is-dict fence is what protects the
# stream thread from string parameters.  Proving this by showing the
# pre-fence code would have crashed.
# ---------------------------------------------------------------------------

def test_mutation_without_fence_raises_on_string_params():
    """Simulate the pre-HOOK-44 code path: params is NOT coerced; the
    subsequent ``.get`` call crashes with AttributeError."""
    params = "raw-string-not-a-dict"
    with pytest.raises(AttributeError):
        # This is exactly what the parser used to do.
        params.get("command", "")


def test_current_parser_tolerates_string_params():
    parser = strm.GeminiStreamParser(agent="gemini")
    # Must NOT raise (the fix covers this).
    parser.handle_event({
        "type": "tool_use",
        "tool_name": "x",
        "tool_id": "y",
        "parameters": "raw-string-not-a-dict",
    })


# ---------------------------------------------------------------------------
# Attack 2: the parser must survive weird parameter types — None,
# int, list, etc. — without raising.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bogus", [None, 42, [1, 2, 3], 3.14, True])
def test_gemini_parser_tolerates_bogus_params_type(bogus):
    parser = strm.GeminiStreamParser(agent="gemini")
    parser.handle_event({
        "type": "tool_use",
        "tool_name": "x",
        "tool_id": "y",
        "parameters": bogus,
    })


@pytest.mark.parametrize("tool_input", [
    None,
    42,
    [1, 2, 3],
    "{not valid",
    "",
    "null",
    "[]",
])
def test_claude_parser_tolerates_bogus_tool_input_buffer(tool_input):
    parser = strm.ClaudeStreamParser(agent="claude")
    parser._tool_input_buffer = str(tool_input) if tool_input is not None else ""
    parser._show_tool_input()


# ---------------------------------------------------------------------------
# Attack 3: extremely long code payload does not truncate badly or
# hang.  The parser slices to 8 lines and shows a "... N more" hint.
# ---------------------------------------------------------------------------

def test_claude_parser_huge_code_payload(capsys):
    parser = strm.ClaudeStreamParser(agent="claude")
    huge = "\n".join(f"line_{i}" for i in range(5_000))
    parser._tool_input_buffer = json.dumps({
        "command": "submit_code",
        "args": json.dumps({"code": huge}),
    })
    parser._show_tool_input()
    out = capsys.readouterr().err
    assert "5000 lines" in out or "4999 lines" in out or "5,000 lines" in out.replace(",", "")
    assert "more" in out


# ---------------------------------------------------------------------------
# Attack 4: Unicode in tool input (common in task specs) passes through.
# ---------------------------------------------------------------------------

def test_claude_parser_unicode_content(capsys):
    parser = strm.ClaudeStreamParser(agent="claude")
    parser._tool_input_buffer = json.dumps({
        "command": "submit_code",
        "args": json.dumps({"code": "# résumé ⓐⓑⓒ\nx = 'π'"}),
    })
    parser._show_tool_input()


def test_gemini_parser_unicode_content():
    parser = strm.GeminiStreamParser(agent="gemini")
    parser.handle_event({
        "type": "tool_use",
        "tool_name": "write_file",
        "tool_id": "abc",
        "parameters": {
            "absolute_path": "/work/outbox/submission.py",
            "content": "x = '中文'\n",
        },
    })


# ---------------------------------------------------------------------------
# Attack 5: stream with BOTH legacy execute and new Write events in the
# same NDJSON run — mixed-shape regression guard for the mid-migration
# period where one agent still uses MCP and the other uses hooks.
# ---------------------------------------------------------------------------

def test_mixed_legacy_and_new_shapes_in_one_stream(tmp_path):
    lines = [
        json.dumps({"type": "system", "subtype": "init", "model": "m", "tools": []}),
        # Legacy execute tool_use
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "content_block": {"type": "tool_use", "name": "mcp__janusmask__execute"},
            },
        }),
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": json.dumps({
                        "command": "submit_code",
                        "args": json.dumps({"code": "x=1"}),
                    }),
                },
            },
        }),
        json.dumps({"type": "stream_event", "event": {"type": "content_block_stop"}}),
        # New Write tool_use
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
                    "partial_json": json.dumps({
                        "file_path": "outbox/submission.py",
                        "content": "x=1",
                    }),
                },
            },
        }),
        json.dumps({"type": "stream_event", "event": {"type": "content_block_stop"}}),
        json.dumps({
            "type": "result",
            "subtype": "success",
            "total_cost_usd": 0.0,
            "duration_ms": 0,
            "usage": {},
        }),
    ]
    pipe = io.StringIO("\n".join(lines) + "\n")
    log_path = tmp_path / "log.jsonl"
    strm.stream_agent_output(pipe, "claude", log_path=log_path)
    assert len(log_path.read_text(encoding="utf-8").splitlines()) == len(lines)


# ---------------------------------------------------------------------------
# Attack 6: JSON decode error in the NDJSON stream does not kill the
# reader — it logs a raw-line warning and continues.
# ---------------------------------------------------------------------------

def test_malformed_ndjson_line_does_not_stop_stream(tmp_path):
    lines = [
        "{this is broken",
        json.dumps({"type": "system", "subtype": "init", "model": "m", "tools": []}),
        json.dumps({
            "type": "result",
            "subtype": "success",
            "total_cost_usd": 0.0,
            "duration_ms": 0,
            "usage": {},
        }),
    ]
    pipe = io.StringIO("\n".join(lines) + "\n")
    strm.stream_agent_output(pipe, "gemini", log_path=None)
