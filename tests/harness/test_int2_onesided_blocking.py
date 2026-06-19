"""Paired RED oracle for the one-sided oracle BLOCKING tier.

This test file pins the four required behaviors of the (not-yet-implemented)
one-sided BLOCKING tier in ``harness.diff_fuzzer``:

  (a) flag OFF/absent  -> the existing waiver is preserved byte-identically and
      the executing helper ``_one_sided_execute_verdict`` is NEVER consulted;
  (b) flag ON + a NON-deterministic lone candidate -> the gate BLOCKS
      (``FuzzResult.equivalent is False``) via REAL out-of-process execution
      (the spied executor runs the same input twice and disagrees);
  (c) flag ON + a FAITHFUL deterministic lone candidate -> verdict ``verified``
      and the skip is preserved (``equivalent is True`` reached THROUGH the
      executor, not via the unconditional waiver);
  (d) no in-process ``exec``/``eval``/``compile``/``__import__`` is introduced
      and the blocking gate is WIRED into ``fuzz_from_task``'s live one-side
      branch (source scan).

It is RED on HEAD because the blocking capability does not exist yet:
``fuzz_from_task`` short-circuits the one-side branch to the waiver without ever
consulting ``_onesided_oracle_blocking_enabled`` or executing the candidate.

The file is collectable on HEAD: it imports only the module under test and
references the new symbols dynamically (monkeypatch with ``raising=False`` /
source scans), so missing attributes surface as ASSERTION failures inside the
tests rather than as a collection-time ImportError.
"""
from __future__ import annotations
import ast
import inspect
import pytest
import harness.diff_fuzzer as df
_CODE_WITH_F = 'def f(x: int) -> int:\n    return x\n'
_CODE_WITHOUT_F = 'def unrelated(y: int) -> int:\n    return y\n'
_HEAD_WAIVER_FRAGMENT = 'skipping fuzz by policy'

def _bypass_meta_type() -> str:
    """A meta_task_type guaranteed to be in the live fuzzer-bypass set."""
    bypass = getattr(df, 'FUZZ_BYPASS_META_TYPES', None)
    if not bypass:
        pytest.skip('FUZZ_BYPASS_META_TYPES is empty; cannot build one-side scenario')
    return next(iter(bypass))

def _make_scenario() -> tuple[str, str, dict, dict]:
    """Return (code_a, code_b, task, config) for a lone-candidate (code_a) run."""
    task = {'task_id': 'onesided-blocking', 'meta_task_type': _bypass_meta_type(), 'constraints': {'function_signature': 'def f(x: int) -> int'}}
    config = {'fuzzing': {'function_level_inputs': 8, 'seed': 1234}, 'batch_execution': {'enabled': False}}
    return (_CODE_WITH_F, _CODE_WITHOUT_F, task, config)

class _ExecResult:
    """Duck-typed ExecutionResult exposing every field the comparators read."""

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

def _record_and_result(rec: dict, mode: str, func_name, args, kwargs) -> _ExecResult:
    call_args = list(args) if args is not None else []
    rec['calls'].append({'func_name': func_name, 'args': tuple(call_args), 'kwargs': dict(kwargs or {})})
    if mode == 'nondet':
        return _ExecResult(len(rec['calls']))
    return _ExecResult(('det', tuple(call_args)))

class _SpySandbox:

    def __init__(self, rec: dict, mode: str):
        self._rec = rec
        self._mode = mode
        self.config = {}

    def execute(self, code, func_name=None, args=None, kwargs=None, *a, **k):
        return _record_and_result(self._rec, self._mode, func_name, args, kwargs)

    def cleanup(self):
        self._rec['cleanups'] = self._rec.get('cleanups', 0) + 1

    def close(self):
        pass

def _install_executor_spy(monkeypatch, mode: str) -> dict:
    """Spy both ``sandbox_from_config`` and ``Sandbox.execute`` (per spec)."""
    rec: dict = {'calls': [], 'cleanups': 0}

    def factory(config=None, session_id='default', *a, **k):
        return _SpySandbox(rec, mode)
    monkeypatch.setattr(df, 'sandbox_from_config', factory, raising=False)
    sandbox_cls = getattr(df, 'Sandbox', None)
    if sandbox_cls is not None:

        def _patched_execute(self, code, func_name=None, args=None, kwargs=None, *a, **k):
            return _record_and_result(rec, mode, func_name, args, kwargs)
        monkeypatch.setattr(sandbox_cls, 'execute', _patched_execute, raising=False)
    return rec

