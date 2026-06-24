"""Adversarial retry budget test suite for blind drafts.

Tests the bounded retry budget logic for planning blind drafts when agents
encounter transient crashes or invalid submissions.
"""
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import pytest
from harness.planner.blind_draft import run_blind_drafts, BlindDraftResult
from harness.planner.brief_loader import PlanningBrief
Collected = Tuple[Optional[Dict[str, Any]], str]

@pytest.fixture
def dummy_brief() -> PlanningBrief:
    """An in-memory leaf brief for testing."""
    return PlanningBrief(title='Test Brief', scope='Test Scope', non_goals='None', inputs='Nothing', deliverables='JSON', raw_text='Full text', source_path=Path('path/to/brief'), sha256='abcdef')

@pytest.fixture
def base_config() -> Dict[str, Any]:
    """Base configuration for planning."""
    return {'agents': {'claude': {'env': {}}, 'gemini': {'env': {}}}, 'synthesis': {'timeout_seconds': 10}}

def _make_dual_spawn(record: List[Tuple[Any, ...]]) -> Callable[..., Tuple[None, None]]:
    """Stub for the initial dual spawn; records each call, returns (None, None)."""

    def _dual(*args: Any, **kwargs: Any) -> Tuple[None, None]:
        record.append(args)
        return (None, None)
    return _dual

def _make_phase(calls: List[str]) -> Callable[..., str]:
    """Stub for the single-agent re-spawn seam."""

    def _phase(*args: Any, **kwargs: Any) -> str:
        agent = args[0] if args else kwargs.get('agent')
        calls.append(agent)
        return 'code'
    return _phase

def _make_collect(seq: Dict[str, List[Collected]], counters: Dict[str, int]) -> Callable[..., Collected]:
    """Per-agent sequenced collect stub."""

    def _collect(*args: Any, **kwargs: Any) -> Collected:
        agent = args[0] if args else kwargs.get('agent')
        i = counters.get(agent, 0)
        counters[agent] = i + 1
        results = seq.get(agent, [(None, 'crashed')])
        return results[i] if i < len(results) else results[-1]
    return _collect

def _install_seams(monkeypatch: pytest.MonkeyPatch, seq: Dict[str, List[Collected]], calls: List[str], dual_record: List[Tuple[Any, ...]]) -> Dict[str, int]:
    """Patch seams at the harness.planner.blind_draft namespace."""
    counters: Dict[str, int] = {'claude': 0, 'gemini': 0}
    monkeypatch.setattr('harness.planner.blind_draft.run_both_agents', _make_dual_spawn(dual_record), raising=True)
    monkeypatch.setattr('harness.planner.blind_draft.run_agent_phase', _make_phase(calls), raising=False)
    monkeypatch.setattr('harness.planner.blind_draft.collect_agent_draft', _make_collect(seq, counters), raising=True)
    return counters

def test_recover_up_to_three_attempts_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_brief: PlanningBrief, base_config: Dict[str, Any]) -> None:
    """TEST A: Verify recovery up to 3 attempts, succeeding on the 3rd retry."""
    calls: List[str] = []
    dual: List[Tuple[Any, ...]] = []
    draft_g = {'tasks': [{'id': 'g'}]}
    recovered = {'tasks': [{'id': 'c-retry'}]}
    _install_seams(monkeypatch, {'claude': [(None, 'crashed'), (None, 'invalid'), (None, 'crashed'), (recovered, 'ok')], 'gemini': [(draft_g, 'ok')]}, calls, dual)
    res = run_blind_drafts(dummy_brief, base_config, tmp_path)
    assert isinstance(res, BlindDraftResult)
    assert calls == ['claude', 'claude', 'claude']
    assert res.claude_status == 'ok'
    assert res.claude_draft == recovered
    assert res.gemini_status == 'ok'
    assert res.gemini_draft == draft_g

def test_retry_budget_cap_gives_up_after_three(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_brief: PlanningBrief, base_config: Dict[str, Any]) -> None:
    """TEST B: Verify that budget cap of 3 attempts is enforced."""
    calls: List[str] = []
    dual: List[Tuple[Any, ...]] = []
    draft_g = {'tasks': [{'id': 'g'}]}
    _install_seams(monkeypatch, {'claude': [(None, 'crashed'), (None, 'invalid'), (None, 'crashed'), (None, 'crashed')], 'gemini': [(draft_g, 'ok')]}, calls, dual)
    res = run_blind_drafts(dummy_brief, base_config, tmp_path)
    assert isinstance(res, BlindDraftResult)
    assert calls == ['claude', 'claude', 'claude']
    assert res.claude_status in ('crashed', 'invalid')
    assert res.claude_draft is None
    assert res.gemini_status == 'ok'
    assert res.gemini_draft == draft_g

