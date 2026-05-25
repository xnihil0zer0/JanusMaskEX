import json
import os
import signal
import subprocess
import sys
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from harness.orchestrator import load_config, spawn_agent, run_both_agents, _boost_antigravity_mcp_config
from harness.autowork_daemon import suspend_parallel_workers, resume_parallel_workers

def test_antigravity_config_override(tmp_path):
    # Create a dummy config file with antigravity_mode: true
    config_data = {
        "synthesis": {
            "timeout_seconds": 600,
            "max_ast_retries": 3,
            "max_clarification_requests": 2,
            "clarification_timeout_sec": 60,
            "active_agents": ["claude", "gemini"],
            "antigravity_mode": True
        },
        "agents": {
            "antigravity": {
                "command": "agy",
                "args": ["-p", "--dangerously-skip-permissions", "--sandbox"]
            }
        }
    }
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(config_data, f)
        
    config = load_config(config_file)
    assert config["synthesis"]["active_agents"] == ["antigravity"]

def test_boost_antigravity_mcp_config(tmp_path, monkeypatch):
    # Mock home path to write in tmp_path
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    
    # Run _boost_antigravity_mcp_config
    state_dir = tmp_path / "state"
    _boost_antigravity_mcp_config(state_dir)
    
    # Verify the config exists
    mcp_config_path = fake_home / ".gemini" / "antigravity-cli" / "mcp_config.json"
    assert mcp_config_path.exists()
    
    with open(mcp_config_path, "r") as f:
        data = json.load(f)
    
    assert "janusmask" in data["mcpServers"]
    server_info = data["mcpServers"]["janusmask"]
    assert "args" in server_info
    assert "antigravity" in server_info["args"]
    assert str(state_dir.resolve()) in server_info["args"]

def test_sequential_execution_routing(tmp_path):
    config = {
        "synthesis": {
            "timeout_seconds": 600,
            "max_ast_retries": 3,
            "active_agents": ["antigravity"],
            "antigravity_mode": True
        },
        "agents": {
            "antigravity": {
                "command": "agy",
                "args": ["-p", "--dangerously-skip-permissions", "--sandbox"]
            }
        }
    }
    
    # Mock run_agent_phase to return a mock response
    with patch("harness.orchestrator.run_agent_phase") as mock_run:
        mock_run.side_effect = ["code_a", "code_b"]
        
        code_a, code_b = run_both_agents(
            "prompt_a", "prompt_b", config, tmp_path, 1, "synthesis"
        )
        
        assert code_a == "code_a"
        assert code_b == "code_b"
        
        # Verify run_agent_phase was called sequentially for antigravity
        mock_run.assert_any_call("antigravity", "prompt_a", config, tmp_path, 1, "synthesis")
        mock_run.assert_any_call("antigravity", "prompt_b", config, tmp_path, 1, "synthesis")

def test_process_suspension_logic(tmp_path):
    running_dir = tmp_path / "running"
    running_dir.mkdir(parents=True)
    
    # Write some dummy PIDs
    pid1_file = running_dir / "task-001.pid"
    pid2_file = running_dir / "task-002.pid"
    pid3_file = running_dir / "task-003.pid"
    
    pid1_file.write_text("11111\n")
    pid2_file.write_text("22222\n")
    pid3_file.write_text("33333\n")
    
    killed_signals = []
    def fake_kill(pid, sig):
        killed_signals.append((pid, sig))
        
    with patch("os.kill", side_effect=fake_kill):
        # Suspend all except current task-001
        suspend_parallel_workers(tmp_path, "task-001")
        assert (22222, signal.SIGSTOP) in killed_signals
        assert (33333, signal.SIGSTOP) in killed_signals
        assert (11111, signal.SIGSTOP) not in killed_signals
        
        killed_signals.clear()
        
        # Resume all except task-001
        resume_parallel_workers(tmp_path, "task-001")
        assert (22222, signal.SIGCONT) in killed_signals
        assert (33333, signal.SIGCONT) in killed_signals
        assert (11111, signal.SIGCONT) not in killed_signals

def test_autobrief_default_agent_antigravity(tmp_path):
    # Verify load_config overrides autobrief_default_agent
    config_data = {
        "synthesis": {
            "antigravity_mode": True
        },
        "control": {
            "autobrief_default_agent": "claude"
        }
    }
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(config_data, f)
    config = load_config(config_file)
    assert config["control"]["autobrief_default_agent"] == "antigravity"