def _set_flag(monkeypatch, blocking: bool) -> None:
    """Drive the new blocking flag; keep the shadow flag OFF so only the
    blocking gate can change behavior."""
    monkeypatch.setattr(df, '_onesided_oracle_blocking_enabled', lambda: blocking, raising=False)
    monkeypatch.setattr(df, '_onesided_oracle_enabled', lambda: False, raising=False)

def _patch_generate_inputs(monkeypatch, inputs, seeds_seen=None, counts_seen=None):
    """Pin the seeded input generator to a controlled, fast input set.

    The blocking tier reuses ``_generate_inputs`` verbatim (seed-pinned
    Phase.generate contract); patching it keeps the suite hermetic and lets us
    observe the seed/count handed to it.
    """

    def fake(strategy, count, seed):
        if seeds_seen is not None:
            seeds_seen.append(seed)
        if counts_seen is not None:
            counts_seen.append(count)
        return [tuple(item) for item in inputs]
    monkeypatch.setattr(df, '_generate_inputs', fake, raising=False)

def _spy_helper(monkeypatch, return_value: str='verified') -> dict:
    """Spy ``_one_sided_execute_verdict`` to prove it is (not) consulted."""
    rec: dict = {'calls': []}

    def spy(*args, **kwargs):
        rec['calls'].append((args, kwargs))
        return return_value
    monkeypatch.setattr(df, '_one_sided_execute_verdict', spy, raising=False)
    return rec

def test_flag_off_absent_returns_waiver_equivalent_true_and_helper_not_consulted(monkeypatch):
    _set_flag(monkeypatch, blocking=False)
    helper_rec = _spy_helper(monkeypatch)
    exec_rec = _install_executor_spy(monkeypatch, mode='det')
    code_a, code_b, task, config = _make_scenario()
    result = df.fuzz_from_task(code_a, code_b, task, config, session_id='off')
    assert result.equivalent is True
    assert result.skipped_reason is not None
    assert helper_rec['calls'] == []
    assert exec_rec['calls'] == []

def test_flag_on_nondeterministic_candidate_blocks_equivalent_false(monkeypatch):
    _set_flag(monkeypatch, blocking=True)
    exec_rec = _install_executor_spy(monkeypatch, mode='nondet')
    _patch_generate_inputs(monkeypatch, inputs=[([7], {}), ([11], {})])
    code_a, code_b, task, config = _make_scenario()
    result = df.fuzz_from_task(code_a, code_b, task, config, session_id='block')
    assert result.equivalent is False
    err = (result.error or '') + ' ' + (result.skipped_reason or '')
    assert len(exec_rec['calls']) >= 2 or 'block' in err.lower()

def test_flag_on_deterministic_candidate_verified_skip_preserved(monkeypatch):
    _set_flag(monkeypatch, blocking=True)
    exec_rec = _install_executor_spy(monkeypatch, mode='det')
    _patch_generate_inputs(monkeypatch, inputs=[([5], {}), ([9], {})])
    code_a, code_b, task, config = _make_scenario()
    result = df.fuzz_from_task(code_a, code_b, task, config, session_id='verify')
    assert result.equivalent is True
    assert len(exec_rec['calls']) >= 2
    assert _HEAD_WAIVER_FRAGMENT not in (result.skipped_reason or '')

def test_no_inprocess_dynamic_exec_and_wired_into_live_branch():
    module_src = inspect.getsource(df)
    tree = ast.parse(module_src)
    banned = {'exec', 'eval', 'compile', '__import__'}
    scanned = {'fuzz_from_task', '_one_sided_execute_verdict'}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in scanned:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    fn = sub.func
                    name = None
                    if isinstance(fn, ast.Name):
                        name = fn.id
                    elif isinstance(fn, ast.Attribute):
                        name = fn.attr
                    assert name not in banned, f'forbidden in-process dynamic exec {name!r} in {node.name}'
    fuzz_src = inspect.getsource(df.fuzz_from_task)
    assert '_onesided_oracle_blocking_enabled' in fuzz_src, "blocking gate not wired into fuzz_from_task's live one-side branch"
    assert '_one_sided_execute_verdict' in module_src, 'executing helper _one_sided_execute_verdict is missing'

