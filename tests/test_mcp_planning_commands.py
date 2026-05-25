import json
import pytest
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

from harness.mcp_server import JanusMaskServer, build_execute_tool

@pytest.fixture
def planning_server(tmp_path):
    with patch.dict(os.environ, {"JANUSMASK_MODE": "planning", "JANUSMASK_AGENT": "claude", "JANUSMASK_STATE_DIR": str(tmp_path)}):
        server = JanusMaskServer(agent_id="claude", state_dir=tmp_path)
    return server

@pytest.fixture
def synthesis_server(tmp_path):
    with patch.dict(os.environ, {"JANUSMASK_MODE": "synthesis", "JANUSMASK_AGENT": "claude", "JANUSMASK_STATE_DIR": str(tmp_path)}):
        server = JanusMaskServer(agent_id="claude", state_dir=tmp_path)
    return server

def _make_call(server, command, args):
    msg = {
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "execute",
            "arguments": {
                "command": command,
                "args": json.dumps(args)
            }
        }
    }
    return server.handle_message(msg)

def test_planning_mode_blocks_synthesis_commands(planning_server):
    res = _make_call(planning_server, "get_task", {})
    assert res["result"]["isError"] is True
    content = json.loads(res["result"]["content"][0]["text"])
    assert content["code"] == "wrong_mode"

def test_get_planning_brief_happy_path(planning_server, tmp_path):
    brief_dir = tmp_path / "planning"
    brief_dir.mkdir(parents=True)
    brief_file = brief_dir / "brief.json"
    brief_data = {"title": "Test Brief"}
    brief_file.write_text(json.dumps(brief_data))
    
    res = _make_call(planning_server, "get_planning_brief", {})
    assert res["result"]["isError"] is False
    content = json.loads(res["result"]["content"][0]["text"])
    assert content["title"] == "Test Brief"

def test_get_planning_brief_no_brief(planning_server):
    res = _make_call(planning_server, "get_planning_brief", {})
    assert res["result"]["isError"] is True
    content = json.loads(res["result"]["content"][0]["text"])
    assert content["code"] == "no_brief"

@patch('harness.planner.plan_validator.validate_plan', return_value=[])
def test_submit_plan_draft_valid(mock_validate, planning_server, tmp_path):
    planning_server.task_read = True # bypass inbox gate
    draft = {"tasks": []}
    res = _make_call(planning_server, "submit_plan_draft", draft)
    
    assert res["result"]["isError"] is False
    content = json.loads(res["result"]["content"][0]["text"])
    assert content["status"] == "accepted"
    
    saved_path = tmp_path / "planning" / "sessions" / "claude_draft.json"
    assert saved_path.exists()
    
def test_submit_plan_draft_invalid_rejected(planning_server):
    planning_server.task_read = True
    
    class FakeViolation:
        code = "missing_field"
        path = "objective"
        message = "Missing objective"
        
    with patch('harness.planner.plan_validator.validate_plan', return_value=[FakeViolation()]):
        res = _make_call(planning_server, "submit_plan_draft", {})
        
    assert res["result"]["isError"] is False # Wait, spec says "rejects with {status:'rejected', violations:[...]}". The MCP call itself is successful but the payload contains rejection.
    content = json.loads(res["result"]["content"][0]["text"])
    assert content["status"] == "rejected"
    assert len(content["violations"]) > 0
    assert content["violations"][0]["code"] == "missing_field"

def test_submit_reconciliation_unknown_diff_item(planning_server, tmp_path):
    planning_server.task_read = True
    
    diff_dir = tmp_path / "planning"
    diff_dir.mkdir(parents=True)
    diff_file = diff_dir / "current_diff.json"
    diff_file.write_text(json.dumps({"items": [{"diff_item_id": "known_id"}]}))
    
    responses = {"responses": [{"diff_item_id": "unknown_id", "stance": "defend", "rationale": "x"}]}
    res = _make_call(planning_server, "submit_reconciliation_response", responses)
    assert res["result"]["isError"] is True
    content = json.loads(res["result"]["content"][0]["text"])
    assert content["code"] == "unknown_diff_item"

@patch('harness.planner.plan_validator.validate_plan', return_value=[])
def test_second_submission_rejected(mock_validate, planning_server):
    planning_server.task_read = True
    
    res1 = _make_call(planning_server, "submit_plan_draft", {})
    assert res1["result"]["isError"] is False
    
    res2 = _make_call(planning_server, "submit_plan_draft", {})
    assert res2["result"]["isError"] is True
    content2 = json.loads(res2["result"]["content"][0]["text"])
    assert content2["code"] == "already_submitted"

