"""Adversarial battery for HOOK-12-extract-console.

Mutation-style tests that pin the move of ConsoleStreamer out of mcp_server.py
into harness/hooks/console.py. Any regression that reintroduces the class in
mcp_server.py, breaks the import, or silently diverges the two copies must
cause at least one of these tests to fail.

Coverage axes (sub-plan 02 §3.2, sub-plan 04 §3.10):
    1. Module path — `harness.hooks.console` is the authoritative source.
    2. No duplicate definition inside `harness.mcp_server` source.
    3. Stream target = stderr (MCP's stdio contract — stdout is reserved).
    4. Verb bodies in mcp_server still hit the shared class.
    5. Ordering invariant (sub-plan 04 §4 invariant 6): on_input precedes
       on_output when they fire around a tools/call dispatch.
    6. Rejected-submission path writes a truncation marker when violations
       exceed the 8-item ceiling (line-level behaviour pinned).
"""

from __future__ import annotations

import io
import json
import pathlib
import sys
from contextlib import redirect_stderr

import pytest

import harness.hooks.console as console_mod
import harness.mcp_server as mcp_mod
from harness.hooks.console import ConsoleStreamer


REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


class TestModulePath:
    def test_mcp_imports_from_hooks_console(self):
        assert mcp_mod.ConsoleStreamer is console_mod.ConsoleStreamer
        assert mcp_mod._C is console_mod._C
        assert mcp_mod._stream is console_mod._stream
        assert mcp_mod._agent_label is console_mod._agent_label
        assert mcp_mod._agent_color is console_mod._agent_color
        assert mcp_mod._divider is console_mod._divider
        assert mcp_mod._code_preview is console_mod._code_preview

    def test_console_module_path_is_hooks(self):
        # The canonical module path must be harness.hooks.console.
        assert ConsoleStreamer.__module__ == "harness.hooks.console"

    def test_mcp_source_has_no_local_console_class(self):
        src = (REPO_ROOT / "harness" / "mcp_server.py").read_text(encoding="utf-8")
        # The `class ConsoleStreamer` line must only appear as the import form,
        # never as a class definition.
        assert "\nclass ConsoleStreamer" not in src, (
            "ConsoleStreamer must not be redefined in mcp_server.py. It lives in "
            "harness.hooks.console per HOOK-12."
        )

    def test_mcp_source_has_no_local_C_palette(self):
        src = (REPO_ROOT / "harness" / "mcp_server.py").read_text(encoding="utf-8")
        assert "\nclass _C:" not in src, (
            "ANSI palette must not be redefined in mcp_server.py."
        )


class TestStdoutStderrContract:
    def test_stream_writes_to_stderr_only(self):
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        saved_out, saved_err = sys.stdout, sys.stderr
        try:
            sys.stdout, sys.stderr = out_buf, err_buf
            console_mod._stream("hello")
        finally:
            sys.stdout, sys.stderr = saved_out, saved_err
        assert out_buf.getvalue() == "", "MCP stdio contract: stdout reserved for JSON-RPC"
        assert err_buf.getvalue() == "hello\n"


class TestVerbOrderingInvariant:
    """Mirrors sub-plan 04 §4 invariant 6 — on_input fires before on_output."""

    def test_on_input_then_on_output_sequence(self):
        streamer = ConsoleStreamer("claude", "s1")
        buf = io.StringIO()
        with redirect_stderr(buf):
            streamer.on_input({"id": 1, "method": "tools/call",
                               "params": {"arguments": {"command": "submit_code"}}})
            streamer.on_output({"id": 1, "result":
                {"content": [{"text": json.dumps({"status": "accepted", "ast_valid": True})}]}})
        out = buf.getvalue()
        in_pos = out.find("IN")
        out_pos = out.find("OUT")
        assert in_pos != -1 and out_pos != -1, f"got: {out!r}"
        assert in_pos < out_pos, "on_input must precede on_output in emitted stream"


class TestRejectionTruncation:
    def test_truncation_marker_appears_for_large_violation_list(self):
        streamer = ConsoleStreamer("gemini", "s2")
        violations = [{"line": i, "rule": "x", "message": "bad"} for i in range(25)]
        buf = io.StringIO()
        with redirect_stderr(buf):
            streamer.on_submit_rejected("y=1", violations)
        out = buf.getvalue()
        # Exactly 8 violations should be printed in detail; the rest summarized.
        assert "and 17 more" in out
        assert "SUBMISSION REJECTED" in out


class TestSubmitAcceptedContract:
    def test_submission_counter_appears_in_accepted_message(self):
        streamer = ConsoleStreamer("claude", "s3")
        buf = io.StringIO()
        with redirect_stderr(buf):
            streamer.on_submit_accepted("z=0", 3, 5, 2, [])
        assert "[3/5, round 2]" in buf.getvalue()


class TestMcpServerReuse:
    """Ensure the MCP JanusMaskServer still wires to the shared streamer."""

    def test_janusmask_server_instantiates_streamer(self, tmp_path, monkeypatch):
        # Avoid touching real state/logs on module import.
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        # on_connect runs in __init__; capture stderr to keep the suite quiet.
        with redirect_stderr(io.StringIO()):
            srv = mcp_mod.JanusMaskServer("claude", tmp_path)
        assert isinstance(srv._console, ConsoleStreamer)
        assert srv._console.agent_id == "claude"


@pytest.mark.parametrize("agent,expected_color", [
    ("claude", console_mod._C.CLAUDE),
    ("gemini", console_mod._C.GEMINI),
    ("other",  console_mod._C.GEMINI),  # default branch
])
def test_agent_color_mapping_stable(agent, expected_color):
    assert console_mod._agent_color(agent) == expected_color
