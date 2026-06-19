"""Paired RED oracle for the one-sided METAMORPHIC blocking tier.

This file pins the behaviour of the (not-yet-implemented) one-sided
*metamorphic* tier that sits on top of the already-shipped determinism-only
blocking tier in ``harness.diff_fuzzer`` (see ``test_int2_onesided_blocking``):

  (a) flag OFF/absent (``autowork.onesided_metamorphic`` False/missing) -> the
      one-side VERDICT is unchanged from determinism-only and the run is
      byte-identical to the determinism-only path (no extra transformed-input
      executions; a deterministic-but-non-idempotent candidate still passes);
  (b) flag ON + a cross-process DETERMINISTIC but NON-idempotent (or
      order-dependent) lone candidate -> the gate BLOCKS
      (``FuzzResult.equivalent is False``);
  (c) flag ON + a FAITHFUL lone candidate (relations inapplicable or satisfied)
      -> stays ``equivalent is True`` (a *verified* skip, reached THROUGH the
      executor -- not the unconditional HEAD waiver);
  (d) no in-process ``exec``/``eval``/``compile``/``__import__`` is introduced
      into the changed regions;
  (e) the new reader ``_onesided_metamorphic_enabled()`` is fail-safe (False on
      missing key / unreadable config) and lazy-imports ``load_config`` from
      ``harness.orchestrator``.

The oracle asserts only the observable VERDICT for the gated branches (it does
NOT pin the reader's source location inside ``fuzz_from_task`` nor demand any
minimum number of ``sandbox.execute`` calls): the gate is correct iff its
verdict is correct.

It is RED on HEAD because the metamorphic capability does not exist yet:
``fuzz_from_task`` never consults ``_onesided_metamorphic_enabled`` and issues
no transformed-input executions, and the reader itself is absent.

The file is collectable on HEAD: it imports only the module under test and
references the new symbols dynamically (``getattr`` / ``monkeypatch`` with
``raising=False`` / source scans), so missing attributes surface as ASSERTION
failures inside the tests rather than as a collection-time ImportError.
"""
from __future__ import annotations
import ast
import inspect
import pytest
import harness.diff_fuzzer as df
_CODE_WITH_INT = 'def f(x: int) -> int:\n    return x\n'
_CODE_WITH_LIST = 'def f(xs: list) -> int:\n    return xs[0]\n'
_CODE_WITHOUT = 'def unrelated(y: int) -> int:\n    return y\n'
_HEAD_WAIVER_FRAGMENT = 'skipping fuzz by policy'

def _bypass_meta_type() -> str:
    """A meta_task_type guaranteed to be in the live fuzzer-bypass set.

    The one-side branch of ``fuzz_from_task`` is only reached when the missing
    function's meta_task_type is bypass-eligible; otherwise the call fails
    closed before any oracle runs.
    """
    bypass = getattr(df, 'FUZZ_BYPASS_META_TYPES', None)
    if not bypass:
        pytest.skip('FUZZ_BYPASS_META_TYPES is empty; cannot build one-side scenario')
    return next(iter(bypass))

def _scenario(func_sig: str, code_with: str) -> tuple[str, str, dict, dict]:
    """Return (code_a, code_b, task, config) for a lone-candidate (code_a) run."""
    task = {'task_id': 'onesided-metamorphic', 'meta_task_type': _bypass_meta_type(), 'constraints': {'function_signature': func_sig}}
    config = {'fuzzing': {'function_level_inputs': 8, 'seed': 1234}, 'batch_execution': {'enabled': False}}
    return (code_with, _CODE_WITHOUT, task, config)

def _freeze(obj):
    """Make a (possibly nested) value hashable for membership/counting."""
    if isinstance(obj, (list, tuple)):
        return tuple((_freeze(x) for x in obj))
    if isinstance(obj, dict):
        return tuple(sorted(((k, _freeze(v)) for k, v in obj.items())))
    if isinstance(obj, set):
        return ('set', tuple(sorted((_freeze(x) for x in obj))))
    return obj

class _ExecResult:
    """Duck-typed ExecutionResult exposing every field the comparators read."""

    def __init__(self, value, *, success: bool=True, timed_out: bool=False, exception_type=None):
        self.return_value = value
        self.return_repr = repr(value)
        self.success = success
        self.timed_out = timed_out
        self.exception_type = exception_type
        self.exception_message = None
        self.stderr = ''
        self.wall_time_ms = 0.0
        self.completed_inputs = 1
        self.batch_error = None

