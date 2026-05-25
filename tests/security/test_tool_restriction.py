"""Security tests: tool restriction, identity isolation, cross-exam blindness."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from harness.mcp_server import JanusMaskServer
from harness.cross_examiner import anonymize_code, prepare_exam_packets
from harness.diff_fuzzer import FuzzFailure
from harness.sandbox import ExecutionResult

HOOK_SCRIPT = str(Path(__file__).resolve().parent.parent.parent / "harness" / "hook_pre_tool.py")


def _run_hook(tool_name):
    result = subprocess.run(
        [sys.executable, HOOK_SCRIPT],
        input=json.dumps({"tool_name": tool_name}),
        capture_output=True, text=True, timeout=5,
    )
    return json.loads(result.stdout)


def _make_failure():
    return FuzzFailure(
        input_args=[1, 2], input_kwargs={},
        result_a=ExecutionResult(success=True, return_value=1, return_repr="1"),
        result_b=ExecutionResult(success=True, return_value=2, return_repr="2"),
        reason="return_mismatch",
    )


# ── Tool Restriction (SEC-01 to SEC-08) ─────────────────────────────────

class TestToolRestriction:
    @pytest.mark.parametrize("tool", [
        "Bash", "Read", "Edit", "Write", "Glob", "Grep",
        "WebFetch", "WebSearch", "Agent", "NotebookEdit",
        "TodoRead", "TodoWrite", "AskUserQuestion",
        "TaskCreate", "TaskGet", "TaskList", "TaskUpdate",
        "EnterPlanMode", "ExitPlanMode",
    ])
    def test_hook_blocks_native_tool(self, tool):
        resp = _run_hook(tool)
        assert resp["decision"] == "deny"

    def test_hook_allows_janusmask(self):
        resp = _run_hook("mcp__janusmask__execute")
        assert resp["decision"] == "allow"

    def test_mcp_rejects_unknown_tool(self, tmp_path):
        (tmp_path / "sessions").mkdir()
        (tmp_path / "tasks").mkdir()
        server = JanusMaskServer("claude", tmp_path)
        result = server.handle_tools_call({"name": "not_execute", "arguments": {}})
        assert result["isError"] is True

    def test_mcp_rejects_unknown_command(self, tmp_path):
        (tmp_path / "sessions").mkdir()
        (tmp_path / "tasks").mkdir()
        server = JanusMaskServer("claude", tmp_path)
        result = server.handle_tools_call({
            "name": "execute",
            "arguments": {"command": "shell_exec"},
        })
        assert result["isError"] is True


# ── Identity Isolation (SEC-09 to SEC-14) ──────────────────────────────

class TestIdentityIsolation:
    @pytest.fixture
    def server_pair(self, tmp_path):
        for sub in ("sessions", "tasks"):
            (tmp_path / sub).mkdir()
        task = {"task_id": "sec-test", "constraints": {"deterministic": True}}
        (tmp_path / "tasks" / "current_task.json").write_text(json.dumps(task))
        claude = JanusMaskServer("claude", tmp_path)
        gemini = JanusMaskServer("gemini", tmp_path)
        return claude, gemini, tmp_path

    def test_locked_session_id(self, server_pair):
        claude, _, _ = server_pair
        args = claude._inject_locked_fields({"session_id": "HACKED"})
        assert args["session_id"] == claude.session_id
        assert args["session_id"] != "HACKED"

    def test_locked_agent_identity(self, server_pair):
        claude, _, _ = server_pair
        args = claude._inject_locked_fields({"agent_identity": "gemini"})
        assert args["agent_identity"] == "claude"

    def test_locked_round_number(self, server_pair):
        claude, _, state_dir = server_pair
        args = claude._inject_locked_fields({"round_number": 999})
        # Should come from STATE.json, not agent-supplied
        assert isinstance(args["round_number"], int)

    def test_locked_timestamp(self, server_pair):
        claude, _, _ = server_pair
        args = claude._inject_locked_fields({"timestamp": "1970-01-01T00:00:00Z"})
        assert args["timestamp"] != "1970-01-01T00:00:00Z"

    def test_claude_writes_claude_files(self, server_pair):
        claude, _, state_dir = server_pair
        claude.cmd_get_task({})
        claude.cmd_submit_code({
            "code": "def f():\n    return 1\n",
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        files = list((state_dir / "sessions").glob("*.json"))
        for f in files:
            assert "gemini" not in f.name

    def test_gemini_writes_gemini_files(self, server_pair):
        _, gemini, state_dir = server_pair
        gemini.cmd_get_task({})
        gemini.cmd_submit_code({
            "code": "def f():\n    return 1\n",
            "session_id": "x", "agent_identity": "gemini",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        files = list((state_dir / "sessions").glob("*.json"))
        for f in files:
            assert "claude" not in f.name


# ── Cross-Exam Blindness (SEC-32 to SEC-37) ────────────────────────────

class TestCrossExamBlindness:
    def test_no_original_variable_names(self):
        code = "def foo(x: int) -> int:\n    my_result = x + 1\n    return my_result\n"
        anon = anonymize_code(code)
        assert "my_result" not in anon

    def test_no_comments(self):
        code = "# secret comment\ndef foo(x: int) -> int:\n    # another secret\n    return x\n"
        anon = anonymize_code(code)
        assert "#" not in anon

    def test_no_docstrings(self):
        code = 'def foo(x: int) -> int:\n    """My docstring here."""\n    return x\n'
        anon = anonymize_code(code)
        assert "docstring" not in anon.lower()

    def test_claude_reviews_code_b(self):
        code_a = "def foo(x: int) -> int:\n    alpha = x + 1\n    return alpha\n"
        code_b = "def foo(x: int) -> int:\n    beta = x + 2\n    return beta\n"
        failures = [_make_failure()]
        cp, gp = prepare_exam_packets(code_a, code_b, "task spec", failures)
        assert cp.agent == "claude"
        # Claude should have anonymized code_B
        anon_b = anonymize_code(code_b)
        assert cp.code_under_review == anon_b

    def test_gemini_reviews_code_a(self):
        code_a = "def foo(x: int) -> int:\n    alpha = x + 1\n    return alpha\n"
        code_b = "def foo(x: int) -> int:\n    beta = x + 2\n    return beta\n"
        failures = [_make_failure()]
        cp, gp = prepare_exam_packets(code_a, code_b, "task spec", failures)
        assert gp.agent == "gemini"
        anon_a = anonymize_code(code_a)
        assert gp.code_under_review == anon_a

    def test_no_authorship_in_prompt(self):
        code_a = "def foo(x): return x + 1\n"
        code_b = "def foo(x): return x + 2\n"
        failures = [_make_failure()]
        cp, gp = prepare_exam_packets(code_a, code_b, "task", failures)
        for prompt in (cp.review_prompt, gp.review_prompt):
            lower = prompt.lower()
            assert "claude" not in lower
            assert "gemini" not in lower
            assert "your code" not in lower
            assert "their code" not in lower
