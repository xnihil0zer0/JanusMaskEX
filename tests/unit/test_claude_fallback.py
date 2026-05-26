"""Unit tests for Claude rate limit fallback logic in orchestrator.py."""
import pytest
from pathlib import Path
from typing import Any
from harness.orchestrator import run_both_agents

def test_claude_fallback_triggered(monkeypatch):
    """Test that when the claude agent returns None, it triggers the fallback to claude_fallback."""
    calls = []

    def mock_run_agent_phase(agent: str, prompt: str, config: dict[str, Any], state_dir: Path, round_number: int, phase_name: str, max_retries: int = 3) -> str | None:
        calls.append(agent)
        if agent == 'claude':
            return None
        elif agent == 'claude_fallback':
            return 'fallback_code'
        elif agent == 'gemini':
            return 'gemini_code'
        return None

    monkeypatch.setattr("harness.orchestrator.run_agent_phase", mock_run_agent_phase)

    config = {
        'synthesis': {
            'active_agents': ['claude', 'gemini'],
            'antigravity_mode': True,
            'timeout_seconds': 10
        }
    }

    # 1. Test sequential execution fallback
    calls.clear()
    res_claude, res_gemini = run_both_agents(
        prompt_claude="prompt_claude",
        prompt_gemini="prompt_gemini",
        config=config,
        state_dir=Path("/tmp"),
        round_number=1,
        phase_name="test_phase"
    )
    assert res_claude == 'fallback_code'
    assert res_gemini == 'gemini_code'
    assert calls == ['claude', 'claude_fallback', 'gemini']

    # 2. Test parallel execution fallback
    config['synthesis']['antigravity_mode'] = False
    calls.clear()
    res_claude, res_gemini = run_both_agents(
        prompt_claude="prompt_claude",
        prompt_gemini="prompt_gemini",
        config=config,
        state_dir=Path("/tmp"),
        round_number=1,
        phase_name="test_phase"
    )
    assert res_claude == 'fallback_code'
    assert res_gemini == 'gemini_code'
    assert set(calls[:2]) == {'claude', 'gemini'}
    assert calls[2] == 'claude_fallback'
    assert len(calls) == 3

def test_claude_fallback_not_triggered(monkeypatch):
    """Test that when the claude agent succeeds (non-None), the fallback to claude_fallback is not triggered."""
    calls = []

    def mock_run_agent_phase(agent: str, prompt: str, config: dict[str, Any], state_dir: Path, round_number: int, phase_name: str, max_retries: int = 3) -> str | None:
        calls.append(agent)
        if agent == 'claude':
            return 'claude_code'
        elif agent == 'gemini':
            return 'gemini_code'
        return None

    monkeypatch.setattr("harness.orchestrator.run_agent_phase", mock_run_agent_phase)

    config = {
        'synthesis': {
            'active_agents': ['claude', 'gemini'],
            'antigravity_mode': True,
            'timeout_seconds': 10
        }
    }

    # 1. Test sequential execution - no fallback
    calls.clear()
    res_claude, res_gemini = run_both_agents(
        prompt_claude="prompt_claude",
        prompt_gemini="prompt_gemini",
        config=config,
        state_dir=Path("/tmp"),
        round_number=1,
        phase_name="test_phase"
    )
    assert res_claude == 'claude_code'
    assert res_gemini == 'gemini_code'
    assert calls == ['claude', 'gemini']

    # 2. Test parallel execution - no fallback
    config['synthesis']['antigravity_mode'] = False
    calls.clear()
    res_claude, res_gemini = run_both_agents(
        prompt_claude="prompt_claude",
        prompt_gemini="prompt_gemini",
        config=config,
        state_dir=Path("/tmp"),
        round_number=1,
        phase_name="test_phase"
    )
    assert res_claude == 'claude_code'
    assert res_gemini == 'gemini_code'
    assert set(calls) == {'claude', 'gemini'}
    assert len(calls) == 2

def test_claude_fallback_error_handling(monkeypatch):
    """Test that errors raised during the fallback are caught and None is returned cleanly."""
    calls = []

    def mock_run_agent_phase(agent: str, prompt: str, config: dict[str, Any], state_dir: Path, round_number: int, phase_name: str, max_retries: int = 3) -> str | None:
        calls.append(agent)
        if agent == 'claude':
            return None
        elif agent == 'claude_fallback':
            raise RuntimeError("Fallback crashed!")
        elif agent == 'gemini':
            return 'gemini_code'
        return None

    monkeypatch.setattr("harness.orchestrator.run_agent_phase", mock_run_agent_phase)

    config = {
        'synthesis': {
            'active_agents': ['claude', 'gemini'],
            'antigravity_mode': True,
            'timeout_seconds': 10
        }
    }

    # 1. Test sequential execution fallback exception handling
    calls.clear()
    res_claude, res_gemini = run_both_agents(
        prompt_claude="prompt_claude",
        prompt_gemini="prompt_gemini",
        config=config,
        state_dir=Path("/tmp"),
        round_number=1,
        phase_name="test_phase"
    )
    assert res_claude is None
    assert res_gemini == 'gemini_code'
    assert calls == ['claude', 'claude_fallback', 'gemini']

    # 2. Test parallel execution fallback exception handling
    config['synthesis']['antigravity_mode'] = False
    calls.clear()
    res_claude, res_gemini = run_both_agents(
        prompt_claude="prompt_claude",
        prompt_gemini="prompt_gemini",
        config=config,
        state_dir=Path("/tmp"),
        round_number=1,
        phase_name="test_phase"
    )
    assert res_claude is None
    assert res_gemini == 'gemini_code'
    assert set(calls[:2]) == {'claude', 'gemini'}
    assert calls[2] == 'claude_fallback'
    assert len(calls) == 3
