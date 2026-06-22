"""RED-first behavioral oracle for the blind-draft re-draft-once contract.

Pins ``harness.planner.blind_draft.run_blind_drafts`` to the rule: when ONE
planning agent's collected draft is ``(None, 'invalid')`` or ``(None,
'crashed')``, that single agent (and only it) is re-spawned EXACTLY once via the
single-agent ``run_agent_phase`` seam and its recovered draft replaces the
failed result, while ``'timeout'`` / ``'suspect_hallucination'`` / ``'ok'`` are
never retried.

This is a hermetic harness control-flow oracle: the REAL ``run_blind_drafts`` is
driven (never mocked), and only the spawn+collect seams are monkeypatched at the
``harness.planner.blind_draft.*`` namespace -- no real subprocess, no real
sleeps, no draft files.

On current HEAD ``run_blind_drafts`` never calls ``run_agent_phase`` and returns
the failed ``(None, status)`` verbatim, so the recovery tests are RED; they go
GREEN once planner-redraft-once-impl lands. ``run_agent_phase`` is patched with
``raising=False`` so HEAD (where the module has no such binding yet) fails at the
behavioural assertions rather than erroring at setup.
"""
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import pytest
from harness.planner.blind_draft import run_blind_drafts, BlindDraftResult
from harness.planner.brief_loader import PlanningBrief
Collected = Tuple[Optional[Dict[str, Any]], str]

@pytest.fixture
def dummy_brief() -> PlanningBrief:
    """Mirror tests/planner/test_blind_draft.py: an in-memory leaf brief."""
    return PlanningBrief(title='Test Brief', scope='Test Scope', non_goals='None', inputs='Nothing', deliverables='JSON', raw_text='Full text', source_path=Path('path/to/brief'), sha256='abcdef')

@pytest.fixture
def base_config() -> Dict[str, Any]:
    """Mirror tests/planner/test_blind_draft.py base_config."""
    return {'agents': {'claude': {'env': {}}, 'gemini': {'env': {}}}, 'synthesis': {'timeout_seconds': 10}}

def _make_dual_spawn(record: List[Tuple[Any, ...]]) -> Callable[..., Tuple[None, None]]:
    """Stub for the initial dual spawn; records each call, returns (None, None)."""

    def _dual(*args: Any, **kwargs: Any) -> Tuple[None, None]:
        record.append(args)
        return (None, None)
    return _dual

def _make_phase(calls: List[str]) -> Callable[..., str]:
    """Stub for the single-agent re-spawn seam.

    Appends the spawned agent (positional first arg, kwarg fallback) to ``calls``
    and returns a truthy 'submitted code' so the caller will re-collect.
    """

    def _phase(*args: Any, **kwargs: Any) -> str:
        agent = args[0] if args else kwargs.get('agent')
        calls.append(agent)
        return 'code'
    return _phase

def _make_collect(seq: Dict[str, List[Collected]], counters: Dict[str, int]) -> Callable[..., Collected]:
    """Per-agent SEQUENCED collect stub.

    ``seq`` maps agent -> list of ``(draft|None, status)`` returned on that
    agent's successive collects; ``counters`` is mutated in place so the caller
    can assert how many times each agent was collected. Past the end of an
    agent's list the final entry is repeated.
    """

    def _collect(*args: Any, **kwargs: Any) -> Collected:
        agent = args[0] if args else kwargs.get('agent')
        i = counters.get(agent, 0)
        counters[agent] = i + 1
        results = seq.get(agent, [(None, 'crashed')])
        return results[i] if i < len(results) else results[-1]
    return _collect

def _install_seams(monkeypatch: pytest.MonkeyPatch, seq: Dict[str, List[Collected]], calls: List[str], dual_record: List[Tuple[Any, ...]]) -> Dict[str, int]:
    """Patch all three seams at the harness.planner.blind_draft namespace.

    ``run_agent_phase`` uses ``raising=False`` because HEAD has no such module
    binding yet (planner-redraft-once-impl introduces it); the other two exist on
    HEAD and are patched with ``raising=True`` to guard against name drift.
    Returns the per-agent collect counter dict.
    """
    counters: Dict[str, int] = {'claude': 0, 'gemini': 0}
    monkeypatch.setattr('harness.planner.blind_draft.run_both_agents', _make_dual_spawn(dual_record), raising=True)
    monkeypatch.setattr('harness.planner.blind_draft.run_agent_phase', _make_phase(calls), raising=False)
    monkeypatch.setattr('harness.planner.blind_draft.collect_agent_draft', _make_collect(seq, counters), raising=True)
    return counters

