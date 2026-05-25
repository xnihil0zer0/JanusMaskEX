"""Tests for harness/mcp_server.py — MCP server."""

import io
import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.mcp_server import (
    JanusMaskServer,
    VALID_COMMANDS,
    MCP_PROTOCOL_VERSION,
    EXECUTE_TOOL,
    PARSE_ERROR,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    INTERNAL_ERROR,
    main,
)


@pytest.fixture
def task_file(state_dir):
    """Write current_task_default.json (per-task fallback path, post-RP7) and return the task dict."""
    task = {
        "task_id": "test-001",
        "round": 1,
        "specification": "Write a function add(a, b) that returns a + b.",
        "constraints": {
            "language": "python",
            "function_signature": "def add(a: int, b: int) -> int",
            "deterministic": True,
        },
        "feedback": None,
    }
    path = state_dir / "tasks" / "current_task_default.json"
    path.write_text(json.dumps(task))
    return task


@pytest.fixture
def server(state_dir):
    return JanusMaskServer("claude", state_dir)


@pytest.fixture
def ready_server(server, task_file):
    """Server with task already read (inbox gate passed)."""
    server.cmd_get_task({})
    return server


def _state_json(state_dir, data):
    """Write STATE.json for phase checks."""
    (state_dir / "STATE.json").write_text(json.dumps(data))


# ── Server Initialization ──────────────────────────────────────────────

class TestServerInit:
    def test_claude_agent(self, state_dir):
        s = JanusMaskServer("claude", state_dir)
        assert s.agent_id == "claude"

    def test_gemini_agent(self, state_dir):
        s = JanusMaskServer("gemini", state_dir)
        assert s.agent_id == "gemini"

    def test_invalid_agent(self, state_dir):
        with pytest.raises(ValueError, match="Must be"):
            JanusMaskServer("gpt4", state_dir)

    def test_session_id_is_uuid(self, state_dir):
        s = JanusMaskServer("claude", state_dir)
        uuid.UUID(s.session_id)  # raises if not valid UUID

    def test_initial_state(self, server):
        assert server.task_read is False
        assert server.submissions == 0
        assert server.clarifications == 0


# ── MCP Protocol: initialize ───────────────────────────────────────────

class TestInitialize:
    def test_returns_protocol_version(self, server):
        result = server.handle_initialize({})
        assert result["protocolVersion"] == MCP_PROTOCOL_VERSION

    def test_has_capabilities(self, server):
        result = server.handle_initialize({})
        assert "tools" in result["capabilities"]

    def test_server_info(self, server):
        result = server.handle_initialize({})
        assert result["serverInfo"]["name"] == "janusmask"

    def test_sets_initialized(self, server):
        server.handle_initialize({})
        assert server._initialized is True


# ── MCP Protocol: tools/list ────────────────────────────────────────────

class TestToolsList:
    def test_returns_one_tool(self, server):
        result = server.handle_tools_list({})
        assert len(result["tools"]) == 1

    def test_tool_name(self, server):
        result = server.handle_tools_list({})
        assert result["tools"][0]["name"] == "execute"

    def test_has_command_enum(self, server):
        result = server.handle_tools_list({})
        enum = result["tools"][0]["inputSchema"]["properties"]["command"]["enum"]
        assert len(enum) == 5
        assert set(enum) == VALID_COMMANDS


# ── MCP Protocol: tools/call ───────────────────────────────────────────

class TestToolsCall:
    def test_unknown_tool(self, server):
        result = server.handle_tools_call({"name": "unknown"})
        assert result["isError"] is True

    def test_invalid_command(self, server):
        result = server.handle_tools_call({
            "name": "execute",
            "arguments": {"command": "hack"},
        })
        assert result["isError"] is True

    def test_empty_command(self, server):
        result = server.handle_tools_call({
            "name": "execute",
            "arguments": {"command": ""},
        })
        assert result["isError"] is True


# ── Command: get_task ───────────────────────────────────────────────────

class TestGetTask:
    def test_valid_task(self, server, task_file):
        result = server.cmd_get_task({})
        assert result["task_id"] == "test-001"
        assert server.task_read is True

    def test_missing_task(self, server):
        result = server.cmd_get_task({})
        assert result["code"] == "no_task"

    def test_corrupt_task(self, state_dir, server):
        (state_dir / "tasks" / "current_task_default.json").write_text("NOT JSON")
        result = server.cmd_get_task({})
        assert result["code"] == "corrupt_task"

    def test_idempotent(self, server, task_file):
        r1 = server.cmd_get_task({})
        r2 = server.cmd_get_task({})
        assert r1["task_id"] == r2["task_id"]


