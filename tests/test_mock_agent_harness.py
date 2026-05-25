import pytest
import time
import json
import subprocess
from unittest import mock
from pathlib import Path

from tests.mocks.agent_harness import (
    MockAgent, 
    paired_mocks,
    ScriptExhaustedError,
    ScriptedCrashError,
    TurnOrderError,
    TurnMismatchError
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "mock_agent_scripts"

@pytest.fixture
def claude_script():
    return FIXTURES_DIR / "basic_claude.json"

@pytest.fixture
def gemini_script():
    return FIXTURES_DIR / "basic_gemini.json"

@pytest.fixture
def invalid_script():
    return FIXTURES_DIR / "invalid.json"

def test_mock_agent_returns_scripted_responses_in_order(claude_script):
    agent = MockAgent(fixture_path=claude_script)
    r1 = agent.next_response("Prompt 1")
    assert r1["response"] == "Hello from Claude turn 1"
    
    r2 = agent.next_response("Prompt 2")
    assert r2["response"] == "Hello from Claude turn 2"
    
    with pytest.raises(ScriptExhaustedError):
        agent.next_response("Prompt 3")

def test_mock_agent_crash_after_n_chars(claude_script):
    agent = MockAgent(fixture_path=claude_script, crash_after_n_chars=5)
    with pytest.raises(ScriptedCrashError) as exc_info:
        agent.next_response("Prompt 1")
    
    assert exc_info.value.partial_output == "Hello"
    assert exc_info.value.offset == 5

def test_mock_agent_invalid_json(claude_script):
    agent = MockAgent(fixture_path=claude_script, return_invalid_json=True)
    out = agent.next_response("Prompt 1")
    assert isinstance(out, str)
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)
    assert '{"this_is_invalid_json": ' in out

def test_mock_agent_hang_exceeds_deadline(claude_script):
    agent = MockAgent(fixture_path=claude_script, hang_for_seconds=0.1)
    start = time.time()
    r = agent.next_response("Prompt")
    duration = time.time() - start
    assert duration >= 0.1
    assert r["response"] == "Hello from Claude turn 1"

def test_paired_mocks_turn_tracking(claude_script, gemini_script):
    with paired_mocks(claude_script, gemini_script) as (claude, gemini):
        claude.next_response("P1")
        gemini.next_response("P2")
        claude.next_response("P3")
        gemini.next_response("P4")
        
        assert len(claude.received_prompts) == 2
        assert len(gemini.received_prompts) == 2

    # Verify that it raises TurnMismatchError if out of sync
    with pytest.raises(TurnMismatchError):
        with paired_mocks(claude_script, gemini_script) as (claude, gemini):
            claude.next_response("P1")

    # Verify order enforcement
    with pytest.raises(TurnOrderError):
        with paired_mocks(claude_script, gemini_script) as (claude, gemini):
            gemini.next_response("P1")

def test_mock_records_received_prompts(claude_script):
    agent = MockAgent(fixture_path=claude_script)
    agent.next_response("A")
    agent.next_response("B")
    assert agent.received_prompts == ["A", "B"]

def test_fixture_load_failure_raises_at_construction(invalid_script):
    with pytest.raises(FileNotFoundError):
        MockAgent(fixture_path=FIXTURES_DIR / "does_not_exist.json")
        
    with pytest.raises(json.JSONDecodeError):
        MockAgent(fixture_path=invalid_script)

def test_mock_agent_reset_clears_received_prompts(claude_script):
    agent = MockAgent(fixture_path=claude_script)
    agent.next_response("A")
    assert len(agent.received_prompts) == 1
    
    agent.reset()
    assert len(agent.received_prompts) == 0
    
    r = agent.next_response("B")
    assert r["response"] == "Hello from Claude turn 1"

def test_mock_agent_no_subprocess_spawn(claude_script):
    with mock.patch("subprocess.Popen") as mock_popen, mock.patch("subprocess.run") as mock_run:
        agent = MockAgent(fixture_path=claude_script)
        agent.next_response("A")
        
        mock_popen.assert_not_called()
        mock_run.assert_not_called()

def test_mock_harness_drop_in_for_real_agent_call(claude_script):
    def do_agent_call(agent_like):
        return agent_like.next_response("Hello")
        
    mock_agent = MockAgent(fixture_path=claude_script)
    result = do_agent_call(mock_agent)
    assert result["response"] == "Hello from Claude turn 1"

def test_script_exhaustion_does_not_return_none(claude_script):
    agent = MockAgent(fixture_path=claude_script)
    agent.next_response("A")
    agent.next_response("B")
    
    with pytest.raises(ScriptExhaustedError):
        res = agent.next_response("C")
        assert res is not None
