"""P4 corrections M12 — streamer-ordering invariant (sub-plan 03 §Proposed 3).

The original invariant-6 test at
``tests/hooks/invariants/test_nine_invariants.py:233-254`` only asserts
that the per-session ledger preserves append order.  Plan §4
invariant 6 is actually about a different surface: for any single
tool_use/tool_result pair streaming through ``agent_streamer``, the
``_out(...)`` console sink must emit events in the order
``on_input → dispatch → on_output``.  A future refactor that buffered
events or reordered them would silently desynchronise live operator
telemetry from the ledger.

This file drives a recorded NDJSON trace through both
``ClaudeStreamParser`` and ``GeminiStreamParser``, monkey-patching
``_out`` to capture the call sequence, then asserts:

  * the ``tool_use:`` header for a tool call is emitted before any
    ``_show_tool_input`` / ``_on_tool_use`` dispatch bodies
    (``command:``, ``code:``, keyed args);
  * all of those dispatch lines appear before the corresponding
    ``tool_result`` output.

Mutation / negative assertions confirm the positive tests would catch
a reorder.

Precedent: ``test_stream_agent_output_mixed_shapes_does_not_raise`` in
``tests/hooks/invariants/test_agent_streamer_passthrough.py`` —
same NDJSON-trace fixture pattern.
"""

from __future__ import annotations

import io
import json
import pathlib
import sys
from typing import List

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from harness import agent_streamer as strm  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def capture_out(monkeypatch):
    """Replace ``agent_streamer._out`` with a call-recorder.

    Returns the list that each ``_out(msg)`` call appends ``msg`` to, in
    order.  Any reorder of parser emissions immediately shows up as a
    positional mismatch in that list.
    """
    calls: List[str] = []

    def _recorder(msg: str) -> None:
        calls.append(msg)

    monkeypatch.setattr(strm, "_out", _recorder)
    return calls


def _index_of_substring(calls: List[str], needle: str) -> int:
    for i, msg in enumerate(calls):
        if needle in msg:
            return i
    raise AssertionError(
        f"expected {needle!r} somewhere in _out log; got {calls!r}"
    )


# ---------------------------------------------------------------------------
# Claude parser — tool_use:<hdr> -> dispatch body -> tool_result
# ---------------------------------------------------------------------------


def _claude_trace_tool_use_then_result() -> List[str]:
    """Mimic the Claude NDJSON wire: tool_use header, input_json_delta
    with command/args, content_block_stop, then a `user` event carrying
    a tool_result."""
    return [
        json.dumps({
            "type": "system",
            "subtype": "init",
            "model": "haiku",
            "tools": [{"name": "mcp__janusmask__execute"}],
        }),
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "content_block": {
                    "type": "tool_use",
                    "name": "mcp__janusmask__execute",
                },
            },
        }),
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": json.dumps(
                        {
                            "command": "submit_code",
                            "args": json.dumps({"code": "x = 1\n"}),
                        }
                    ),
                },
            },
        }),
        json.dumps({
            "type": "stream_event",
            "event": {"type": "content_block_stop"},
        }),
        json.dumps({
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tu-abc123456789",
                        "is_error": False,
                        "content": json.dumps({"status": "accepted"}),
                    }
                ]
            },
        }),
        json.dumps({
            "type": "result",
            "subtype": "success",
            "total_cost_usd": 0.01,
            "duration_ms": 500,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }),
    ]


def test_claude_on_input_before_dispatch_before_on_output(capture_out, tmp_path):
    """Positive: for one Claude tool_use/tool_result pair, ``_out`` calls
    appear in the order: tool_use header (on_input), command: /code:
    dispatch, tool_result (on_output)."""
    pipe = io.StringIO("\n".join(_claude_trace_tool_use_then_result()) + "\n")
    strm.stream_agent_output(pipe, "claude", log_path=tmp_path / "raw.jsonl")

    # tool_use header = on_input; command/code dispatch = dispatch body;
    # tool_result [OK|ERROR] = on_output.
    idx_input = _index_of_substring(capture_out, "tool_use:")
    idx_dispatch = _index_of_substring(capture_out, "command:")
    idx_output = _index_of_substring(capture_out, "tool_result")

    assert idx_input < idx_dispatch, (
        "tool_use header must be emitted before the dispatch body. "
        f"Got order: input={idx_input}, dispatch={idx_dispatch}. "
        f"Log: {capture_out!r}"
    )
    assert idx_dispatch < idx_output, (
        "dispatch body must be emitted before the tool_result. "
        f"Got order: dispatch={idx_dispatch}, output={idx_output}. "
        f"Log: {capture_out!r}"
    )


