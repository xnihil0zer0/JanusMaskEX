"""RED oracle for P5a — cache-passing of AST-valid agent submissions across retries.

Contract (REV26 P5a):
  In the non-retry-module AST loop of ``harness.orchestrator_worker.main``
  (the ``while ast_retries < max_ast_retries`` block, current anchors
  orchestrator_worker.py:243-311), when one agent's submission PASSES AST
  validation but the other FAILS, the failing agent is re-prompted and the
  whole loop runs ``orchestrator.run_both_agents`` again — which RE-RUNS the
  already-valid agent. P5a must CACHE the last AST-valid per-agent submission
  so the already-valid agent is NOT re-synthesized on the next attempt; only
  the failing agent re-runs.

  Today the per-attempt validity is recomputed and ``run_both_agents`` is
  invoked unconditionally every attempt with BOTH prompts live, so the valid
  agent IS re-run. This oracle drives the real ``main()`` with the agent layer
  monkeypatched to count, per attempt, which agents were actually asked to
  synthesize, and asserts the consistently-valid agent is asked EXACTLY ONCE.

  RED on HEAD: the valid agent is re-asked on every attempt (>1 call).
"""
from __future__ import annotations
import json
import pathlib
import pytest


def _write_task(state_dir: pathlib.Path, task_id: str) -> None:
    (state_dir / 'tasks').mkdir(parents=True, exist_ok=True)
    task = {
        'task_id': task_id,
        'title': 'p5a cache passing probe',
        'meta_task_type': 'validation',
        'partial_edit': True,
        'files_touched': ['some/external/mod.py'],
        'acceptance_criteria': ['noop'],
    }
    (state_dir / 'tasks' / f'{task_id}.json').write_text(json.dumps(task), encoding='utf-8')


def test_valid_agent_not_resynthesized_across_ast_retry(tmp_path, monkeypatch):
    from harness import orchestrator as orch
    import harness.orchestrator_worker as worker

    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    task_id = 'rev26_p5a_probe'
    _write_task(state_dir, task_id)

    # Force the non-retry-module path with a finite retry budget.
    base_cfg = orch.load_config(pathlib.Path('harness/config.yaml'))
    base_cfg.setdefault('synthesis', {})
    base_cfg['synthesis']['use_retry_module'] = False
    base_cfg['synthesis']['antigravity_mode'] = False
    base_cfg['synthesis']['max_ast_retries'] = 3
    base_cfg['synthesis']['active_agents'] = ['claude', 'gemini']
    monkeypatch.setattr(orch, 'load_config', lambda *_a, **_k: base_cfg)

    # Count how many times each agent is actually asked to synthesize.
    synth_calls = {'claude': 0, 'gemini': 0}

    def _fake_run_both(prompt_a, prompt_b, config, sd, rnd, phase_name):
        synth_calls['claude'] += 1
        synth_calls['gemini'] += 1
        return ('def f():\n    return 1\n', 'def f():\n    return 2\n')

    monkeypatch.setattr(orch, 'run_both_agents', _fake_run_both)

    # claude ALWAYS valid; gemini fails AST on attempt 1, passes on attempt 2.
    seen = {'gemini': 0}

    def _fake_validate(code, agent, task):
        if agent == 'claude':
            return (True, [])
        seen['gemini'] += 1
        if seen['gemini'] == 1:
            from harness.ast_enforcer import Violation
            return (False, [Violation('security', 'error', 1, 'eval() is banned')])
        return (True, [])

    monkeypatch.setattr(orch, '_validate_submission', _fake_validate)
    monkeypatch.setattr(orch, '_try_auto_repair', lambda *_a, **_k: None)

    # Stub the heavy accept tail so the test ends right after synthesis succeeds.
    monkeypatch.setattr(orch, '_route_stateful_fuzz', lambda *a, **k: (_ for _ in ()).throw(AssertionError('should not reach fuzz')), raising=False)
    monkeypatch.setattr(orch, '_save_final_output', lambda *a, **k: None, raising=False)
    monkeypatch.setattr(orch, '_auto_commit_accepted', lambda *a, **k: True, raising=False)
    monkeypatch.setattr(orch, '_mark_processed', lambda *a, **k: None, raising=False)
    monkeypatch.setattr(worker, '_detect_and_append_untracked_tests', lambda *a, **k: None, raising=False)

    import sys
    monkeypatch.setattr(sys, 'argv', ['worker', '--state-dir', str(state_dir), '--task-id', task_id, '--config', 'harness/config.yaml'])
    try:
        worker.main()
    except SystemExit:
        pass
    except AssertionError:
        # reaching the accept tail is fine; we only care about synth call counts
        pass

    # claude was AST-valid on attempt 1; P5a must NOT re-synthesize it on the
    # gemini-only retry. RED today: run_both_agents re-runs claude every attempt.
    assert synth_calls['claude'] == 1, (
        f'cache-passing violated: consistently-valid agent re-synthesized '
        f'{synth_calls["claude"]}x (expected 1); per-agent valid submission '
        f'was not cached across the AST retry'
    )