def test_recover_invalid_respawns_claude_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_brief: PlanningBrief, base_config: Dict[str, Any]) -> None:
    calls: List[str] = []
    dual: List[Tuple[Any, ...]] = []
    draft_g = {'tasks': [{'id': 'g'}]}
    recovered = {'tasks': [{'id': 'c-retry'}]}
    _install_seams(monkeypatch, {'claude': [(None, 'invalid'), (recovered, 'ok')], 'gemini': [(draft_g, 'ok')]}, calls, dual)
    res = run_blind_drafts(dummy_brief, base_config, tmp_path)
    assert isinstance(res, BlindDraftResult)
    assert calls == ['claude']
    assert res.claude_status == 'ok'
    assert res.claude_draft == recovered
    assert res.gemini_status == 'ok'
    assert res.gemini_draft == draft_g

def test_recover_crashed_respawns_claude_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_brief: PlanningBrief, base_config: Dict[str, Any]) -> None:
    calls: List[str] = []
    dual: List[Tuple[Any, ...]] = []
    draft_g = {'tasks': [{'id': 'g'}]}
    recovered = {'tasks': [{'id': 'c-retry'}]}
    _install_seams(monkeypatch, {'claude': [(None, 'crashed'), (recovered, 'ok')], 'gemini': [(draft_g, 'ok')]}, calls, dual)
    res = run_blind_drafts(dummy_brief, base_config, tmp_path)
    assert calls == ['claude']
    assert res.claude_status == 'ok'
    assert res.claude_draft == recovered
    assert res.gemini_status == 'ok'
    assert res.gemini_draft == draft_g

def test_respawn_only_failed_agent_single_element_list(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_brief: PlanningBrief, base_config: Dict[str, Any]) -> None:
    calls: List[str] = []
    dual: List[Tuple[Any, ...]] = []
    draft_g = {'tasks': [{'id': 'g'}]}
    recovered = {'tasks': [{'id': 'c-retry'}]}
    _install_seams(monkeypatch, {'claude': [(None, 'invalid'), (recovered, 'ok')], 'gemini': [(draft_g, 'ok')]}, calls, dual)
    run_blind_drafts(dummy_brief, base_config, tmp_path)
    assert calls == ['claude']
    assert 'gemini' not in calls
    assert len(calls) == 1

def test_no_retry_on_timeout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_brief: PlanningBrief, base_config: Dict[str, Any]) -> None:
    calls: List[str] = []
    dual: List[Tuple[Any, ...]] = []
    draft_g = {'tasks': [{'id': 'g'}]}
    _install_seams(monkeypatch, {'claude': [(None, 'timeout')], 'gemini': [(draft_g, 'ok')]}, calls, dual)
    res = run_blind_drafts(dummy_brief, base_config, tmp_path)
    assert calls == []
    assert res.claude_status == 'timeout'
    assert res.claude_draft is None
    assert res.gemini_status == 'ok'
    assert res.gemini_draft == draft_g

def test_no_retry_on_suspect_hallucination(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_brief: PlanningBrief, base_config: Dict[str, Any]) -> None:
    calls: List[str] = []
    dual: List[Tuple[Any, ...]] = []
    draft_g = {'tasks': [{'id': 'g'}]}
    _install_seams(monkeypatch, {'claude': [(None, 'suspect_hallucination')], 'gemini': [(draft_g, 'ok')]}, calls, dual)
    res = run_blind_drafts(dummy_brief, base_config, tmp_path)
    assert calls == []
    assert res.claude_status == 'suspect_hallucination'
    assert res.claude_draft is None
    assert res.gemini_status == 'ok'
    assert res.gemini_draft == draft_g

