"""Narrow-fuzz module for ``meta_task_type="validation"`` (W77b.2).

Discovers candidate validator-like functions in the canary source —
top-level ``def`` matching ``^(validate_|check_|is_)`` — extracts each
function's annotated signature via
:func:`harness.diff_fuzzer.extract_function_signature`, maps Python
type-annotation strings to Hypothesis strategies per the brief §10.2
table, and runs 200 inputs per validator. Returns ``None`` on
pass/skip; on crash, returns an error string that includes the
exception type **and** the shrunken failing input (binding §13).

Per §11.2 reversed default: when the candidate source already defines
embedded ``test_*`` functions (detected via
:func:`harness.embedded_test_runner.should_run_embedded_tests`),
narrow-fuzz returns ``None`` to avoid redundant coverage. The
``RUN_NARROW_FUZZ_ALWAYS=1`` env var, read at module load, overrides
this skip.

Per §10.3 decorator opt-out: validators may carry an
``_narrow_fuzz_meta`` sentinel attribute (``{"skip": True}`` to skip,
``{"timeout": 10.0}`` to override timeout). Discovery uses ``getattr``
with a default of ``{}`` so undecorated validators run with defaults.
"""
from __future__ import annotations
import ast
import os
import re
import traceback
from typing import Any
from typing import Callable
from hypothesis import HealthCheck
from hypothesis import given
from hypothesis import settings
from hypothesis import strategies as st
from harness.diff_fuzzer import extract_function_signature
from harness.embedded_test_runner import should_run_embedded_tests
_VALIDATOR_PREFIX_RE = re.compile('^(validate_|check_|is_)')
_DEFAULT_INPUT_BUDGET = 200
_RUN_ALWAYS: bool = os.environ.get('RUN_NARROW_FUZZ_ALWAYS') == '1'

def _strategy_for_annotation(annotation: str) -> st.SearchStrategy[Any] | None:
    a = annotation.strip()
    if a in ('str', 'builtins.str'):
        return st.text(alphabet=st.characters(blacklist_categories=('Cs',)))
    if a in ('bool', 'builtins.bool'):
        return st.booleans()
    if a in ('int', 'builtins.int'):
        return st.integers()
    if a in ('list', 'List') or a.startswith('list[') or a.startswith('List['):
        return st.lists(st.one_of(st.integers(), st.text(max_size=8), st.none()), max_size=4)
    if a in ('dict', 'Dict') or a.startswith('dict[') or a.startswith('Dict['):
        return st.dictionaries(st.text(max_size=8), st.one_of(st.none(), st.integers(), st.text(max_size=8)), max_size=4)
    return None

def _discover_validators(module_src: str) -> list[str]:
    try:
        tree = ast.parse(module_src)
    except SyntaxError:
        return []
    return [node.name for node in tree.body if isinstance(node, ast.FunctionDef) and _VALIDATOR_PREFIX_RE.match(node.name)]

def _build_strategies(sig: dict[str, str]) -> dict[str, st.SearchStrategy[Any]] | None:
    strategies: dict[str, st.SearchStrategy[Any]] = {}
    for param, annot in sig.items():
        s = _strategy_for_annotation(annot)
        if s is None:
            return None
        strategies[param] = s
    return strategies

def _exec_module(module_name: str, module_src: str) -> dict[str, Any] | None:
    ns: dict[str, Any] = {'__name__': module_name}
    try:
        compiled = compile(module_src, f'<narrow_fuzz_{module_name}>', 'exec')
        exec(compiled, ns)
    except Exception:
        return None
    return ns

def _meta_for(fn: Callable[..., Any]) -> dict[str, Any]:
    meta = getattr(fn, '_narrow_fuzz_meta', None)
    return meta if isinstance(meta, dict) else {}

def _fuzz_one(fn: Callable[..., Any], name: str, strategies: dict[str, st.SearchStrategy[Any]], timeout: float) -> str | None:
    captured: dict[str, Any] = {}

    @settings(max_examples=_DEFAULT_INPUT_BUDGET, deadline=int(timeout * 1000), suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture], print_blob=False)
    @given(**strategies)
    def runner(**kwargs: Any) -> None:
        try:
            fn(**kwargs)
        except Exception as exc:
            captured['input'] = kwargs
            captured['exc_type'] = type(exc).__name__
            captured['exc_msg'] = str(exc)
            captured['tb'] = traceback.format_exc(limit=3)
            raise
    try:
        runner()
    except Exception:
        if not captured:
            return f'{name}: narrow-fuzz failed (no captured input)'
        return f'{captured['exc_type']} on {name} with input {captured['input']!r}: {captured['exc_msg']}'
    return None

def fuzz(module_name: str, module_src: str, *, timeout: float=5.0) -> str | None:
    """Narrow-fuzz the candidate's validator-like functions.
    
        See module docstring for design contract; brief §4.1, §11.2, §13
        are the binding spec.
        """
    if should_run_embedded_tests(module_src) and (not _RUN_ALWAYS):
        return None
    validator_names = _discover_validators(module_src)
    if not validator_names:
        return None
    namespace = _exec_module(module_name, module_src)
    if namespace is None:
        return None
    for name in validator_names:
        fn = namespace.get(name)
        if not callable(fn):
            continue
        meta = _meta_for(fn)
        if meta.get('skip'):
            continue
        try:
            sig = extract_function_signature(module_src, name)
        except Exception:
            continue
        if not sig:
            continue
        strategies = _build_strategies(sig)
        if strategies is None:
            continue
        per_timeout = float(meta.get('timeout', timeout))
        err = _fuzz_one(fn, name, strategies, per_timeout)
        if err is not None:
            return err
    return None