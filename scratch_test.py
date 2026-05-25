from __future__ import annotations
import io
import sys
import pytest
from harness.hooks._common import read_input, HookInputError

def test_read_input_parses_json_object_from_stream():
    stream = io.StringIO('{"event": "PreToolUse", "tool": "Bash"}')
    result = read_input(stream)
    assert result == {"event": "PreToolUse", "tool": "Bash"}
    assert isinstance(result, dict)

def test_read_input_parses_nested_json_object():
    payload = '{"outer": {"inner": [1, 2, 3], "flag": true}, "n": 5}'
    stream = io.StringIO(payload)
    result = read_input(stream)
    assert result == {"outer": {"inner": [1, 2, 3], "flag": True}, "n": 5}

def test_read_input_empty_string_returns_empty_dict():
    result = read_input(io.StringIO(""))
    assert result == {}

def test_read_input_whitespace_only_returns_empty_dict():
    result = read_input(io.StringIO("   \n\t  \r\n "))
    assert result == {}

def test_read_input_empty_object_returns_empty_dict():
    # A real (parsed) empty JSON object, distinct from the empty-stream path.
    result = read_input(io.StringIO("{}"))
    assert result == {}

def test_read_input_invalid_json_raises_hookinputerror():
    with pytest.raises(HookInputError):
        read_input(io.StringIO("{not valid json"))

def test_read_input_invalid_json_message_mentions_json():
    with pytest.raises(HookInputError) as excinfo:
        read_input(io.StringIO("{broken"))
    assert "JSON" in str(excinfo.value)

def test_read_input_json_list_raises_hookinputerror():
    with pytest.raises(HookInputError) as excinfo:
        read_input(io.StringIO("[1, 2, 3]"))
    assert "list" in str(excinfo.value)

def test_read_input_json_number_raises_hookinputerror():
    with pytest.raises(HookInputError) as excinfo:
        read_input(io.StringIO("42"))
    assert "int" in str(excinfo.value)

def test_read_input_json_string_raises_hookinputerror():
    with pytest.raises(HookInputError) as excinfo:
        read_input(io.StringIO('"just a string"'))
    assert "str" in str(excinfo.value)

def test_read_input_non_dict_error_message_reports_type_name():
    with pytest.raises(HookInputError) as excinfo:
        read_input(io.StringIO("[]"))
    msg = str(excinfo.value)
    assert "JSON object" in msg
    assert "list" in msg

def test_read_input_reads_from_stdin_by_default(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"from": "stdin"}'))
    result = read_input()
    assert result == {"from": "stdin"}

def test_read_input_stdin_empty_returns_empty_dict(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    result = read_input()
    assert result == {}

def test_read_input_returns_plain_dict_instance():
    result = read_input(io.StringIO('{"key": "value"}'))
    assert type(result) is dict