def test_claude_dispatch_body_follows_input_completion(capture_out):
    """The ``command:`` dispatch line MUST only appear after
    ``content_block_stop`` — i.e. the input buffer has been fully
    accumulated before ``_show_tool_input`` runs.  Delivery ordering
    guard against an over-eager streamer that flushes on every delta.
    """
    parser = strm.ClaudeStreamParser(agent="claude")

    # Simulate a partial delta arriving first.  Before content_block_stop
    # nothing should be dispatched.
    parser.handle_event({
        "type": "stream_event",
        "event": {
            "type": "content_block_start",
            "content_block": {
                "type": "tool_use",
                "name": "mcp__janusmask__execute",
            },
        },
    })
    # At this point the header should have been emitted.
    assert any("tool_use:" in m for m in capture_out)
    pre_delta = list(capture_out)

    parser.handle_event({
        "type": "stream_event",
        "event": {
            "type": "content_block_delta",
            "delta": {
                "type": "input_json_delta",
                "partial_json": json.dumps({"command": "submit_code", "args": ""}),
            },
        },
    })
    # Deltas must NOT trigger a dispatch emission on their own.
    assert capture_out == pre_delta, (
        "input_json_delta handling leaked _out() calls before the "
        "content_block_stop finaliser — the stream has been torn out of "
        "on_input/dispatch/on_output ordering."
    )

    parser.handle_event({
        "type": "stream_event",
        "event": {"type": "content_block_stop"},
    })
    assert any("command:" in m for m in capture_out), (
        "content_block_stop must finalise the tool_use by dispatching"
        " _show_tool_input — the command: line was never emitted."
    )


def test_claude_mutation_reordered_trace_breaks_ordering(capture_out):
    """Mutation: if a caller delivers the trace out of order
    (tool_result arriving BEFORE the tool_use finaliser), the captured
    log no longer satisfies ``on_input < dispatch < on_output``.
    Confirms the positive test is discriminating."""
    parser = strm.ClaudeStreamParser(agent="claude")
    # Result first — simulates a reordered shim.
    parser.handle_event({
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tu-early",
                    "is_error": False,
                    "content": "{}",
                }
            ]
        },
    })
    parser.handle_event({
        "type": "stream_event",
        "event": {
            "type": "content_block_start",
            "content_block": {
                "type": "tool_use",
                "name": "mcp__janusmask__execute",
            },
        },
    })
    parser._tool_input_buffer = json.dumps(
        {"command": "submit_code", "args": ""}
    )
    parser.handle_event({
        "type": "stream_event",
        "event": {"type": "content_block_stop"},
    })

    idx_output = _index_of_substring(capture_out, "tool_result")
    idx_input = _index_of_substring(capture_out, "tool_use:")
    # Under the reorder, output precedes input — the positive test's
    # ``input < output`` assertion would fail on a log like this.
    assert idx_output < idx_input


# ---------------------------------------------------------------------------
# Gemini parser — symmetric assertion.  _on_tool_use emits the header
# AND the command/args dispatch together, then a later tool_result
# event drives _on_tool_result.
# ---------------------------------------------------------------------------


def test_gemini_on_tool_use_header_before_dispatch_before_result(capture_out):
    parser = strm.GeminiStreamParser(agent="gemini")
    parser.handle_event({
        "type": "tool_use",
        "tool_name": "mcp__janusmask__execute",
        "tool_id": "gtu-xyz",
        "parameters": {
            "command": "submit_code",
            "args": json.dumps({"code": "def f(): return 1\n"}),
        },
    })
    parser.handle_event({
        "type": "tool_result",
        "tool_id": "gtu-xyz",
        "status": "ok",
        "output": json.dumps({"status": "accepted"}),
    })

    idx_input = _index_of_substring(capture_out, "tool_use:")
    idx_dispatch = _index_of_substring(capture_out, "command:")
    idx_output = _index_of_substring(capture_out, "tool_result")

    assert idx_input < idx_dispatch < idx_output, (
        f"Gemini streamer reordered on_input/dispatch/on_output: "
        f"input={idx_input}, dispatch={idx_dispatch}, output={idx_output}. "
        f"Log: {capture_out!r}"
    )