def _make_result(rec, compute, success, timed_out, func_name, args, kwargs):
    call_args = list(args) if args is not None else []
    call_kwargs = dict(kwargs or {})
    rec['calls'].append({'func_name': func_name, 'args': _freeze(call_args), 'kwargs': _freeze(call_kwargs)})
    to = timed_out(call_args, call_kwargs) if callable(timed_out) else timed_out
    if to:
        return _ExecResult(None, success=False, timed_out=True, exception_type='TimeoutError')
    try:
        value = compute(call_args, call_kwargs)
    except Exception as exc:
        return _ExecResult(None, success=False, exception_type=type(exc).__name__)
    ok = success(call_args, call_kwargs) if callable(success) else success
    return _ExecResult(value, success=ok)

class _SpySandbox:

    def __init__(self, rec, compute, success, timed_out):
        self._rec = rec
        self._compute = compute
        self._success = success
        self._timed_out = timed_out
        self.config = {}

    def execute(self, code, func_name=None, args=None, kwargs=None, *a, **k):
        return _make_result(self._rec, self._compute, self._success, self._timed_out, func_name, args, kwargs)

    def cleanup(self):
        self._rec['cleanups'] = self._rec.get('cleanups', 0) + 1

    def close(self):
        pass

def _install_spy(monkeypatch, compute, *, success=True, timed_out=False) -> dict:
    """Spy both ``sandbox_from_config`` and ``Sandbox.execute`` (per spec).

    Every out-of-process execution issued by the determinism tier OR the new
    metamorphic tier is recorded, so the OFF/absent suite can prove the run is
    byte-identical to the determinism-only path (exactly two determinism
    executions per input, no transformed-input probes).
    """
    rec: dict = {'calls': [], 'cleanups': 0}

    def factory(config=None, session_id='default', *a, **k):
        return _SpySandbox(rec, compute, success, timed_out)
    monkeypatch.setattr(df, 'sandbox_from_config', factory, raising=False)
    sandbox_cls = getattr(df, 'Sandbox', None)
    if sandbox_cls is not None:

        def _patched_execute(self, code, func_name=None, args=None, kwargs=None, *a, **k):
            return _make_result(rec, compute, success, timed_out, func_name, args, kwargs)
        monkeypatch.setattr(sandbox_cls, 'execute', _patched_execute, raising=False)
    return rec

def _set_flags(monkeypatch, *, blocking: bool, metamorphic: bool) -> None:
    """Drive the determinism-blocking gate and the NEW metamorphic gate.

    The shadow flag is forced OFF so only the gates under test can change
    behaviour. ``raising=False`` keeps the call collectable on HEAD (the
    metamorphic reader does not exist there yet).
    """
    monkeypatch.setattr(df, '_onesided_oracle_blocking_enabled', lambda: blocking, raising=False)
    monkeypatch.setattr(df, '_onesided_metamorphic_enabled', lambda: metamorphic, raising=False)
    monkeypatch.setattr(df, '_onesided_oracle_enabled', lambda: False, raising=False)

def _patch_generate_inputs(monkeypatch, inputs, seeds_seen=None, counts_seen=None):
    """Pin the seed-pinned generator to a controlled, fast input set.

    Both the determinism tier and (per spec) the metamorphic tier reuse
    ``_generate_inputs`` verbatim; patching it keeps the suite hermetic.
    """

    def fake(strategy, count, seed):
        if seeds_seen is not None:
            seeds_seen.append(seed)
        if counts_seen is not None:
            counts_seen.append(count)
        return [tuple(item) for item in inputs]
    monkeypatch.setattr(df, '_generate_inputs', fake, raising=False)

def _metamorphic_source_present() -> bool:
    """True iff the module file actually defines the metamorphic reader.

    Reads the file via ``inspect.getsource`` so it is immune to any test-time
    monkeypatching of the module attribute.
    """
    try:
        return 'def _onesided_metamorphic_enabled' in inspect.getsource(df)
    except Exception:
        return False

