from __future__ import annotations
import ast
import inspect
import logging
import pytest
from typing import Any
from hypothesis import strategies as st
import harness.diff_fuzzer as df
logger = logging.getLogger('janusmask.test_diff_fuzzer_absent')

class _ExecResult:
    """Duck-typed ExecutionResult exposing fields the comparators read."""

    def __init__(self, value, *, success: bool=True, timed_out: bool=False, exception_type=None):
        self.return_value = value
        self.return_repr = repr(value)
        self.success = success
        self.timed_out = timed_out
        self.exception_type = exception_type
        self.error = None
        self.stdout = ''
        self.stderr = ''
        self.completed_inputs = 1
        self.batch_error = None

class _SpySandbox:
    """Mock sandbox to record executions and return deterministic results."""

    def __init__(self, rec: dict, mode: str='det'):
        self._rec = rec
        self._mode = mode
        self.config = {}

    def execute(self, code, func_name=None, args=None, kwargs=None, *a, **k):
        call_args = list(args) if args is not None else []
        self._rec['calls'].append({'code': code, 'func_name': func_name, 'args': tuple(call_args), 'kwargs': dict(kwargs or {})})
        if self._mode == 'nondet':
            return _ExecResult(len(self._rec['calls']))
        val = args[0] * 2 if args and isinstance(args[0], (int, float)) else 0
        return _ExecResult(val)

    def cleanup(self):
        self._rec['cleanups'] = self._rec.get('cleanups', 0) + 1

    def close(self):
        pass

def _install_executor_spy(monkeypatch, mode: str='det') -> dict:
    rec = {'calls': [], 'cleanups': 0}

    def factory(config=None, session_id='default', *a, **k):
        return _SpySandbox(rec, mode)
    monkeypatch.setattr(df, 'sandbox_from_config', factory, raising=False)
    return rec

def _patch_generate_inputs(monkeypatch, inputs):

    def fake(strategy, count, seed):
        return [tuple(item) for item in inputs]
    monkeypatch.setattr(df, '_generate_inputs', fake, raising=False)

def test_absent_target_out_of_bypass_skips_cleanly():
    """An absent-on-both target under a NON-bypass meta_task_type returns the clean fail-soft SKIP with equivalent=True, error=None, and skipped_reason!=None."""
    code_a = 'def other_a(): pass'
    code_b = 'def other_b(): pass'
    task = {'task_id': 'absent_out_of_bypass', 'meta_task_type': 'test_authoring', 'constraints': {'function_signature': 'def target(x: int) -> int'}}
    config = {'fuzzing': {'function_level_inputs': 10, 'float_tolerance': 1e-09, 'seed': 42}, 'batch_execution': {'enabled': False}}
    res = df.fuzz_from_task(code_a, code_b, task, config)
    assert isinstance(res, df.FuzzResult)
    assert res.equivalent is True
    assert res.error is None
    assert res.skipped_reason is not None
    assert 'absent' in res.skipped_reason.lower() or 'missing' in res.skipped_reason.lower()

def test_fuzzable_flipped_task_still_runs_inputs(monkeypatch):
    """The real fuzz path still runs for fuzzable tasks even if it is a flipped task type (like data_model)."""
    exec_rec = _install_executor_spy(monkeypatch, 'det')
    _patch_generate_inputs(monkeypatch, [([10], {}), ([20], {})])
    code_a = 'def target(x: int) -> int:\n    return x * 2\n'
    code_b = 'def target(x: int) -> int:\n    y = 0\n    return x * 2\n'
    task = {'task_id': 'fuzzable_flipped', 'meta_task_type': 'data_model', 'constraints': {'function_signature': 'def target(x: int) -> int'}}
    config = {'fuzzing': {'function_level_inputs': 2, 'float_tolerance': 1e-09, 'seed': 42}, 'batch_execution': {'enabled': False}}
    res = df.fuzz_from_task(code_a, code_b, task, config)
    assert isinstance(res, df.FuzzResult)
    assert res.equivalent is True
    assert res.error is None
    assert res.skipped_reason is None
    assert res.total_inputs == 2
    assert res.matching_inputs == 2
    assert len(exec_rec['calls']) == 4