def test_no_retry_on_non_retryable_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_brief: PlanningBrief, base_config: Dict[str, Any]) -> None:
    """TEST C: Verify that non-retryable statuses are never retried."""
    calls: List[str] = []
    dual: List[Tuple[Any, ...]] = []
    _install_seams(monkeypatch, {'claude': [(None, 'timeout')], 'gemini': [(None, 'suspect_hallucination')]}, calls, dual)
    res = run_blind_drafts(dummy_brief, base_config, tmp_path)
    assert isinstance(res, BlindDraftResult)
    assert calls == []
    assert res.claude_status == 'timeout'
    assert res.claude_draft is None
    assert res.gemini_status == 'suspect_hallucination'
    assert res.gemini_draft is None

def test_healthy_agent_untouched(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_brief: PlanningBrief, base_config: Dict[str, Any]) -> None:
    """TEST D: Verify that healthy agents are untouched."""
    calls: List[str] = []
    dual: List[Tuple[Any, ...]] = []
    draft_c = {'tasks': [{'id': 'c'}]}
    draft_g = {'tasks': [{'id': 'g'}]}
    counters = _install_seams(monkeypatch, {'claude': [(draft_c, 'ok')], 'gemini': [(draft_g, 'ok')]}, calls, dual)
    res = run_blind_drafts(dummy_brief, base_config, tmp_path)
    assert isinstance(res, BlindDraftResult)
    assert calls == []
    assert counters['claude'] == 1
    assert counters['gemini'] == 1
    assert res.claude_status == 'ok'
    assert res.claude_draft == draft_c
    assert res.gemini_status == 'ok'
    assert res.gemini_draft == draft_g

def test_blind_draft_retry_budget_recover_on_first_retry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_brief: PlanningBrief, base_config: Dict[str, Any]) -> None:
    """Verify recovery on the first retry attempt."""
    calls: List[str] = []
    dual: List[Tuple[Any, ...]] = []
    draft_g = {'tasks': [{'id': 'g'}]}
    recovered = {'tasks': [{'id': 'c-retry-1'}]}
    _install_seams(monkeypatch, {'claude': [(None, 'crashed'), (recovered, 'ok')], 'gemini': [(draft_g, 'ok')]}, calls, dual)
    res = run_blind_drafts(dummy_brief, base_config, tmp_path)
    assert isinstance(res, BlindDraftResult)
    assert calls == ['claude']
    assert res.claude_status == 'ok'
    assert res.claude_draft == recovered

def test_blind_draft_retry_budget_recover_on_second_retry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_brief: PlanningBrief, base_config: Dict[str, Any]) -> None:
    """Verify recovery on the second retry attempt."""
    calls: List[str] = []
    dual: List[Tuple[Any, ...]] = []
    draft_g = {'tasks': [{'id': 'g'}]}
    recovered = {'tasks': [{'id': 'c-retry-2'}]}
    _install_seams(monkeypatch, {'claude': [(None, 'invalid'), (None, 'crashed'), (recovered, 'ok')], 'gemini': [(draft_g, 'ok')]}, calls, dual)
    res = run_blind_drafts(dummy_brief, base_config, tmp_path)
    assert isinstance(res, BlindDraftResult)
    assert calls == ['claude', 'claude']
    assert res.claude_status == 'ok'
    assert res.claude_draft == recovered

def test_blind_draft_retry_budget_gemini_timeout_no_retry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_brief: PlanningBrief, base_config: Dict[str, Any]) -> None:
    """Verify Gemini is not retried on timeout."""
    calls: List[str] = []
    dual: List[Tuple[Any, ...]] = []
    draft_c = {'tasks': [{'id': 'c'}]}
    _install_seams(monkeypatch, {'claude': [(draft_c, 'ok')], 'gemini': [(None, 'timeout')]}, calls, dual)
    res = run_blind_drafts(dummy_brief, base_config, tmp_path)
    assert isinstance(res, BlindDraftResult)
    assert calls == []
    assert res.gemini_status == 'timeout'
    assert res.gemini_draft is None

def test_blind_draft_retry_budget_gemini_hallucination_no_retry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_brief: PlanningBrief, base_config: Dict[str, Any]) -> None:
    """Verify Gemini is not retried on suspect_hallucination."""
    calls: List[str] = []
    dual: List[Tuple[Any, ...]] = []
    draft_c = {'tasks': [{'id': 'c'}]}
    _install_seams(monkeypatch, {'claude': [(draft_c, 'ok')], 'gemini': [(None, 'suspect_hallucination')]}, calls, dual)
    res = run_blind_drafts(dummy_brief, base_config, tmp_path)
    assert isinstance(res, BlindDraftResult)
    assert calls == []
    assert res.gemini_status == 'suspect_hallucination'
    assert res.gemini_draft is None