def test_reader_failsafe_missing_or_corrupt_config(monkeypatch):
    reader = getattr(df, '_onesided_metamorphic_enabled', None)
    assert callable(reader), 'reader _onesided_metamorphic_enabled is not implemented'
    monkeypatch.setattr('harness.orchestrator.load_config', lambda *a, **k: {}, raising=False)
    assert reader() is False
    monkeypatch.setattr('harness.orchestrator.load_config', lambda *a, **k: {'autowork': {}}, raising=False)
    assert reader() is False

    def _boom(*a, **k):
        raise RuntimeError('config unreadable')
    monkeypatch.setattr('harness.orchestrator.load_config', _boom, raising=False)
    assert reader() is False
    monkeypatch.setattr('harness.orchestrator.load_config', lambda *a, **k: {'autowork': {'onesided_metamorphic': True}}, raising=False)
    assert reader() is True

def test_regression_reader_uses_correct_lazy_import_path(monkeypatch):
    reader = getattr(df, '_onesided_metamorphic_enabled', None)
    assert reader is not None, 'reader _onesided_metamorphic_enabled is missing'
    src = inspect.getsource(reader)
    assert 'from harness.orchestrator import load_config' in src, 'reader must lazy-import load_config from harness.orchestrator'
    called = {'hit': False}

    def _fake_load_config(*a, **k):
        called['hit'] = True
        return {'autowork': {'onesided_metamorphic': True}}
    monkeypatch.setattr('harness.orchestrator.load_config', _fake_load_config, raising=False)
    assert reader() is True
    assert called['hit'] is True

def test_regression_metamorphic_flag_absent_defaults_to_off(monkeypatch):
    reader = getattr(df, '_onesided_metamorphic_enabled', None)
    assert callable(reader), 'reader _onesided_metamorphic_enabled is not implemented'
    monkeypatch.setattr('harness.orchestrator.load_config', lambda *a, **k: {'autowork': {}}, raising=False)
    assert reader() is False
    monkeypatch.setattr(df, '_onesided_oracle_blocking_enabled', lambda: True, raising=False)
    monkeypatch.setattr(df, '_onesided_oracle_enabled', lambda: False, raising=False)
    inputs = [([7], {}), ([11], {})]
    rec = _install_spy(monkeypatch, compute=lambda a, k: a[0] + 1 if a else 0)
    _patch_generate_inputs(monkeypatch, inputs=inputs)
    code_a, code_b, task, config = _scenario('def f(x: int) -> int', _CODE_WITH_INT)
    result = df.fuzz_from_task(code_a, code_b, task, config, session_id='absent')
    assert result.equivalent is True
    allowed = {_freeze([7]), _freeze([11])}
    assert all((c['args'] in allowed for c in rec['calls'])), rec['calls']
    assert len(rec['calls']) == 2 * len(inputs), rec['calls']

def test_fuzz_from_task_flag_off_preserves_determinism_only_behavior(monkeypatch):
    _set_flags(monkeypatch, blocking=True, metamorphic=False)
    inputs = [([7], {}), ([11], {})]
    rec = _install_spy(monkeypatch, compute=lambda a, k: a[0] + 1 if a else 0)
    _patch_generate_inputs(monkeypatch, inputs=inputs)
    code_a, code_b, task, config = _scenario('def f(x: int) -> int', _CODE_WITH_INT)
    result = df.fuzz_from_task(code_a, code_b, task, config, session_id='off')
    assert result.equivalent is True
    allowed = {_freeze([7]), _freeze([11])}
    assert all((c['args'] in allowed for c in rec['calls'])), rec['calls']
    assert len(rec['calls']) == 2 * len(inputs), rec['calls']

def test_fuzz_from_task_flag_on_blocks_non_idempotent_candidate(monkeypatch):
    _set_flags(monkeypatch, blocking=True, metamorphic=True)
    inputs = [([7], {})]
    _install_spy(monkeypatch, compute=lambda a, k: a[0] + 1 if a else 0)
    _patch_generate_inputs(monkeypatch, inputs=inputs)
    code_a, code_b, task, config = _scenario('def f(x: int) -> int', _CODE_WITH_INT)
    result = df.fuzz_from_task(code_a, code_b, task, config, session_id='nonidem')
    assert result.equivalent is False

