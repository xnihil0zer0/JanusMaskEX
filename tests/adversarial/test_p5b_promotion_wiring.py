"""RED oracle for P5b single-agent promotion wiring.
Verifies that:
1. When exactly one agent is valid, ceiling is met, enable_single_agent_promotion=True, and operator approval is provided, the lone AST-valid agent is promoted and both agents are set to this valid code.
2. Control: when enable_single_agent_promotion=False, no promotion occurs and task is blocked.
3. Control: when target is sensitive (harness_self_fix) and no operator approval is provided, no promotion occurs and task is blocked.
"""
from __future__ import annotations
import json
import pathlib
import pytest

def _setup_and_run_worker(
    tmp_path,
    monkeypatch,
    task_id: str,
    enable_single_agent_promotion: bool,
    preseed_attempts: int,
    approval_val: str | None,
    meta_task_type: str = 'harness_self_fix',
    files_touched: list[str] = None
) -> dict:
    if files_touched is None:
        files_touched = ['harness/orchestrator_worker.py']
        
    state_dir = tmp_path / 'state'
    state_dir.mkdir(exist_ok=True)
    
    # 1. Write task JSON
    tasks_dir = state_dir / 'tasks'
    tasks_dir.mkdir(exist_ok=True)
    task = {
        'task_id': task_id,
        'title': 'p5b promotion wiring probe',
        'meta_task_type': meta_task_type,
        'partial_edit': True,
        'files_touched': files_touched,
        'acceptance_criteria': ['noop'],
    }
    (tasks_dir / f'{task_id}.json').write_text(json.dumps(task), encoding='utf-8')
    
    # 2. Preseed blocked retry sidecar if needed
    if preseed_attempts is not None:
        blocked_dir = tasks_dir / 'blocked'
        blocked_dir.mkdir(exist_ok=True)
        (blocked_dir / f'{task_id}.retry.json').write_text(
            json.dumps({'attempts': preseed_attempts, 'last_outcome': 'synthesis_or_ast_failed', 'ts': 12345.6}),
            encoding='utf-8'
        )
        
    # 3. Preseed approval decision if provided
    if approval_val is not None:
        decisions_dir = state_dir / 'control' / 'decisions'
        decisions_dir.mkdir(parents=True, exist_ok=True)
        (decisions_dir / f'{task_id}.json').write_text(
            json.dumps({'decision': approval_val}),
            encoding='utf-8'
        )
        
    from harness import orchestrator as orch
    import harness.orchestrator_worker as worker
    
    # Mock config
    base_cfg = orch.load_config(pathlib.Path('harness/config.yaml'))
    base_cfg.setdefault('synthesis', {})
    base_cfg['synthesis']['enable_single_agent_promotion'] = enable_single_agent_promotion
    base_cfg['synthesis']['single_agent_promotion_ceiling'] = 3
    base_cfg['synthesis']['use_retry_module'] = False
    base_cfg['synthesis']['antigravity_mode'] = False
    base_cfg['synthesis']['max_ast_retries'] = 3
    base_cfg['synthesis']['active_agents'] = ['claude', 'gemini']
    monkeypatch.setattr(orch, 'load_config', lambda *_a, **_k: base_cfg)
    
    # Mock synthesis: agent A (claude) is always valid, agent B (gemini) always has eval
    def _mock_run_both(prompt_a, prompt_b, config, sd, rnd, phase_name):
        return ("def f():\n    return 1\n", "def f():\n    eval('1')\n")
        
    def _mock_run_agent_phase(agent, prompt, config, sd, rnd, phase_name):
        if agent == 'gemini':
            return "def f():\n    eval('2')\n"
        return "def f():\n    return 1\n"
        
    monkeypatch.setattr(orch, 'run_both_agents', _mock_run_both)
    monkeypatch.setattr(orch, 'run_agent_phase', _mock_run_agent_phase)
    
    # Mock validation: reject code containing eval
    def _mock_validate_submission(code, agent, task):
        if 'eval' in code:
            from harness.ast_enforcer import Violation
            return False, [Violation('security', 'error', 1, 'eval() is banned')]
        return True, []
        
    monkeypatch.setattr(orch, '_validate_submission', _mock_validate_submission)
    monkeypatch.setattr(orch, '_try_auto_repair', lambda *_a, **_k: None)
    
    # Capturing variables passed to final stages
    succeeded_with = {}
    
    # Downstream mocks to prevent real actions and capture what code succeeded
    def _mock_save_final_output(sd, tid, code):
        succeeded_with['code'] = code
        
    monkeypatch.setattr('harness.orchestrator._route_stateful_fuzz', lambda *a, **k: None, raising=False)
    monkeypatch.setattr('harness.orchestrator._save_final_output', _mock_save_final_output, raising=False)
    monkeypatch.setattr('harness.orchestrator._auto_commit_accepted', lambda *a, **k: True, raising=False)
    monkeypatch.setattr('harness.orchestrator._mark_processed', lambda *a, **k: None, raising=False)
    monkeypatch.setattr('harness.orchestrator_worker._detect_and_append_untracked_tests', lambda *a, **k: None, raising=False)
    
    class MockFuzzResult:
        error = False
        equivalent = True
    monkeypatch.setattr('harness.diff_fuzzer.fuzz_from_task', lambda *a, **k: MockFuzzResult(), raising=False)
    
    # Run main()
    import sys
    monkeypatch.setattr(sys, 'argv', ['worker', '--state-dir', str(state_dir), '--task-id', task_id, '--config', 'harness/config.yaml'])
    
    exit_code = None
    try:
        exit_code = worker.main()
    except SystemExit as exc:
        exit_code = exc.code
        
    # Read impl_progress.jsonl events
    events = []
    progress_file = state_dir / 'impl_progress.jsonl'
    if progress_file.exists():
        for line in progress_file.read_text(encoding='utf-8').splitlines():
            if line.strip():
                events.append(json.loads(line))
                
    return {
        'exit_code': exit_code,
        'events': events,
        'succeeded_code': succeeded_with.get('code'),
        'blocked_exists': (tasks_dir / 'blocked' / f'{task_id}.json').exists(),
    }