def test_retry_also_fails_preserves_original_failed_claude(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_brief: PlanningBrief, base_config: Dict[str, Any]) -> None:
    calls: List[str] = []
    dual: List[Tuple[Any, ...]] = []
    draft_g = {'tasks': [{'id': 'g'}]}
    _install_seams(monkeypatch, {'claude': [(None, 'invalid'), (None, 'crashed')], 'gemini': [(draft_g, 'ok')]}, calls, dual)
    res = run_blind_drafts(dummy_brief, base_config, tmp_path)
    assert calls == ['claude']
    assert res.claude_draft is None
    assert res.claude_status in ('invalid', 'crashed')
    assert res.gemini_status == 'ok'
    assert res.gemini_draft == draft_g

def test_healthy_gemini_untouched_when_claude_recovered(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_brief: PlanningBrief, base_config: Dict[str, Any]) -> None:
    calls: List[str] = []
    dual: List[Tuple[Any, ...]] = []
    draft_g = {'tasks': [{'id': 'gemini-original'}]}
    recovered = {'tasks': [{'id': 'c-retry'}]}
    counters = _install_seams(monkeypatch, {'claude': [(None, 'invalid'), (recovered, 'ok')], 'gemini': [(draft_g, 'ok')]}, calls, dual)
    res = run_blind_drafts(dummy_brief, base_config, tmp_path)
    assert calls == ['claude']
    assert counters['gemini'] == 1
    assert res.gemini_status == 'ok'
    assert res.gemini_draft == draft_g
    assert res.claude_status == 'ok'
    assert res.claude_draft == recovered

def test_deterministic_no_subprocess_no_sleep(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_brief: PlanningBrief, base_config: Dict[str, Any]) -> None:
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
    counters = _install_seams(monkeypatch, {'claude': [(None, 'invalid'), (recovered, 'ok')], 'gemini': [(draft_g, 'ok')]}, calls, dual)
    res = run_blind_drafts(dummy_brief, base_config, tmp_path)
    assert len(dual) == 1
    assert calls == ['claude']
    assert counters['claude'] == 2
    assert counters['gemini'] == 1
    assert sleeps == []
    assert res.claude_status == 'ok'
    assert res.claude_draft == recovered

def test_run_both_agents_called_once_no_second_dual_spawn(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_brief: PlanningBrief, base_config: Dict[str, Any]) -> None:
    calls: List[str] = []
    dual: List[Tuple[Any, ...]] = []
    draft_g = {'tasks': [{'id': 'g'}]}
    recovered = {'tasks': [{'id': 'c-retry'}]}
    _install_seams(monkeypatch, {'claude': [(None, 'invalid'), (recovered, 'ok')], 'gemini': [(draft_g, 'ok')]}, calls, dual)
    res = run_blind_drafts(dummy_brief, base_config, tmp_path)
    assert len(dual) == 1
    assert calls == ['claude']
    assert res.claude_status == 'ok'
    assert res.claude_draft == recovered

def test_no_retry_on_ok_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_brief: PlanningBrief, base_config: Dict[str, Any]) -> None:
    calls: List[str] = []
    dual: List[Tuple[Any, ...]] = []
    draft_c = {'tasks': [{'id': 'c'}]}
    draft_g = {'tasks': [{'id': 'g'}]}
    counters = _install_seams(monkeypatch, {'claude': [(draft_c, 'ok')], 'gemini': [(draft_g, 'ok')]}, calls, dual)
    res = run_blind_drafts(dummy_brief, base_config, tmp_path)
    assert calls == []
    assert counters['claude'] == 1
    assert counters['gemini'] == 1
    assert res.claude_status == 'ok'
    assert res.claude_draft == draft_c
    assert res.gemini_status == 'ok'
    assert res.gemini_draft == draft_g

def test_collect_recollects_only_failed_agent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, dummy_brief: PlanningBrief, base_config: Dict[str, Any]) -> None:
    calls: List[str] = []
    dual: List[Tuple[Any, ...]] = []
    draft_g = {'tasks': [{'id': 'g'}]}
    recovered = {'tasks': [{'id': 'c-retry'}]}
    counters = _install_seams(monkeypatch, {'claude': [(None, 'invalid'), (recovered, 'ok')], 'gemini': [(draft_g, 'ok')]}, calls, dual)
    run_blind_drafts(dummy_brief, base_config, tmp_path)
    assert counters['claude'] == 2
    assert counters['gemini'] == 1
    assert calls == ['claude']