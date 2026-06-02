"""Adversarial regression test for MCP relax external constructs.

Ensures that when an external task submits code containing eval/exec/__import__
via the MCP server, they are allowed, while self-tasks remain strictly rejected.
"""
from __future__ import annotations

import json
import pathlib
import pytest

from harness import mcp_server
from harness.hooks.rpc import submit_code as rpc_submit_code

EVAL_CODE = "def foo(x):\n    return eval('1 + 1')\n"

def test_external_mcp_relax_allowed(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 1. Build a JanusMaskServer with a tmp state_dir
    state_dir = tmp_path / "state"
    tasks_dir = state_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    
    # 2. Build an external workdir and target file
    ext_workdir = tmp_path / "ext_workdir"
    ext_workdir.mkdir(parents=True, exist_ok=True)
    ext_file = ext_workdir / "some_file.py"
    
    # Write a per-task spec to <state>/tasks/current_task_default.json
    spec = {
        "task_id": "default",
        "working_dir": str(ext_workdir.resolve()),
        "files_touched": [str(ext_file.resolve())],
        "constraints": {"deterministic": True},
        "synthesis_target_type": "harness_module",
    }
    (tasks_dir / "current_task_default.json").write_text(json.dumps(spec), encoding="utf-8")
    
    # Ensure JANUSMASK_TASK_ID is unset
    monkeypatch.delenv("JANUSMASK_TASK_ID", raising=False)
    
    # Spy on rpc_submit_code.validate
    spy_calls = []
    orig_validate = rpc_submit_code.validate
    
    def spy_validate(code, *, allow_nondeterminism=False, relax_external_constructs=False):
        spy_calls.append(relax_external_constructs)
        return orig_validate(code, allow_nondeterminism=allow_nondeterminism, relax_external_constructs=relax_external_constructs)
        
    monkeypatch.setattr(rpc_submit_code, "validate", spy_validate)
    
    # Instantiate server and set task_read=True
    server = mcp_server.JanusMaskServer(agent_id="claude", state_dir=state_dir)
    server.task_read = True
    
    # Submit EVAL_CODE
    result = server.cmd_submit_code({
        "code": EVAL_CODE,
        "session_id": "x", "agent_identity": "claude",
        "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
    })
    
    # Test 1 assertions:
    # Under HEAD (pre-fix), relax_external_constructs is False/omitted, so eval is rejected.
    # On post-fix, relax_external_constructs is True, so result status must be accepted (no security violation).
    assert spy_calls, "rpc_submit_code.validate was not called"
    assert spy_calls[0] is True, f"Expected relax_external_constructs=True, got {spy_calls[0]}"
    
    violations = result.get("violations") or []
    security_violations = [
        v for v in violations
        if isinstance(v, dict) and "security" in str(v.get("rule", "")).lower()
    ]
    assert not security_violations, f"Expected no security violations, got: {violations!r}"
    assert result.get("status") == "accepted", f"Expected status 'accepted', got {result!r}"


def test_self_mcp_relax_still_rejected(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 1. Build a JanusMaskServer with a tmp state_dir
    state_dir = tmp_path / "state"
    tasks_dir = state_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    
    # Write a per-task spec for a SELF task (working_dir is None/absent)
    spec = {
        "task_id": "default",
        "working_dir": None,
        "files_touched": ["harness/mcp_server.py"],
        "constraints": {"deterministic": True},
        "synthesis_target_type": "harness_module",
    }
    (tasks_dir / "current_task_default.json").write_text(json.dumps(spec), encoding="utf-8")
    
    # Ensure JANUSMASK_TASK_ID is unset
    monkeypatch.delenv("JANUSMASK_TASK_ID", raising=False)
    
    # Spy on rpc_submit_code.validate
    spy_calls = []
    orig_validate = rpc_submit_code.validate
    
    def spy_validate(code, *, allow_nondeterminism=False, relax_external_constructs=False):
        spy_calls.append(relax_external_constructs)
        return orig_validate(code, allow_nondeterminism=allow_nondeterminism, relax_external_constructs=relax_external_constructs)
        
    monkeypatch.setattr(rpc_submit_code, "validate", spy_validate)
    
    # Instantiate server and set task_read=True
    server = mcp_server.JanusMaskServer(agent_id="claude", state_dir=state_dir)
    server.task_read = True
    
    # Submit EVAL_CODE
    result = server.cmd_submit_code({
        "code": EVAL_CODE,
        "session_id": "x", "agent_identity": "claude",
        "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
    })
    
    # Test 2 assertions:
    # Should always be rejected with a security violation
    assert spy_calls, "rpc_submit_code.validate was not called"
    assert spy_calls[0] is False, f"Expected relax_external_constructs=False, got {spy_calls[0]}"
    
    violations = result.get("violations") or []
    security_violations = [
        v for v in violations
        if isinstance(v, dict) and "security" in str(v.get("rule", "")).lower()
    ]
    assert security_violations, f"Expected a security violation for self task, got result: {result!r}"
    assert result.get("status") == "rejected", f"Expected status 'rejected', got {result!r}"