def test_p5b_wiring_promotes_when_valid_and_approved(tmp_path, monkeypatch):
    """If single agent promotion is enabled, operator approved, ceiling met, and only one agent is valid, promotion occurs."""
    res = _setup_and_run_worker(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        task_id='rev29_p5b_wiring_success',
        enable_single_agent_promotion=True,
        preseed_attempts=2,
        approval_val='approve'
    )
    
    # Assertions for successful promotion
    promo_events = [e for e in res['events'] if e.get('event') == 'single_agent_promotion']
    assert len(promo_events) == 1, f"Expected exactly 1 single_agent_promotion lifecycle event, got: {promo_events}"
    assert 'gemini' in promo_events[0].get('detail', '').lower(), "Expected promotion reason to mention dropping gemini"
    assert res['succeeded_code'] == "def f():\n    return 1\n", "Expected promoted valid code to be used downstream"
    assert not res['blocked_exists'], "Task should not be blocked after successful single-agent promotion"
    assert res['exit_code'] == 0 or res['exit_code'] is None, f"Expected successful worker exit code, got {res['exit_code']}"

def test_p5b_wiring_control_disabled(tmp_path, monkeypatch):
    """Control case: single agent promotion is disabled -> task gets blocked."""
    res = _setup_and_run_worker(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        task_id='rev29_p5b_wiring_disabled',
        enable_single_agent_promotion=False,
        preseed_attempts=2,
        approval_val='approve'
    )
    
    # Assertions for failed promotion due to configuration disabled
    promo_events = [e for e in res['events'] if e.get('event') == 'single_agent_promotion']
    assert len(promo_events) == 0, "No promotion should occur when enable_single_agent_promotion is False"
    assert res['blocked_exists'], "Task should be blocked/rejected when single agent promotion is disabled"
    assert res['exit_code'] == 1, f"Expected worker to exit with code 1 (failure), got {res['exit_code']}"

def test_p5b_wiring_control_no_approval(tmp_path, monkeypatch):
    """Control case: target is sensitive and no operator approval is provided -> task gets blocked."""
    res = _setup_and_run_worker(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        task_id='rev29_p5b_wiring_no_approval',
        enable_single_agent_promotion=True,
        preseed_attempts=2,
        approval_val=None  # No operator decision JSON
    )
    
    # Assertions for failed promotion due to lack of operator approval
    promo_events = [e for e in res['events'] if e.get('event') == 'single_agent_promotion']
    assert len(promo_events) == 0, "No promotion should occur for sensitive target without operator approval"
    assert res['blocked_exists'], "Task should be blocked/rejected without operator approval"
    assert res['exit_code'] == 1, f"Expected worker to exit with code 1 (failure), got {res['exit_code']}"