# ── Inbox Gate ──────────────────────────────────────────────────────────

class TestInboxGate:
    def test_submit_before_get_task(self, server):
        result = server._dispatch("submit_code", json.dumps({"code": "def f(): pass"}))
        assert result["code"] == "task_not_read"

    def test_get_feedback_before_get_task(self, server):
        """Post-P0.3: get_feedback is phase-gated, not inbox-gated (sub-plan 04 invariant 3).
        Without STATE.json, _current_phase defaults to 'synthesis', so the phase-gate
        error code is emitted instead of task_not_read."""
        result = server._dispatch("get_feedback", None)
        assert result["code"] == "wrong_phase"

    def test_request_clarification_before_get_task(self, server):
        result = server._dispatch("request_clarification", json.dumps({"question": "?"}))
        assert result["code"] == "task_not_read"

    def test_report_error_before_get_task(self, server):
        result = server._dispatch("report_error", json.dumps({"error": "oops"}))
        assert result["code"] == "task_not_read"

    def test_submit_after_get_task(self, ready_server):
        result = ready_server._dispatch("submit_code", json.dumps({
            "code": "def add(a: int, b: int) -> int:\n    return a + b\n"
        }))
        assert result["status"] == "accepted"


# ── Command: submit_code ────────────────────────────────────────────────

