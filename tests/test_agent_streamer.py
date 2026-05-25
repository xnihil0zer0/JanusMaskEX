import io
import json
import logging
from unittest.mock import MagicMock
from pathlib import Path

import pytest

from harness.agent_streamer import (
    ClaudeStreamParser,
    GeminiStreamParser,
    stream_agent_output,
    stream_stderr,
    start_stream_threads,
    _truncate,
)

def test_truncate():
    assert _truncate("abc", 5) == "abc"
    assert _truncate("abcdef", 5) == "abcde...(6 total)"

class TestClaudeParser:
    def test_init(self):
        p = ClaudeStreamParser()
        p.handle_event({"type": "system", "subtype": "init", "model": "test", "tools": [{"name": "t1"}]})
        
    def test_thinking(self):
        p = ClaudeStreamParser()
        p.handle_event({"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "thinking"}}})
        p.handle_event({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "hm\n"}}})
        p.handle_event({"type": "stream_event", "event": {"type": "content_block_stop"}})
        
    def test_text(self):
        p = ClaudeStreamParser()
        p.handle_event({"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "text"}}})
        p.handle_event({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hello\n"}}})
        p.handle_event({"type": "stream_event", "event": {"type": "content_block_stop"}})

    def test_tool_use(self):
        p = ClaudeStreamParser()
        p.handle_event({"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "tool_use", "name": "t1"}}})
        p.handle_event({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": '{"command": "c", "args": '}}})
        p.handle_event({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": '"{\\"code\\": \\"1\\\\n2\\\\n3\\\\n4\\\\n5\\\\n6\\\\n7\\\\n8\\\\n9\\"}"}'}}})
        p.handle_event({"type": "stream_event", "event": {"type": "content_block_stop"}})

    def test_tool_use_bad_json(self):
        p = ClaudeStreamParser()
        p.handle_event({"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "tool_use", "name": "t1"}}})
        p.handle_event({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": 'bad json'}}})
        p.handle_event({"type": "stream_event", "event": {"type": "content_block_stop"}})

    def test_messages(self):
        p = ClaudeStreamParser()
        p.handle_event({"type": "stream_event", "event": {"type": "message_start"}})
        p.handle_event({"type": "stream_event", "event": {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}})
        p.handle_event({"type": "stream_event", "event": {"type": "message_stop"}})

    def test_assistant(self):
        p = ClaudeStreamParser()
        p.handle_event({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "n", "input": {"command": "c"}}]}})

    def test_user(self):
        p = ClaudeStreamParser()
        p.handle_event({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "123", "is_error": True, "content": '{"error": "bad"}'}]}})
        p.handle_event({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "123", "is_error": False, "content": '{"status": "ok", "task_id": "t1", "specification": "s"}'}]}})
        p.handle_event({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "123", "is_error": False, "content": [{'text': 'plain text'}]}]}})

    def test_result(self):
        p = ClaudeStreamParser()
        p.handle_event({"type": "result", "subtype": "success", "total_cost_usd": 1.0})
        p.handle_event({"type": "rate_limit_event", "percentage_remaining": 50, "seconds_until_reset": 10})

    def test_unknown(self):
        p = ClaudeStreamParser()
        p.handle_event({"type": "unknown_type"})


class TestGeminiParser:
    def test_basic(self):
        p = GeminiStreamParser()
        p.handle_event({"type": "init", "session_id": "123", "model": "m1"})
        p.handle_event({"type": "message", "role": "user", "content": "hello"})
        p.handle_event({"type": "message", "role": "assistant", "content": "hi\n", "delta": True})
        
    def test_tool_use(self):
        p = GeminiStreamParser()
        p.handle_event({"type": "tool_use", "tool_name": "t1", "parameters": {"command": "c", "args": {"code": "1\n2\n3\n4\n5\n6\n7\n8\n9", "other": "val"}}})
        p.handle_event({"type": "tool_use", "tool_name": "t2", "parameters": {"command": "c", "args": "plain string args"}})

    def test_tool_result(self):
        p = GeminiStreamParser()
        p.handle_event({"type": "tool_result", "status": "ok", "output": '{"status": "ok", "error": "none", "task_id": "t", "specification": "s"}'})
        p.handle_event({"type": "tool_result", "status": "error", "output": 'bad json'})

    def test_result(self):
        p = GeminiStreamParser()
        p.handle_event({"type": "result", "status": "success", "stats": {"total_input_tokens": 1}})
        p.handle_event({"type": "result", "status": "error", "stats": {"model1": {"input_tokens": 1}}})

    def test_unknown(self):
        p = GeminiStreamParser()
        p.handle_event({"type": "unknown_type"})


class TestStreaming:
    def test_stream_agent_output(self, tmp_path):
        pipe = io.StringIO('prefix text {"type": "init", "model": "test"}\n{"invalid json\n')
        log_file = tmp_path / "log.jsonl"
        stream_agent_output(pipe, "gemini", log_file)
        assert log_file.exists()

    def test_stream_agent_output_exception(self):
        class BadPipe:
            def __iter__(self):
                yield "data"
                raise RuntimeError("pipe error")
        stream_agent_output(BadPipe(), "claude")

    def test_stream_stderr(self):
        pipe = io.StringIO("error line 1\nerror line 2\n")
        stream_stderr(pipe, "claude")

    def test_stream_stderr_exception(self):
        class BadPipe:
            def __iter__(self):
                raise RuntimeError("pipe error")
        stream_stderr(BadPipe(), "claude")

    def test_start_stream_threads(self, tmp_path):
        proc = MagicMock()
        proc.stdout = io.StringIO('{"type": "init"}')
        proc.stderr = io.StringIO('err')
        t1, t2 = start_stream_threads(proc, "claude", tmp_path)
        t1.join()
        t2.join()

def test_agent_streamer_edge_cases():
    """Verify streamer edge cases."""
    from unittest.mock import patch

    # 1. Test timeout handling during streaming
    class TimeoutPipe:
        def __iter__(self):
            yield '{"type": "system", "subtype": "init"}\n'
            raise TimeoutError("stream timed out")

    with patch("harness.agent_streamer.log.exception") as mock_log:
        stream_agent_output(TimeoutPipe(), "claude")
        mock_log.assert_called_once()
        assert "Stream reader error" in mock_log.call_args[0][0]

    # 2. Test event dispatching for malformed or prefix-heavy streams
    pipe = io.StringIO('prefix text {"type": "init", "model": "test"}\nbad_json_line\n{"type": "unknown"}')
    with patch("sys.stderr.write") as mock_stderr:
        stream_agent_output(pipe, "gemini")
        # Should output raw or prefix and ignore bad json gracefully
        writes = [call.args[0] for call in mock_stderr.call_args_list]
        assert any("prefix text" in w for w in writes)
        assert any("bad_json_line" in w for w in writes)