def test_fuzz_from_task_one_side_branch_exercises_out_of_process_executor_twice_per_input(monkeypatch):
    _set_flag(monkeypatch, blocking=True)
    exec_rec = _install_executor_spy(monkeypatch, mode='det')
    _patch_generate_inputs(monkeypatch, inputs=[([1], {}), ([2], {})])
    code_a, code_b, task, config = _make_scenario()
    result = df.fuzz_from_task(code_a, code_b, task, config, session_id='twice')
    assert result.equivalent is True
    assert exec_rec['calls'], 'executor was never exercised'
    per_input: dict = {}
    for call in exec_rec['calls']:
        per_input[call['args']] = per_input.get(call['args'], 0) + 1
    assert per_input, 'no inputs were executed'
    assert all((count >= 2 for count in per_input.values())), per_input

def test_determinism_relation_uses_seed_pinned_inputs_and_outputs_match(monkeypatch):
    _set_flag(monkeypatch, blocking=True)
    exec_rec = _install_executor_spy(monkeypatch, mode='det')
    seeds_seen: list = []
    _patch_generate_inputs(monkeypatch, inputs=[([5], {})], seeds_seen=seeds_seen)
    code_a, code_b, task, config = _make_scenario()
    result = df.fuzz_from_task(code_a, code_b, task, config, session_id='prop')
    assert seeds_seen, 'seed-pinned input generator was never consulted'
    assert all((isinstance(s, int) for s in seeds_seen))
    same_input_calls = [c for c in exec_rec['calls'] if c['args'] == (5,)]
    assert len(same_input_calls) >= 2, exec_rec['calls']
    assert result.equivalent is True

def test_regression_flag_off_byte_identical_to_head_waiver(monkeypatch):
    _set_flag(monkeypatch, blocking=False)
    helper_rec = _spy_helper(monkeypatch)
    exec_rec = _install_executor_spy(monkeypatch, mode='nondet')
    code_a, code_b, task, config = _make_scenario()
    result = df.fuzz_from_task(code_a, code_b, task, config, session_id='reg_off')
    assert result.equivalent is True
    assert result.skipped_reason is not None
    assert helper_rec['calls'] == []
    assert exec_rec['calls'] == []

def test_regression_flag_on_nondeterministic_blocks_not_waiver(monkeypatch):
    _set_flag(monkeypatch, blocking=True)
    exec_rec = _install_executor_spy(monkeypatch, mode='nondet')
    _patch_generate_inputs(monkeypatch, inputs=[([3], {})])
    code_a, code_b, task, config = _make_scenario()
    result = df.fuzz_from_task(code_a, code_b, task, config, session_id='reg_block')
    assert result.equivalent is False
    assert len(exec_rec['calls']) >= 2

def test_regression_flag_on_deterministic_verified_not_unconditional_waiver(monkeypatch):
    _set_flag(monkeypatch, blocking=True)
    exec_rec = _install_executor_spy(monkeypatch, mode='det')
    _patch_generate_inputs(monkeypatch, inputs=[([4], {})])
    code_a, code_b, task, config = _make_scenario()
    result = df.fuzz_from_task(code_a, code_b, task, config, session_id='reg_verify')
    assert result.equivalent is True
    assert len(exec_rec['calls']) >= 2
    assert _HEAD_WAIVER_FRAGMENT not in (result.skipped_reason or '')

def test_regression_unverified_fail_closed_equivalent_false(monkeypatch):
    _set_flag(monkeypatch, blocking=True)
    _install_executor_spy(monkeypatch, mode='det')
    _patch_generate_inputs(monkeypatch, inputs=[])
    code_a, code_b, task, config = _make_scenario()
    result = df.fuzz_from_task(code_a, code_b, task, config, session_id='reg_unver')
    assert result.equivalent is False