def test_blind_draft_retry_budget_both_agents_fail_and_recover(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_brief: PlanningBrief, base_config: Dict[str, Any]) -> None:
    """Verify that both agents can recover when failing initially."""
    calls: List[str] = []
    dual: List[Tuple[Any, ...]] = []
    recovered_c = {'tasks': [{'id': 'c-recovered'}]}
    recovered_g = {'tasks': [{'id': 'g-recovered'}]}
    _install_seams(monkeypatch, {'claude': [(None, 'crashed'), (None, 'invalid'), (recovered_c, 'ok')], 'gemini': [(None, 'invalid'), (recovered_g, 'ok')]}, calls, dual)
    res = run_blind_drafts(dummy_brief, base_config, tmp_path)
    assert isinstance(res, BlindDraftResult)
    assert calls.count('claude') == 2
    assert calls.count('gemini') == 1
    assert res.claude_status == 'ok'
    assert res.claude_draft == recovered_c
    assert res.gemini_status == 'ok'
    assert res.gemini_draft == recovered_g

def test_blind_draft_retry_budget_both_agents_fail_and_exhaust(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_brief: PlanningBrief, base_config: Dict[str, Any]) -> None:
    """Verify that both agents exhaust budget when failing repeatedly."""
    calls: List[str] = []
    dual: List[Tuple[Any, ...]] = []
    _install_seams(monkeypatch, {'claude': [(None, 'crashed'), (None, 'invalid'), (None, 'crashed'), (None, 'invalid')], 'gemini': [(None, 'invalid'), (None, 'crashed'), (None, 'invalid'), (None, 'crashed')]}, calls, dual)
    res = run_blind_drafts(dummy_brief, base_config, tmp_path)
    assert isinstance(res, BlindDraftResult)
    assert calls.count('claude') == 3
    assert calls.count('gemini') == 3
    assert res.claude_status in ('crashed', 'invalid')
    assert res.claude_draft is None
    assert res.gemini_status in ('crashed', 'invalid')
    assert res.gemini_draft is None

def test_blind_draft_retry_budget_deterministic_no_subprocess_no_sleep(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_brief: PlanningBrief, base_config: Dict[str, Any]) -> None:
    """Verify that no subprocesses or sleep events occur during retries."""
    import subprocess
    import time
    sleeps: List[float] = []
    monkeypatch.setattr(time, 'sleep', lambda s: sleeps.append(s))

    def _no_subprocess(*args: Any, **kwargs: Any):
        raise AssertionError('real subprocess invoked; seams not hermetic')
    monkeypatch.setattr(subprocess, 'Popen', _no_subprocess, raising=True)
    monkeypatch.setattr(subprocess, 'run', _no_subprocess, raising=True)
    calls: List[str] = []
    dual: List[Tuple[Any, ...]] = []
    draft_g = {'tasks': [{'id': 'g'}]}
    recovered = {'tasks': [{'id': 'c-retry'}]}
    counters = _install_seams(monkeypatch, {'claude': [(None, 'crashed'), (None, 'invalid'), (recovered, 'ok')], 'gemini': [(draft_g, 'ok')]}, calls, dual)
    res = run_blind_drafts(dummy_brief, base_config, tmp_path)
    assert len(dual) == 1
    assert calls == ['claude', 'claude']
    assert counters['claude'] == 3
    assert counters['gemini'] == 1
    assert sleeps == []
    assert res.claude_status == 'ok'
    assert res.claude_draft == recovered

def test_blind_draft_retry_budget_healthy_gemini_untouched_when_claude_retried(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_brief: PlanningBrief, base_config: Dict[str, Any]) -> None:
    """Verify that healthy Gemini remains untouched while Claude retries."""
    calls: List[str] = []
    dual: List[Tuple[Any, ...]] = []
    draft_g = {'tasks': [{'id': 'gemini-original'}]}
    recovered_c = {'tasks': [{'id': 'c-retry'}]}
    counters = _install_seams(monkeypatch, {'claude': [(None, 'invalid'), (recovered_c, 'ok')], 'gemini': [(draft_g, 'ok')]}, calls, dual)
    res = run_blind_drafts(dummy_brief, base_config, tmp_path)
    assert isinstance(res, BlindDraftResult)
    assert calls == ['claude']
    assert counters['gemini'] == 1
    assert res.gemini_status == 'ok'
    assert res.gemini_draft == draft_g
    assert res.claude_status == 'ok'
    assert res.claude_draft == recovered_c

def test_blind_draft_retry_budget_stops_on_non_retryable_during_retry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_brief: PlanningBrief, base_config: Dict[str, Any]) -> None:
    """Verify that retrying stops immediately if a non-retryable status is returned during a retry."""
    calls: List[str] = []
    dual: List[Tuple[Any, ...]] = []
    _install_seams(monkeypatch, {'claude': [(None, 'crashed'), (None, 'timeout'), (None, 'crashed')], 'gemini': [({'tasks': []}, 'ok')]}, calls, dual)
    res = run_blind_drafts(dummy_brief, base_config, tmp_path)
    assert isinstance(res, BlindDraftResult)
    assert calls == ['claude']
    assert res.claude_status == 'timeout'
    assert res.claude_draft is None