def test_one_sided_ladder_preserved(monkeypatch):
    """The genuinely one-sided degrade ladder (blocking, metamorphic, shadow) is preserved byte-for-byte."""
    code_a = 'def target(x: int) -> int:\n    return x\n'
    code_b = 'def other_b(): pass'
    bypass_type = 'sandbox_infra'
    task = {'task_id': 'one_sided_ladder', 'meta_task_type': bypass_type, 'constraints': {'function_signature': 'def target(x: int) -> int'}}
    config = {'fuzzing': {'function_level_inputs': 10, 'float_tolerance': 1e-09, 'seed': 42}, 'batch_execution': {'enabled': False}}
    monkeypatch.setattr(df, '_onesided_oracle_blocking_enabled', lambda: True, raising=False)
    monkeypatch.setattr(df, '_onesided_oracle_enabled', lambda: False, raising=False)
    monkeypatch.setattr(df, '_onesided_metamorphic_enabled', lambda: False, raising=False)
    monkeypatch.setattr(df, '_one_sided_execute_verdict', lambda *a, **k: 'rejected', raising=False)
    res = df.fuzz_from_task(code_a, code_b, task, config)
    assert res.equivalent is False
    assert res.error is not None
    assert 'one-sided oracle BLOCKED' in res.error
    monkeypatch.setattr(df, '_onesided_oracle_blocking_enabled', lambda: True, raising=False)
    monkeypatch.setattr(df, '_one_sided_execute_verdict', lambda *a, **k: 'verified', raising=False)
    monkeypatch.setattr(df, '_onesided_metamorphic_enabled', lambda: True, raising=False)
    monkeypatch.setattr(df, '_one_sided_metamorphic_verdict', lambda *a, **k: 'rejected', raising=False)
    res = df.fuzz_from_task(code_a, code_b, task, config)
    assert res.equivalent is False
    assert res.error is not None
    assert 'one-sided metamorphic oracle BLOCKED' in res.error
    monkeypatch.setattr(df, '_onesided_oracle_blocking_enabled', lambda: True, raising=False)
    monkeypatch.setattr(df, '_one_sided_execute_verdict', lambda *a, **k: 'verified', raising=False)
    monkeypatch.setattr(df, '_onesided_metamorphic_enabled', lambda: True, raising=False)
    monkeypatch.setattr(df, '_one_sided_metamorphic_verdict', lambda *a, **k: 'verified', raising=False)
    res = df.fuzz_from_task(code_a, code_b, task, config)
    assert res.equivalent is True
    assert res.error is None
    assert res.skipped_reason is not None
    assert 'one-sided oracle BLOCKING executed' in res.skipped_reason or 'passed the conservative determinism' in res.skipped_reason
    monkeypatch.setattr(df, '_onesided_oracle_blocking_enabled', lambda: True, raising=False)
    monkeypatch.setattr(df, '_one_sided_execute_verdict', lambda *a, **k: 'unverified', raising=False)
    res = df.fuzz_from_task(code_a, code_b, task, config)
    assert res.equivalent is False
    assert res.error is not None
    assert 'one-sided oracle BLOCKING could not verify' in res.error
    monkeypatch.setattr(df, '_onesided_oracle_blocking_enabled', lambda: False, raising=False)
    monkeypatch.setattr(df, '_onesided_oracle_enabled', lambda: True, raising=False)
    monkeypatch.setattr(df, 'build_input_strategy', lambda *a, **k: st.just(([], {})), raising=False)
    res = df.fuzz_from_task(code_a, code_b, task, config)
    assert res.equivalent is True
    assert res.error is None
    assert res.skipped_reason is not None
    monkeypatch.setattr(df, '_onesided_oracle_blocking_enabled', lambda: False, raising=False)
    monkeypatch.setattr(df, '_onesided_oracle_enabled', lambda: False, raising=False)
    res = df.fuzz_from_task(code_a, code_b, task, config)
    assert res.equivalent is True
    assert res.error is None
    assert res.skipped_reason is not None

def test_one_sided_test_function_skips():
    """A test_authoring/harness_self_fix task with a target test_ function present on one side only returns equivalent=True, error=None, skipped_reason not None."""
    code_a = 'def test_target():\n    pass\n'
    code_b = 'def other_b():\n    pass\n'
    task = {'task_id': 'one_sided_test_func', 'meta_task_type': 'test_authoring', 'constraints': {'function_signature': 'def test_target()'}}
    config = {'fuzzing': {'function_level_inputs': 10, 'float_tolerance': 1e-09, 'seed': 42}, 'batch_execution': {'enabled': False}}
    res = df.fuzz_from_task(code_a, code_b, task, config)
    assert isinstance(res, df.FuzzResult)
    assert res.equivalent is True
    assert res.error is None
    assert res.skipped_reason is not None

def test_one_sided_no_strategy_skips(monkeypatch):
    """A test_authoring/harness_self_fix task with a non-test function and NO inferrable strategy returns equivalent=True, error=None, skipped_reason not None."""
    code_a = 'def target(x: int) -> int:\n    return x\n'
    code_b = 'def other_b():\n    pass\n'
    task = {'task_id': 'one_sided_no_strategy', 'meta_task_type': 'test_authoring', 'constraints': {'function_signature': 'def target(x: int) -> int'}}
    config = {'fuzzing': {'function_level_inputs': 10, 'float_tolerance': 1e-09, 'seed': 42}, 'batch_execution': {'enabled': False}}
    original_build = df.build_input_strategy

    def mock_build_strategy(code, func_name, *args, **kwargs):
        if func_name == 'target':
            raise ValueError('No strategy found for target')
        return original_build(code, func_name, *args, **kwargs)
    monkeypatch.setattr(df, 'build_input_strategy', mock_build_strategy, raising=False)
    res = df.fuzz_from_task(code_a, code_b, task, config)
    assert isinstance(res, df.FuzzResult)
    assert res.equivalent is True
    assert res.error is None
    assert res.skipped_reason is not None

def test_one_sided_fuzzable_errors(monkeypatch):
    """A test_authoring/harness_self_fix task with a non-test function and buildable strategy still error-rejects."""
    code_a = 'def target(x: int) -> int:\n    return x\n'
    code_b = 'def other_b():\n    pass\n'
    task = {'task_id': 'one_sided_fuzzable', 'meta_task_type': 'test_authoring', 'constraints': {'function_signature': 'def target(x: int) -> int'}}
    config = {'fuzzing': {'function_level_inputs': 10, 'float_tolerance': 1e-09, 'seed': 42}, 'batch_execution': {'enabled': False}}
    monkeypatch.setattr(df, 'build_input_strategy', lambda *a, **k: st.just(([42], {})), raising=False)
    res = df.fuzz_from_task(code_a, code_b, task, config)
    assert isinstance(res, df.FuzzResult)
    assert res.equivalent is False
    assert res.error is not None
    assert 'strategy' in res.error or 'not found' in res.error or 'missing' in res.error or ('absent' in res.error)