class TestSubmitCode:
    def test_valid_submission(self, ready_server):
        result = ready_server.cmd_submit_code({
            "code": "def add(a: int, b: int) -> int:\n    return a + b\n",
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        assert result["status"] == "accepted"
        assert result["ast_valid"] is True

    def test_syntax_error_rejected(self, ready_server):
        result = ready_server.cmd_submit_code({
            "code": "def add(a, b:\n    return\n",
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        assert result["status"] == "rejected"
        assert result["ast_valid"] is False
        assert len(result["violations"]) > 0

    def test_nondeterminism_rejected(self, ready_server):
        result = ready_server.cmd_submit_code({
            "code": "import random\ndef f():\n    return random.randint(1, 10)\n",
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        assert result["status"] == "rejected"

    def test_warnings_returned(self, ready_server):
        result = ready_server.cmd_submit_code({
            "code": "def f():\n    print('hi')\n    return 1\n",
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        assert result["status"] == "accepted"
        assert "warnings" in result

    def test_missing_code(self, ready_server):
        result = ready_server.cmd_submit_code({
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        assert result["code"] == "missing_field"

    def test_empty_code(self, ready_server):
        result = ready_server.cmd_submit_code({
            "code": "",
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        assert result["code"] == "missing_field"

    def test_submission_persisted(self, ready_server, state_dir):
        ready_server.cmd_submit_code({
            "code": "def f():\n    return 1\n",
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        files = list((state_dir / "sessions").glob("claude_round*_submission.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert "code" in data

    def test_locked_fields_injected(self, ready_server, state_dir):
        # _dispatch injects locked fields, overriding agent-supplied values
        result = ready_server._dispatch("submit_code", json.dumps({
            "code": "def f():\n    return 1\n",
            "session_id": "AGENT_SUPPLIED",
            "agent_identity": "AGENT_SUPPLIED",
        }))
        assert result["status"] == "accepted"
        files = list((state_dir / "sessions").glob("claude_round*_submission.json"))
        data = json.loads(files[0].read_text())
        assert data["agent_identity"] == "claude"
        assert data["session_id"] == ready_server.session_id


# ── Rate Limiting ───────────────────────────────────────────────────────

class TestRateLimiting:
    def _submit(self, server, code="def f():\n    return 1\n"):
        return server.cmd_submit_code({
            "code": code,
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })

    def test_five_submissions_ok(self, ready_server):
        for _ in range(5):
            result = self._submit(ready_server)
            assert result["status"] == "accepted"

    def test_sixth_rejected(self, ready_server):
        for _ in range(5):
            self._submit(ready_server)
        result = self._submit(ready_server)
        assert result["code"] == "max_submissions"

    def test_rejected_does_not_increment(self, ready_server):
        # Submit invalid code (rejected by AST) — should NOT count
        ready_server.cmd_submit_code({
            "code": "def f(:\n",
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        assert ready_server.submissions == 0
        # Valid submission should still work
        result = self._submit(ready_server)
        assert result["status"] == "accepted"


# ── Command: request_clarification ──────────────────────────────────────

class TestRequestClarification:
    def test_valid(self, ready_server):
        result = ready_server.cmd_request_clarification({
            "question": "What about edge cases?",
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        assert result["status"] == "acknowledged"

    def test_max_clarifications(self, ready_server):
        for i in range(2):
            ready_server.cmd_request_clarification({
                "question": f"Q{i}",
                "session_id": "x", "agent_identity": "claude",
                "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
            })
        result = ready_server.cmd_request_clarification({
            "question": "Q3",
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        assert result["code"] == "max_clarifications"

    def test_missing_question(self, ready_server):
        result = ready_server.cmd_request_clarification({
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        assert result["code"] == "missing_field"


# ── Command: report_error ──────────────────────────────────────────────

class TestReportError:
    def test_valid(self, ready_server):
        result = ready_server.cmd_report_error({
            "error": "Cannot solve this",
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        assert result["status"] == "acknowledged"

    def test_missing_error(self, ready_server):
        result = ready_server.cmd_report_error({
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        assert result["code"] == "missing_field"

    def test_persisted(self, ready_server, state_dir):
        ready_server.cmd_report_error({
            "error": "test error",
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        path = state_dir / "sessions" / "claude_error.json"
        assert path.is_file()


# ── Command: get_feedback ──────────────────────────────────────────────

class TestGetFeedback:
    def test_wrong_phase(self, ready_server, state_dir):
        _state_json(state_dir, {"phase": "synthesis", "round": 1})
        result = ready_server.cmd_get_feedback({
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        assert result["code"] == "wrong_phase"

    def test_no_feedback_file(self, ready_server, state_dir):
        _state_json(state_dir, {"phase": "cross_examination", "round": 1})
        result = ready_server.cmd_get_feedback({
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        assert result["code"] == "no_feedback"

    def test_valid_feedback(self, ready_server, state_dir, monkeypatch):
        """Post-P0.3: feedback filename is generated by session_namer.generate_feedback_filename
        (e.g. 'test-001_round1_claude_feedback.json'), not the legacy 'claude_feedback.json'."""
        from harness.session_namer import generate_feedback_filename
        monkeypatch.setenv("JANUSMASK_TASK_ID", "test-001")
        _state_json(state_dir, {"phase": "cross_examination", "round": 1})
        feedback = {"round": 1, "code_under_review": "def f(): pass", "review_prompt": "Review this."}
        fname = generate_feedback_filename("claude", 1, "test-001")
        (state_dir / "sessions" / fname).write_text(json.dumps(feedback))
        result = ready_server.cmd_get_feedback({
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        assert result["round"] == 1


# ── Locked Field Injection ──────────────────────────────────────────────

class TestLockedFields:
    def test_session_id_overwritten(self, server):
        args = server._inject_locked_fields({"session_id": "FAKE"})
        assert args["session_id"] == server.session_id

    def test_agent_identity_overwritten(self, server):
        args = server._inject_locked_fields({"agent_identity": "FAKE"})
        assert args["agent_identity"] == "claude"

    def test_timestamp_is_iso(self, server):
        args = server._inject_locked_fields({})
        assert "T" in args["timestamp"]
        assert args["timestamp"].endswith("+00:00") or args["timestamp"].endswith("Z")


# ── Message Routing ─────────────────────────────────────────────────────

class TestMessageRouting:
    def test_request_returns_response(self, server):
        resp = server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert resp is not None
        assert resp["id"] == 1

    def test_notification_returns_none(self, server):
        resp = server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        assert resp is None

    def test_ping(self, server):
        resp = server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}})
        assert resp["result"] == {}

    def test_unknown_method(self, server):
        resp = server.handle_message({"jsonrpc": "2.0", "id": 3, "method": "unknown/method", "params": {}})
        assert "error" in resp
        assert resp["error"]["code"] == -32601

    def test_cancelled_notification(self, server):
        resp = server.handle_message({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {}})
        assert resp is None


# ── Entry Point ─────────────────────────────────────────────────────────

class TestEntryPoint:
    """M-76 through M-79: Entry point / environment variable tests."""

    def test_missing_agent_env(self, monkeypatch):
        """M-76: JANUSMASK_AGENT not set -> exit 1."""
        monkeypatch.delenv("JANUSMASK_AGENT", raising=False)
        monkeypatch.delenv("JANUSMASK_STATE_DIR", raising=False)
        with pytest.raises(SystemExit):
            main()

    def test_missing_state_dir_env(self, monkeypatch, state_dir):
        """M-77: JANUSMASK_STATE_DIR not set -> exit 1."""
        monkeypatch.setenv("JANUSMASK_AGENT", "claude")
        monkeypatch.delenv("JANUSMASK_STATE_DIR", raising=False)
        with pytest.raises(SystemExit):
            main()

    def test_invalid_agent_env(self, monkeypatch, state_dir):
        """M-78: JANUSMASK_AGENT=invalid -> exit 1."""
        monkeypatch.setenv("JANUSMASK_AGENT", "invalid")
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state_dir))
        with pytest.raises(SystemExit):
            main()

    def test_valid_env_starts_server(self, monkeypatch, state_dir):
        """M-79: Valid environment variables -> server starts and processes stdin."""
        monkeypatch.setenv("JANUSMASK_AGENT", "claude")
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state_dir))
        # Provide empty stdin so run() returns immediately on EOF.
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        # Capture stdout
        captured = io.StringIO()
        monkeypatch.setattr("sys.stdout", captured)
        main()  # should not raise; exits cleanly on EOF


# ── M-06, M-07: Separate initial-counter assertions ──────────────────

class TestInitialCounters:
    """M-06 and M-07: submissions and clarifications start at 0."""

    def test_submissions_starts_at_zero(self, server):
        """M-06: submissions starts at 0."""
        assert server.submissions == 0

    def test_clarifications_starts_at_zero(self, server):
        """M-07: clarifications starts at 0."""
        assert server.clarifications == 0


# ── M-12: Client info logged ──────────────────────────────────────────

class TestInitializeLogging:
    """M-12: Client info passed via params is logged."""

    def test_client_info_logged(self, server, caplog):
        """M-12: Client info from params appears in log output."""
        with caplog.at_level(logging.INFO, logger="janusmask.mcp"):
            server.handle_initialize({
                "clientInfo": {"name": "test-client", "version": "1.0"},
            })
        assert "test-client" in caplog.text


# ── M-16: inputSchema has "args" field ───────────────────────────────

class TestToolsListArgs:
    """M-16: Tool inputSchema has 'args' field."""

    def test_input_schema_has_args(self, server):
        """M-16: inputSchema properties include 'args' with type 'string'."""
        result = server.handle_tools_list({})
        schema = result["tools"][0]["inputSchema"]
        assert "args" in schema["properties"]
        assert schema["properties"]["args"]["type"] == "string"


# ── M-21: Call with command=None ──────────────────────────────────────

class TestToolsCallNone:
    """M-21: tools/call with command=None."""

    def test_none_command(self, server):
        """M-21: Call with command=None -> isError=True."""
        result = server.handle_tools_call({
            "name": "execute",
            "arguments": {"command": None},
        })
        assert result["isError"] is True


# ── M-34: Nondeterminism accepted on nondeterministic task ────────────

class TestNondeterministicTask:
    """M-34: Nondeterminism accepted when task allows it."""

    def test_nondeterminism_accepted_when_allowed(self, state_dir):
        """M-34: Code with nondeterminism on nondeterministic task -> accepted."""
        # Write a nondeterministic task
        task = {
            "task_id": "nondet-001",
            "round": 1,
            "specification": "Shuffle a list.",
            "constraints": {
                "language": "python",
                "deterministic": False,
            },
            "feedback": None,
        }
        (state_dir / "tasks" / "current_task_default.json").write_text(json.dumps(task))
        server = JanusMaskServer("claude", state_dir)
        server.cmd_get_task({})
        result = server.cmd_submit_code({
            "code": "import random\ndef shuffle(items):\n    result = list(items)\n    random.shuffle(result)\n    return result\n",
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        assert result["status"] == "accepted"


# ── M-38: code is an integer (wrong type) ─────────────────────────────

class TestCodeWrongType:
    """M-38: code field with wrong type."""

    def test_code_is_integer(self, ready_server):
        """M-38: code is an integer -> missing_field error."""
        result = ready_server.cmd_submit_code({
            "code": 42,
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        assert result["code"] == "missing_field"


# ── M-44: submissions counter increments on each accepted ────────────

class TestSubmissionCounter:
    """M-44: submissions counter increments correctly."""

    def test_counter_increments_each_accepted(self, ready_server):
        """M-44: After N accepted submissions, counter == N."""
        for i in range(3):
            result = ready_server.cmd_submit_code({
                "code": "def f():\n    return 1\n",
                "session_id": "x", "agent_identity": "claude",
                "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
            })
            assert result["status"] == "accepted"
            assert ready_server.submissions == i + 1


# ── M-45 (explicit): Rejected does NOT increment counter ─────────────

class TestRejectedDoesNotIncrement:
    """M-45: Rejected submission does NOT increment counter (explicit test)."""

    def test_rejected_submission_counter_unchanged(self, ready_server):
        """M-45: Syntax-error rejection leaves submissions at 0."""
        before = ready_server.submissions
        ready_server.cmd_submit_code({
            "code": "def f(:\n",
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        assert ready_server.submissions == before


# ── M-50: Clarification persisted to sessions dir ────────────────────

class TestClarificationPersisted:
    """M-50: Clarification is persisted to sessions dir."""

    def test_clarification_persisted(self, ready_server, state_dir):
        """M-50: Clarification file written to sessions directory."""
        ready_server.cmd_request_clarification({
            "question": "What about edge cases?",
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        files = list((state_dir / "sessions").glob("claude_clarification_*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert data["question"] == "What about edge cases?"


# ── M-57: get_feedback when feedback file is corrupt JSON ─────────────

class TestGetFeedbackCorrupt:
    """M-57: Corrupt feedback file."""

    def test_corrupt_feedback(self, ready_server, state_dir, monkeypatch):
        """M-57: get_feedback with corrupt JSON -> corrupt_feedback error.
        Post-P0.3 filename contract: generated by session_namer.generate_feedback_filename."""
        from harness.session_namer import generate_feedback_filename
        monkeypatch.setenv("JANUSMASK_TASK_ID", "test-001")
        _state_json(state_dir, {"phase": "cross_examination", "round": 1})
        fname = generate_feedback_filename("claude", 1, "test-001")
        (state_dir / "sessions" / fname).write_text("NOT VALID JSON{{{")
        result = ready_server.cmd_get_feedback({
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        assert result["code"] == "corrupt_feedback"


# ── M-60, M-61: All commands inject round_number and timestamp ────────

class TestLockedFieldInjectionAll:
    """M-60 through M-63: Locked field injection across all commands."""

    def test_round_number_injected(self, server, state_dir):
        """M-60: _inject_locked_fields injects round_number from STATE.json."""
        _state_json(state_dir, {"round": 7, "phase": "synthesis"})
        args = server._inject_locked_fields({})
        assert args["round_number"] == 7

    def test_timestamp_is_iso8601(self, server):
        """M-61: Timestamp injected is valid ISO 8601 UTC."""
        args = server._inject_locked_fields({})
        ts = args["timestamp"]
        # Must be parseable as ISO 8601
        parsed = datetime.fromisoformat(ts)
        # Must contain timezone info (UTC)
        assert parsed.tzinfo is not None

    def test_agent_supplied_session_id_overwritten(self, server):
        """M-62: Agent attempts to supply session_id -> overwritten by server."""
        args = server._inject_locked_fields({"session_id": "AGENT_FAKE_SESSION"})
        assert args["session_id"] == server.session_id
        assert args["session_id"] != "AGENT_FAKE_SESSION"

    def test_agent_supplied_agent_identity_overwritten(self, server):
        """M-63: Agent attempts to supply agent_identity -> overwritten by server."""
        args = server._inject_locked_fields({"agent_identity": "gpt4"})
        assert args["agent_identity"] == "claude"
        assert args["agent_identity"] != "gpt4"


# ── M-64 through M-75: JSON-RPC stdio protocol tests ─────────────────

class TestStdioProtocol:
    """M-64 through M-75: Full stdio JSON-RPC protocol tests."""

    def _run_stdio(self, server, lines):
        """Feed lines to the server's run() method and capture stdout.

        Args:
            server: JanusMaskServer instance
            lines: list of strings (raw lines, not newline-terminated)

        Returns:
            list of parsed JSON objects written to stdout
        """
        stdin_data = "\n".join(lines) + "\n"
        captured = io.StringIO()
        with patch("sys.stdin", io.StringIO(stdin_data)), \
             patch("sys.stdout", captured):
            server.run()
        output = captured.getvalue()
        results = []
        for out_line in output.strip().split("\n"):
            out_line = out_line.strip()
            if out_line:
                results.append(json.loads(out_line))
        return results

    def test_valid_request(self, server):
        """M-64: Send valid JSON-RPC request, receive valid response."""
        msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        responses = self._run_stdio(server, [msg])
        assert len(responses) == 1
        resp = responses[0]
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        assert "result" in resp

    def test_notification_no_response(self, server):
        """M-65: Send notification (no id) -> no response on stdout."""
        msg = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        responses = self._run_stdio(server, [msg])
        assert len(responses) == 0

    def test_initialized_notification(self, server):
        """M-66: notifications/initialized is handled, no response."""
        msg = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        responses = self._run_stdio(server, [msg])
        assert len(responses) == 0

    def test_cancelled_notification(self, server):
        """M-67: notifications/cancelled is handled, no response."""
        msg = json.dumps({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {}})
        responses = self._run_stdio(server, [msg])
        assert len(responses) == 0

    def test_ping_request(self, server):
        """M-68: ping request -> empty result {}."""
        msg = json.dumps({"jsonrpc": "2.0", "id": 42, "method": "ping", "params": {}})
        responses = self._run_stdio(server, [msg])
        assert len(responses) == 1
        assert responses[0]["result"] == {}

    def test_unknown_method(self, server):
        """M-69: unknown method -> -32601 METHOD_NOT_FOUND."""
        msg = json.dumps({"jsonrpc": "2.0", "id": 5, "method": "bogus/method", "params": {}})
        responses = self._run_stdio(server, [msg])
        assert len(responses) == 1
        assert responses[0]["error"]["code"] == METHOD_NOT_FOUND

    def test_parse_error_invalid_json(self, server):
        """M-70: Invalid JSON -> -32700 PARSE_ERROR."""
        responses = self._run_stdio(server, ["NOT VALID JSON {{{"])
        assert len(responses) == 1
        assert responses[0]["error"]["code"] == PARSE_ERROR

    def test_invalid_request_non_object(self, server):
        """M-71: Non-object JSON (e.g. string) -> -32600 INVALID_REQUEST."""
        responses = self._run_stdio(server, ['"hello"'])
        assert len(responses) == 1
        assert responses[0]["error"]["code"] == INVALID_REQUEST

    def test_empty_line_ignored(self, server):
        """M-72: Empty line is ignored (no response)."""
        # Mix empty lines with a valid request
        init_msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}})
        responses = self._run_stdio(server, ["", "", init_msg, ""])
        assert len(responses) == 1
        assert responses[0]["id"] == 1

    def test_multiple_messages(self, server):
        """M-73: Multiple messages in sequence, each handled independently."""
        msg1 = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        msg2 = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}})
        msg3 = json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}})
        responses = self._run_stdio(server, [msg1, msg2, msg3])
        assert len(responses) == 3
        assert responses[0]["id"] == 1
        assert responses[1]["id"] == 2
        assert responses[2]["id"] == 3

    def test_eof_exits_cleanly(self, server):
        """M-74: EOF (stdin closed) -> server exits cleanly (no exception)."""
        # An empty input simulates immediate EOF.
        responses = self._run_stdio(server, [])
        # No responses expected (no input), no exception raised.
        assert responses == []

    def test_internal_error(self, server):
        """M-75: Internal exception during handling -> -32603 INTERNAL_ERROR."""
        msg = json.dumps({"jsonrpc": "2.0", "id": 99, "method": "initialize", "params": {}})
        # Patch handle_initialize to raise an exception
        with patch.object(server, "handle_initialize", side_effect=RuntimeError("boom")):
            responses = self._run_stdio(server, [msg])
        assert len(responses) == 1
        assert responses[0]["error"]["code"] == INTERNAL_ERROR
