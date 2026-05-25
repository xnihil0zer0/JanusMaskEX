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
import sys
import types
import time
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
    if a.startswith('typing.'):
        a = a[len('typing.'):]
    a_normalized = ''.join(a.split())
    if a_normalized in ('str', 'builtins.str', 'Text'):
        return st.text(alphabet=st.characters(blacklist_categories=('Cs',)))
    if a_normalized in ('bool', 'builtins.bool'):
        return st.booleans()
    if a_normalized in ('int', 'builtins.int'):
        return st.integers()
    if a_normalized in ('list', 'List') or a_normalized.startswith('list[') or a_normalized.startswith('List['):
        return st.lists(st.one_of(st.integers(), st.text(max_size=8), st.none()), max_size=4)
    if a_normalized in ('dict', 'Dict') or a_normalized.startswith('dict[') or a_normalized.startswith('Dict['):
        return st.dictionaries(st.text(max_size=8), st.one_of(st.none(), st.integers(), st.text(max_size=8)), max_size=4)
    return None

def _discover_validators(module_src: str) -> list[str]:
    try:
        tree = ast.parse(module_src)
    except SyntaxError:
        return []
    names = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            if _VALIDATOR_PREFIX_RE.match(node.name):
                names.append(node.name)
    return names

def _build_strategies(sig: dict[str, str]) -> dict[str, st.SearchStrategy[Any]] | None:
    strategies = {}
    for param_name, annotation in sig.items():
        strat = _strategy_for_annotation(annotation)
        if strat is None:
            return None
        strategies[param_name] = strat
    return strategies

def _exec_module(module_name: str, module_src: str) -> dict[str, Any] | None:
    original_module = sys.modules.get(module_name)
    try:
        code = compile(module_src, f'<module {module_name}>', 'exec')
    except (SyntaxError, ValueError):
        return None
    mod = types.ModuleType(module_name)
    mod.__file__ = f'<module {module_name}>'
    if '.' in module_name:
        mod.__package__ = module_name.rsplit('.', 1)[0]
    else:
        mod.__package__ = ''
    sys.modules[module_name] = mod
    try:
        exec(code, mod.__dict__)
    except BaseException:
        return None
    finally:
        if original_module is not None:
            sys.modules[module_name] = original_module
        else:
            sys.modules.pop(module_name, None)
    return mod.__dict__

def _meta_for(fn: Callable[..., Any]) -> dict[str, Any]:
    meta = getattr(fn, '_narrow_fuzz_meta', {})
    if isinstance(meta, dict):
        return meta
    return {}

def _fuzz_one(fn: Callable[..., Any], name: str, strategies: dict[str, st.SearchStrategy[Any]], timeout: float) -> str | None:

    def bind_arguments(func: Callable[..., Any], kwargs: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
        try:
            sig = inspect.signature(func)
        except Exception:
            return ([], kwargs)
        args = []
        bound_kwargs = {}
        for name_param, param in sig.parameters.items():
            if param.kind == inspect.Parameter.POSITIONAL_ONLY:
                if name_param in kwargs:
                    args.append(kwargs[name_param])
                elif param.default is not inspect.Parameter.empty:
                    args.append(param.default)
            elif param.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
                if name_param in kwargs:
                    bound_kwargs[name_param] = kwargs[name_param]
            elif param.kind == inspect.Parameter.KEYWORD_ONLY:
                if name_param in kwargs:
                    bound_kwargs[name_param] = kwargs[name_param]
            elif param.kind == inspect.Parameter.VAR_KEYWORD:
                for k, v in kwargs.items():
                    if k not in sig.parameters:
                        bound_kwargs[k] = v
            elif param.kind == inspect.Parameter.VAR_POSITIONAL:
                if name_param in kwargs:
                    val = kwargs[name_param]
                    if isinstance(val, (list, tuple)):
                        args.extend(val)
                    else:
                        args.append(val)
        return (args, bound_kwargs)
    if not strategies:
        try:
            fn()
        except Exception as e:
            tb_str = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
            return f'Fuzzing function {name} failed with {type(e).__name__}.\nTraceback:\n{tb_str}'
        return None

    def test_target(**kwargs):
        args, b_kwargs = bind_arguments(fn, kwargs)
        fn(*args, **b_kwargs)
    test_target.__name__ = name
    test_target.__qualname__ = name
    deadline_val = int(timeout * 1000) if timeout else None
    decorated = given(**strategies)(settings(max_examples=200, deadline=deadline_val, database=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much])(test_target))
    try:
        decorated()
    except Exception as e:
        tb_str = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
        notes = getattr(e, '__notes__', [])
        notes_str = '\n'.join(notes)
        return f'Fuzzing function {name} failed with {type(e).__name__}.\nTraceback:\n{tb_str}\nNotes:\n{notes_str}'
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
    ns = _exec_module(module_name, module_src)
    if ns is None:
        return None
    for name in validator_names:
        fn = ns.get(name)
        if not fn or not callable(fn):
            continue
        meta = _meta_for(fn)
        if meta.get('skip'):
            continue
        val_timeout = meta.get('timeout', timeout)
        try:
            sig = extract_function_signature(module_src, name)
        except Exception:
            continue
        if sig is None:
            continue
        strategies = _build_strategies(sig)
        if strategies is None:
            continue
        err = _fuzz_one(fn, name, strategies, val_timeout)
        if err is not None:
            return err
    return None
import inspect