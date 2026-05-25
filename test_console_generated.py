# ----- _agent_color -----
import pytest
from harness.hooks.console import _agent_color, _C

def test_agent_color_claude():
    assert _agent_color("claude") == _C.CLAUDE

def test_agent_color_gemini():
    assert _agent_color("gemini") == _C.GEMINI

def test_agent_color_unknown_returns_gemini():
    assert _agent_color("unknown_id") == _C.GEMINI


# ----- _agent_label -----
import pytest
from unittest.mock import patch

from harness.hooks.console import _agent_label
import harness.hooks.console as console_mod


def test_agent_label_formats_correctly():
    with patch.object(console_mod, "_agent_color", return_value="<color>"):
        result = _agent_label("test_agent")
        assert result == f"<color>{console_mod._C.BOLD}TEST_AGENT{console_mod._C.RESET}"


def test_agent_label_uppercase_input():
    with patch.object(console_mod, "_agent_color", return_value="<color>"):
        result = _agent_label("ALREADY_UPPER")
        assert result == f"<color>{console_mod._C.BOLD}ALREADY_UPPER{console_mod._C.RESET}"


def test_agent_label_empty_string():
    with patch.object(console_mod, "_agent_color", return_value="<color>"):
        result = _agent_label("")
        assert result == f"<color>{console_mod._C.BOLD}{console_mod._C.RESET}"


def test_agent_label_numeric_and_special_chars():
    with patch.object(console_mod, "_agent_color", return_value="<color>"):
        result = _agent_label("agent 007!")
        assert result == f"<color>{console_mod._C.BOLD}AGENT 007!{console_mod._C.RESET}"


# ----- _divider -----
import pytest
from harness.hooks.console import _divider

def test_divider_defaults():
    result = _divider("agent1")
    assert isinstance(result, str)
    assert "─" * 60 in result

def test_divider_custom_char():
    result = _divider("agent2", char="=")
    assert isinstance(result, str)
    assert "=" * 60 in result

def test_divider_custom_width():
    result = _divider("agent3", width=25)
    assert isinstance(result, str)
    assert "─" * 25 in result

def test_divider_custom_char_and_width():
    result = _divider("agent4", char="*", width=42)
    assert isinstance(result, str)
    assert "*" * 42 in result

def test_divider_ends_with_reset_if_available():
    import harness.hooks.console as console_mod
    result = _divider("agent5")
    if hasattr(console_mod, "_C") and hasattr(console_mod._C, "RESET"):
        assert result.endswith(console_mod._C.RESET)


# ----- _code_preview -----
import pytest
from harness.hooks.console import _code_preview, _C

def test_code_preview_exact_output():
    code = "a = 1"
    result = _code_preview(code)
    assert result == f"  {_C.MUTED}  1{_C.RESET} {_C.CODE}a = 1{_C.RESET}"

def test_code_preview_basic_formatting():
    code = "print('hello')\nprint('world')"
    expected_line1 = f"  {_C.MUTED}  1{_C.RESET} {_C.CODE}print('hello'){_C.RESET}"
    expected_line2 = f"  {_C.MUTED}  2{_C.RESET} {_C.CODE}print('world'){_C.RESET}"
    
    result = _code_preview(code)
    
    assert expected_line1 in result
    assert expected_line2 in result

def test_code_preview_truncation():
    code = "\n".join(f"line {i}" for i in range(1, 16))
    result = _code_preview(code, max_lines=5)
    
    parts = result.split("\n")
    assert len(parts) == 6
    assert f"line 5{_C.RESET}" in parts[4]
    assert parts[5] == f"  {_C.DIM}... (10 more lines){_C.RESET}"

def test_code_preview_rstrip_removes_trailing_newlines():
    code = "a = 1\n\n\n"
    result = _code_preview(code)
    assert len(result.split("\n")) == 1
    assert "a = 1" in result

def test_code_preview_default_max_lines():
    code = "\n".join(f"line {i}" for i in range(1, 20))
    result = _code_preview(code)
    
    parts = result.split("\n")
    assert len(parts) == 13 # 12 lines + 1 truncation message
    assert f"line 12{_C.RESET}" in parts[11]
    assert parts[12] == f"  {_C.DIM}... (7 more lines){_C.RESET}"