def test_fuzz_from_task_flag_on_blocks_order_dependent_candidate(monkeypatch):
    _set_flags(monkeypatch, blocking=True, metamorphic=True)
    inputs = [([[1, 2, 3]], {})]

    def _first(a, k):
        if a and isinstance(a[0], list) and a[0]:
            return a[0][0]
        return 0
    _install_spy(monkeypatch, compute=_first)
    _patch_generate_inputs(monkeypatch, inputs=inputs)
    code_a, code_b, task, config = _scenario('def f(xs: list) -> int', _CODE_WITH_LIST)
    result = df.fuzz_from_task(code_a, code_b, task, config, session_id='order')
    assert result.equivalent is False

def test_fuzz_from_task_flag_on_passes_faithful_candidate(monkeypatch):
    _set_flags(monkeypatch, blocking=True, metamorphic=True)
    inputs = [([5], {}), ([9], {})]
    _install_spy(monkeypatch, compute=lambda a, k: a[0] if a else None)
    _patch_generate_inputs(monkeypatch, inputs=inputs)
    code_a, code_b, task, config = _scenario('def f(x: int) -> int', _CODE_WITH_INT)
    result = df.fuzz_from_task(code_a, code_b, task, config, session_id='faithful')
    assert result.equivalent is True
    assert _HEAD_WAIVER_FRAGMENT not in (result.skipped_reason or '')

def test_idempotence_skipped_when_return_not_serializable(monkeypatch):
    assert _metamorphic_source_present(), 'metamorphic tier not implemented on HEAD'
    _set_flags(monkeypatch, blocking=True, metamorphic=True)
    inputs = [([5], {})]

    def _compute(a, k):
        if a and isinstance(a[0], set):
            raise ValueError('non-serializable input cannot be executed')
        return {1, 2, 3}
    _install_spy(monkeypatch, compute=_compute)
    _patch_generate_inputs(monkeypatch, inputs=inputs)
    code_a, code_b, task, config = _scenario('def f(x: int) -> int', _CODE_WITH_INT)
    result = df.fuzz_from_task(code_a, code_b, task, config, session_id='noserial')
    assert result.equivalent is True
    assert _HEAD_WAIVER_FRAGMENT not in (result.skipped_reason or '')

def test_order_invariance_skipped_when_first_arg_not_list(monkeypatch):
    assert _metamorphic_source_present(), 'metamorphic tier not implemented on HEAD'
    _set_flags(monkeypatch, blocking=True, metamorphic=True)
    inputs = [([5], {}), ([9], {})]
    rec = _install_spy(monkeypatch, compute=lambda a, k: a[0] if a else None)
    _patch_generate_inputs(monkeypatch, inputs=inputs)
    code_a, code_b, task, config = _scenario('def f(x: int) -> int', _CODE_WITH_INT)
    result = df.fuzz_from_task(code_a, code_b, task, config, session_id='notlist')
    assert result.equivalent is True
    for call in rec['calls']:
        for arg in call['args']:
            assert not isinstance(arg, tuple), call

def test_relation_skipped_when_determinism_fails_or_times_out(monkeypatch):
    assert _metamorphic_source_present(), 'metamorphic tier not implemented on HEAD'
    _set_flags(monkeypatch, blocking=True, metamorphic=True)
    inputs = [([5], {})]
    _install_spy(monkeypatch, compute=lambda a, k: a[0] if a else None, timed_out=True)
    _patch_generate_inputs(monkeypatch, inputs=inputs)
    code_a, code_b, task, config = _scenario('def f(x: int) -> int', _CODE_WITH_INT)
    result = df.fuzz_from_task(code_a, code_b, task, config, session_id='timeout')
    assert result.equivalent is True

def test_no_in_process_exec_ast_check():
    module_src = inspect.getsource(df)
    tree = ast.parse(module_src)
    banned = {'exec', 'eval', 'compile', '__import__'}
    targets = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
            if name in {'fuzz_from_task', '_one_sided_execute_verdict', '_onesided_metamorphic_enabled'} or 'metamorphic' in name or 'one_sided' in name or ('onesided' in name):
                targets.append(node)
    assert any(('metamorphic' in n.name for n in targets)), 'metamorphic tier not implemented on HEAD'
    for node in targets:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                fn = sub.func
                call_name = None
                if isinstance(fn, ast.Name):
                    call_name = fn.id
                elif isinstance(fn, ast.Attribute):
                    call_name = fn.attr
                assert call_name not in banned, f'forbidden in-process dynamic exec {call_name!r} in {node.name}'