def test_tools_list_planning_mode_enum_exact(planning_server):
    res = planning_server.handle_message({"id": 1, "method": "tools/list"})
    schema = res["result"]["tools"][0]
    enum = set(schema["inputSchema"]["properties"]["command"]["enum"])
    assert enum == {"get_planning_brief", "submit_plan_draft", "submit_reconciliation_response", "request_clarification", "report_error"}

def test_tools_list_synthesis_mode_enum_exact(synthesis_server):
    res = synthesis_server.handle_message({"id": 1, "method": "tools/list"})
    schema = res["result"]["tools"][0]
    enum = set(schema["inputSchema"]["properties"]["command"]["enum"])
    assert enum == {"get_task", "submit_code", "request_clarification", "report_error", "get_feedback"}

def test_build_execute_tool_is_pure():
    t1 = build_execute_tool("planning")
    t2 = build_execute_tool("planning")
    assert id(t1) != id(t2)

@patch('harness.planner.plan_validator.validate_plan', return_value=[])
def test_end_to_end_planning_mcp_session(mock_validate, tmp_path):
    with patch.dict(os.environ, {"JANUSMASK_MODE": "planning", "JANUSMASK_AGENT": "claude", "JANUSMASK_STATE_DIR": str(tmp_path)}):
        server = JanusMaskServer("claude", tmp_path)
    
    brief_dir = tmp_path / "planning"
    brief_dir.mkdir(parents=True)
    brief_file = brief_dir / "brief.json"
    brief_file.write_text(json.dumps({"title": "Test"}))
    
    # 1. get brief
    res1 = _make_call(server, "get_planning_brief", {})
    assert res1["result"]["isError"] is False
    content = json.loads(res1["result"]["content"][0]["text"])
    assert content["title"] == "Test"
    
    # 2. submit draft
    res2 = _make_call(server, "submit_plan_draft", {})
    assert res2["result"]["isError"] is False
    
    draft_file = tmp_path / "planning" / "sessions" / "claude_draft.json"
    assert draft_file.exists()
    
    # 3. subsequent get_task fails with wrong_mode
    res3 = _make_call(server, "get_task", {})
    assert res3["result"]["isError"] is True
    content3 = json.loads(res3["result"]["content"][0]["text"])
    assert content3["code"] == "wrong_mode"

from hypothesis import given, settings, strategies as st

@settings(max_examples=50)
@given(st.text(), st.dictionaries(st.text(), st.text()))
def test_random_commands_never_crash(command, args):
    import os
    from harness.mcp_server import JanusMaskServer
    import tempfile
    
    with tempfile.TemporaryDirectory() as td:
        with patch.dict(os.environ, {"JANUSMASK_MODE": "planning", "JANUSMASK_AGENT": "claude", "JANUSMASK_STATE_DIR": td}):
            server = JanusMaskServer("claude", Path(td))
            
            msg = {
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "execute",
                    "arguments": {
                        "command": command,
                        "args": json.dumps(args)
                    }
                }
            }
            # Should not raise exception
            res = server.handle_message(msg)
            # Either it's valid, or returns error inside JSON RPC, but no python crash

def test_synthesis_mode_unchanged(synthesis_server, tmp_path):
    # Setup state for synthesis
    task_dir = tmp_path / "tasks"
    task_dir.mkdir(parents=True)
    task_file = task_dir / "current_task_default.json"
    task_file.write_text(json.dumps({"task_id": "test"}))
    
    res1 = _make_call(synthesis_server, "get_task", {})
    assert res1["result"]["isError"] is False
    
    with patch('harness.mcp_server.validate_code', return_value=[]):
        res2 = _make_call(synthesis_server, "submit_code", {"code": "print(1)"})
        assert res2["result"]["isError"] is False

def test_planning_mode_empty_reconciliation_responses_accepted(planning_server, tmp_path):
    planning_server.task_read = True
    
    diff_dir = tmp_path / "planning"
    diff_dir.mkdir(parents=True)
    diff_file = diff_dir / "current_diff.json"
    diff_file.write_text(json.dumps({"items": []}))
    
    res = _make_call(planning_server, "submit_reconciliation_response", {"responses": []})
    assert res["result"]["isError"] is False
    content = json.loads(res["result"]["content"][0]["text"])
    assert content["status"] == "accepted"