def test_code_preview_empty_string():
    code = ""
    result = _code_preview(code)
    assert result == f"  {_C.MUTED}  1{_C.RESET} {_C.CODE}{_C.RESET}"


# ----- _stream -----
import sys
from unittest.mock import patch

from harness.hooks.console import _stream


def test_stream_writes_to_stderr_and_flushes():
    msg = "Test message for stderr"
    with patch("sys.stderr") as mock_stderr:
        _stream(msg)
        mock_stderr.write.assert_called_once_with("Test message for stderr\n")
        mock_stderr.flush.assert_called_once_with()


def test_stream_handles_empty_string():
    with patch("sys.stderr") as mock_stderr:
        _stream("")
        mock_stderr.write.assert_called_once_with("\n")
        mock_stderr.flush.assert_called_once_with()


# ----- ConsoleStreamer -----
import pytest
from harness.hooks.console import ConsoleStreamer

def test_consolestreamer_init_ConsoleStreamer_assigns_attributes():
    streamer = ConsoleStreamer("agent_1", "session_abc")
    assert streamer.agent_id == "agent_1"
    assert streamer.session_id == "session_abc"

def test_consolestreamer_on_connect_ConsoleStreamer_streams_output(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    streamer.on_connect()
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "agent connected" in output
    assert "session_abc" in output

def test_consolestreamer_on_task_read_ConsoleStreamer_streams_output(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    task = {
        "task_id": "task_123",
        "specification": "Do this",
        "constraints": {"function_signature": "def foo():"}
    }
    streamer.on_task_read(task)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "task_123" in output
    assert "def foo():" in output
    assert "Do this" in output

def test_consolestreamer_on_task_read_ConsoleStreamer_handles_missing_keys(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    task = {"task_id": "task_123"}
    streamer.on_task_read(task)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "task_123" in output

def test_consolestreamer_on_submit_accepted_ConsoleStreamer_streams_output(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    streamer.on_submit_accepted("print('hello')", 1, 3, 2, [{"line": 1, "rule": "W001", "message": "warn"}])
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "SUBMITTED CODE" in output
    assert "1/3, round 2" in output
    assert "W001" in output

def test_consolestreamer_on_submit_accepted_ConsoleStreamer_no_warnings(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    streamer.on_submit_accepted("print('hello')", 1, 3, 2, [])
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "SUBMITTED CODE" in output
    assert "passed (no warnings)" in output

def test_consolestreamer_on_submit_rejected_ConsoleStreamer_streams_output(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    violations = [{"line": 1, "rule": "E001", "message": "error"}] * 10
    streamer.on_submit_rejected("print('bad')", violations)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "SUBMISSION REJECTED" in output
    assert "E001" in output
    assert "and 2 more" in output

def test_consolestreamer_on_submit_rate_limited_ConsoleStreamer_streams_output(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    streamer.on_submit_rate_limited(5)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "RATE LIMITED" in output
    assert "5" in output

def test_consolestreamer_on_clarification_ConsoleStreamer_streams_output(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    streamer.on_clarification("what?", 1, 2)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "CLARIFICATION REQUEST" in output
    assert "what?" in output
    assert "#1, 2 remaining" in output

def test_consolestreamer_on_error_report_ConsoleStreamer_streams_output(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    streamer.on_error_report("something broke")
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "ERROR REPORT" in output
    assert "something broke" in output

def test_consolestreamer_on_feedback_retrieved_ConsoleStreamer_streams_output(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    feedback = {
        "round": 2, 
        "code_under_review": "def f(): pass", 
        "review_prompt": "prompt1", 
        "previous_fuzz_failures": ["f1"]
    }
    streamer.on_feedback_retrieved(feedback)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "FEEDBACK RETRIEVED" in output
    assert "round 2" in output
    assert "prompt1" in output
    assert "1" in output

def test_consolestreamer_on_feedback_retrieved_ConsoleStreamer_no_failures(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    feedback = {"round": 2}
    streamer.on_feedback_retrieved(feedback)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "FEEDBACK RETRIEVED" in output
    assert "round 2" in output

def test_consolestreamer_on_feedback_unavailable_ConsoleStreamer_streams_output(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    streamer.on_feedback_unavailable("network down")
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "feedback unavailable" in output
    assert "network down" in output

def test_consolestreamer_on_input_ConsoleStreamer_tools_call(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    msg = {"method": "tools/call", "id": "1", "params": {"arguments": {"command": "get_task", "args": '{"k": "v"}'}}}
    streamer.on_input(msg)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "IN" in output
    assert "tools/call" in output
    assert "get_task" in output
    assert "k" in output

def test_consolestreamer_on_input_ConsoleStreamer_tools_call_with_code(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    msg = {"method": "tools/call", "id": "2", "params": {"arguments": {"command": "submit", "args": '{"code": "print()"}'}}}
    streamer.on_input(msg)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "code(7ch)" in output

def test_consolestreamer_on_input_ConsoleStreamer_tools_call_missing_args(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    msg = {"method": "tools/call", "id": "1", "params": {"arguments": {}}}
    streamer.on_input(msg)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "tools/call" in output
    assert "?" in output

def test_consolestreamer_on_input_ConsoleStreamer_tools_call_invalid_json(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    msg = {"method": "tools/call", "id": "3", "params": {"arguments": {"command": "get_task", "args": "invalid json"}}}
    streamer.on_input(msg)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "invalid json" in output

def test_consolestreamer_on_input_ConsoleStreamer_long_json_truncation(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    long_str = "A" * 100
    msg = {"method": "tools/call", "id": "3", "params": {"arguments": {"command": "get_task", "args": long_str}}}
    streamer.on_input(msg)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert ("A" * 60) in output
    assert "..." in output

def test_consolestreamer_on_output_ConsoleStreamer_error(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    msg = {"id": "1", "error": {"code": "500", "message": "err1"}}
    streamer.on_output(msg)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "error 500" in output
    assert "err1" in output

def test_consolestreamer_on_output_ConsoleStreamer_content_json(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    msg = {"id": "2", "result": {"content": [{"text": '{"status": "accepted", "ast_valid": true, "violations": [1], "warnings": [2]}'}]}}
    streamer.on_output(msg)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "accepted" in output
    assert "ast=True" in output or "ast=true" in output
    assert "violations=1" in output
    assert "warnings=1" in output

def test_consolestreamer_on_output_ConsoleStreamer_content_json_error(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    msg = {"id": "2", "result": {"isError": True, "content": [{"text": '{"error": "bad thing", "code": "E1"}'}]}}
    streamer.on_output(msg)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "E1:" in output
    assert "bad thing" in output

def test_consolestreamer_on_output_ConsoleStreamer_content_json_error_missing_fields(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    msg = {"id": "2", "result": {"isError": True, "content": [{"text": '{}'}]}}
    streamer.on_output(msg)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "?: ?" in output

def test_consolestreamer_on_output_ConsoleStreamer_content_json_task(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    msg = {"id": "2", "result": {"content": [{"text": '{"task_id": "T1"}'}]}}
    streamer.on_output(msg)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "task=T1" in output

def test_consolestreamer_on_output_ConsoleStreamer_content_json_round(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    msg = {"id": "2", "result": {"content": [{"text": '{"round": 42}'}]}}
    streamer.on_output(msg)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "feedback round=42" in output

def test_consolestreamer_on_output_ConsoleStreamer_protocol_version(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    msg = {"id": "3", "result": {"protocolVersion": "1.0"}}
    streamer.on_output(msg)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "initialized" in output
    assert "v=1.0" in output

def test_consolestreamer_on_output_ConsoleStreamer_tools(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    msg = {"id": "4", "result": {"tools": [{"name": "tool1"}]}}
    streamer.on_output(msg)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "tool1" in output

def test_consolestreamer_on_output_ConsoleStreamer_pong(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    msg = {"id": "5", "result": {}}
    streamer.on_output(msg)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "pong" in output

def test_consolestreamer_on_output_ConsoleStreamer_fallback(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    msg = {"id": "5", "result": {"some_key": "some_value"}}
    streamer.on_output(msg)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "some_key" in output

def test_consolestreamer_on_output_ConsoleStreamer_content_json_invalid(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    msg = {"id": "2", "result": {"content": [{"text": 'invalid json output'}]}}
    streamer.on_output(msg)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "invalid json output" in output

def test_consolestreamer_on_disconnect_ConsoleStreamer_streams_output(capsys):
    streamer = ConsoleStreamer("agent_1", "session_abc")
    streamer.on_disconnect()
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "disconnected" in output