def test_gemini_mutation_result_before_use_breaks_ordering(capture_out):
    parser = strm.GeminiStreamParser(agent="gemini")
    # Result arriving first.
    parser.handle_event({
        "type": "tool_result",
        "tool_id": "gtu-early",
        "status": "ok",
        "output": "",
    })
    parser.handle_event({
        "type": "tool_use",
        "tool_name": "mcp__janusmask__execute",
        "tool_id": "gtu-xyz",
        "parameters": {"command": "submit_code", "args": ""},
    })
    idx_output = _index_of_substring(capture_out, "tool_result")
    idx_input = _index_of_substring(capture_out, "tool_use:")
    assert idx_output < idx_input, (
        "Mutation check: result-before-use should invert the ordering. "
        "If this inequality fails, the positive ordering test would no "
        "longer be discriminating."
    )


# ---------------------------------------------------------------------------
# Full stream — ordering holds across two back-to-back pairs in one
# NDJSON log (the typical cross_examination turn: submit_code then
# clarification_N).
# ---------------------------------------------------------------------------


def test_claude_ordering_stable_across_multiple_pairs(capture_out, tmp_path):
    """Two sequential tool_use/tool_result pairs in one stream; the
    ordering invariant must hold for each pair independently and the
    two pairs must be temporally disjoint (pair1 completes before pair2
    starts).
    """
    def _pair(partial_json: str, tool_use_id: str) -> list[str]:
        return [
            json.dumps({
                "type": "stream_event",
                "event": {
                    "type": "content_block_start",
                    "content_block": {
                        "type": "tool_use",
                        "name": "mcp__janusmask__execute",
                    },
                },
            }),
            json.dumps({
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": partial_json,
                    },
                },
            }),
            json.dumps({
                "type": "stream_event",
                "event": {"type": "content_block_stop"},
            }),
            json.dumps({
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "is_error": False,
                            "content": json.dumps({"status": "accepted"}),
                        }
                    ]
                },
            }),
        ]

    lines: list[str] = [
        json.dumps({
            "type": "system",
            "subtype": "init",
            "model": "haiku",
            "tools": [{"name": "mcp__janusmask__execute"}],
        })
    ]
    lines += _pair(
        json.dumps({"command": "submit_code", "args": ""}),
        "tu-first-123",
    )
    lines += _pair(
        json.dumps({"command": "clarification", "args": ""}),
        "tu-second-456",
    )
    lines.append(
        json.dumps({
            "type": "result",
            "subtype": "success",
            "total_cost_usd": 0.01,
            "duration_ms": 500,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        })
    )

    pipe = io.StringIO("\n".join(lines) + "\n")
    strm.stream_agent_output(pipe, "claude", log_path=tmp_path / "raw.jsonl")

    # Locate both command: emissions — one per pair.
    command_lines = [i for i, m in enumerate(capture_out) if "command:" in m]
    assert len(command_lines) == 2, (
        f"Expected two command: dispatch lines, got {len(command_lines)}. "
        f"Log: {capture_out!r}"
    )

    # Two tool_use headers and two tool_result lines.
    tu_heads = [i for i, m in enumerate(capture_out) if "tool_use:" in m]
    tr_lines = [i for i, m in enumerate(capture_out) if "tool_result" in m]
    assert len(tu_heads) == 2 and len(tr_lines) == 2

    # Each pair satisfies input<dispatch<output independently.
    for pair_idx, (hdr, dispatch, out) in enumerate(
        zip(tu_heads, command_lines, tr_lines)
    ):
        assert hdr < dispatch < out, (
            f"Pair {pair_idx} out of order: "
            f"header={hdr}, dispatch={dispatch}, output={out}"
        )

    # Pairs do not interleave: pair1's tool_result precedes pair2's
    # tool_use header.
    assert tr_lines[0] < tu_heads[1], (
        "pair1 tool_result should finish before pair2 tool_use begins; "
        f"got pair1_out={tr_lines[0]}, pair2_in={tu_heads[1]}."
    )
