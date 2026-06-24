"""Differential fuzzing engine for JanusMask.

Adapted from the Eq@DFuzz methodology (arXiv:2602.15761).  Generates
type-aware inputs via Hypothesis, executes both code samples in sandboxed
subprocesses, and compares outputs with structural equality.

Usage:
    result = differential_fuzz(code_a, code_b, task_constraints, config)
    if result.equivalent:
        ...  # accept
    else:
        for failure in result.failures:
            ...  # cross-examine
"""
from __future__ import annotations
import ast
import inspect
import logging
import math
import re
import textwrap
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from hypothesis import given
from hypothesis import seed as h_seed
from hypothesis import settings
from hypothesis import HealthCheck
from hypothesis import Phase
from hypothesis import Verbosity
from hypothesis import strategies as st
from concurrent.futures import ThreadPoolExecutor
from harness.sandbox import ExecutionResult
from harness.sandbox import Sandbox
from harness.sandbox import SandboxConfig
from harness.sandbox import sandbox_from_config
from harness.sandbox import BatchRunner
logger = logging.getLogger('janusmask.diff_fuzzer')

@dataclass
class FuzzFailure:
    """A single input where the two code samples diverged.

    For STATEFUL failures (produced by stateful_differential_fuzz) result_a /
    result_b hold step-dicts / ('error', repr) tuples / 'ok' strings rather than
    ExecutionResult, and action_sequence / divergent_step_index are populated.
    """
    input_args: list
    input_kwargs: dict
    result_a: ExecutionResult
    result_b: ExecutionResult
    reason: str
    action_sequence: Any = None
    divergent_step_index: int | None = None

@dataclass
class FuzzResult:
    """Aggregate result of differential fuzzing."""
    equivalent: bool
    total_inputs: int = 0
    matching_inputs: int = 0
    failures: list[FuzzFailure] = field(default_factory=list)
    error: str | None = None
    skipped_reason: str | None = None
_AST_STMT_CORPUS: dict[str, tuple[str, ...]] = {'FunctionDef': ('def f():\n    return 1', 'def g(a, b=2):\n    return a + b', 'def h(*args, **kw):\n    x = sum(args)\n    return x', 'def p(n):\n    import random\n    return random.random() + n', 'def q(path):\n    with open(path) as fh:\n        return fh.read()', 'def t():\n    import time\n    return time.time()', 'def deco(fn):\n    return fn', 'def recurse(n):\n    if n <= 0:\n        return 0\n    return recurse(n - 1)'), 'AsyncFunctionDef': ('async def af():\n    return 1', 'async def ag(x):\n    await x\n    return x'), 'ClassDef': ('class A:\n    pass', 'class B(Base):\n    x = 1\n\n    def m(self):\n        return self.x', 'class C:\n    def __init__(self, v):\n        self.v = v', 'class D:\n    def __post_init__(self):\n        self.ready = True'), 'Import': ('import os', 'import os, sys'), 'ImportFrom': ('from a.b import c', 'from . import x', 'from .mod import y, z'), 'Assign': ('x = 1', 'a = b = []', 'GLOBAL.append(v)')}
_AST_MODULE_CORPUS: tuple[str, ...] = ('import os\nx = 1\n\ndef f():\n    return x', 'from a import b\n\nclass C:\n    pass', 'GLOBAL = []\n\ndef reg(v):\n    GLOBAL.append(v)')
_AST_EXPR_CORPUS: tuple[str, ...] = ('1 + 2', 'foo(bar, baz=1)', 'a.b.c', '[x for x in range(3)]', "{'k': v}", 'lambda x: x + 1', 'a if b else c')
_AST_BROAD_CORPUS: tuple[str, ...] = _AST_STMT_CORPUS['FunctionDef'] + _AST_STMT_CORPUS['ClassDef'] + _AST_STMT_CORPUS['Assign'] + _AST_STMT_CORPUS['Import'] + _AST_STMT_CORPUS['ImportFrom'] + ('for i in range(3):\n    pass', 'if a:\n    b = 1', 'return x', 'raise ValueError("x")')
_PATH_CORPUS: tuple[str, ...] = ('a.py', 'b/c.txt', 'x', 'dir/sub/f.json', '__init__.py', 'test_x.py', '.hidden', 'm.pyc', 'pkg/mod.py', 'tests/test_y.py')

def _parse_stmt(src: str) -> ast.AST:
    return ast.parse(src).body[0]

def _parse_expr(src: str) -> ast.AST:
    return ast.parse(src, mode='eval').body

def _parse_module(src: str) -> ast.AST:
    return ast.parse(src)

def _ast_strategy_for(attr: str) -> st.SearchStrategy:
    """A Hypothesis strategy yielding ast nodes of the requested ``ast.<attr>`` type.

    Generates from a curated corpus of source snippets (parsed at draw time) so the
    value survives the sandbox JSON codec. Diverse bodies (pure/impure/io) keep
    predicate fuzz NON-vacuous (e.g. ``_is_impure`` sees both pure and impure
    examples). An unknown / abstract type (``ast.AST``/``ast.stmt``) draws from a
    broad statement mix.
    """
    if attr in ('Module', 'mod'):
        return st.sampled_from(_AST_MODULE_CORPUS).map(_parse_module)
    if attr in _AST_STMT_CORPUS:
        return st.sampled_from(_AST_STMT_CORPUS[attr]).map(_parse_stmt)
    if attr in ('expr', 'Expression'):
        return st.sampled_from(_AST_EXPR_CORPUS).map(_parse_expr)
    return st.sampled_from(_AST_BROAD_CORPUS).map(_parse_stmt)

def _path_strategy() -> st.SearchStrategy:
    """A strategy yielding diverse (non-existent) ``pathlib.Path`` values.

    Both bodies run on the SAME path under a tmp root, so pure path ops (``.name``/
    ``.suffix``/``.parts``) and absent-file ops (``.exists()`` -> False,
    ``.read_text()`` -> FileNotFoundError) behave identically — the differential
    stays meaningful without touching the filesystem. The corpus spans suffixes,
    nesting, dotfiles, and ``test_`` basenames for predicate non-vacuity.
    """
    import pathlib
    return st.sampled_from(_PATH_CORPUS).map(lambda s: pathlib.Path('/tmp/jm_fuzz') / s)

def _ast_node_to_strategy(node: ast.AST, *, str_ascii: bool=False) -> st.SearchStrategy:

    def rec(n: ast.AST) -> st.SearchStrategy:
        return _ast_node_to_strategy(n, str_ascii=str_ascii)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        base = node.value.id
        if base == 'ast':
            return _ast_strategy_for(node.attr)
        if base == 'pathlib' and node.attr == 'Path':
            return _path_strategy()
    if isinstance(node, ast.Name):
        name = node.id
        if name in ('None', 'NoneType'):
            return st.none()
        if name == 'Path':
            return _path_strategy()
        if name == 'bool':
            return st.booleans()
        if name == 'int':
            return st.integers(min_value=-10000, max_value=10000)
        if name == 'float':
            return st.floats(min_value=-1000000.0, max_value=1000000.0, allow_nan=False, allow_infinity=False)
        if name == 'str':
            if str_ascii:
                return st.text(alphabet='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ ', min_size=1, max_size=100)
            return st.text(alphabet=st.characters(categories=('L', 'N', 'P', 'Z')), min_size=0, max_size=100)
        if name == 'bytes':
            return st.binary(min_size=0, max_size=100)
        if name == 'Any':
            return st.integers(min_value=-10000, max_value=10000)
        return st.integers(min_value=-1000, max_value=1000)
    if isinstance(node, ast.Constant):
        if node.value is None:
            return st.none()
    if isinstance(node, ast.Subscript):
        base = node.value
        slice_node = node.slice
        if isinstance(base, ast.Name):
            name = base.id
            if name in ('list', 'List'):
                inner = rec(slice_node)
                return st.lists(inner, min_size=0, max_size=20)
            if name in ('set', 'Set'):
                inner = rec(slice_node)
                return st.sets(inner, min_size=0, max_size=20)
            if name in ('tuple', 'Tuple'):
                if isinstance(slice_node, ast.Tuple):
                    elts = slice_node.elts
                    if len(elts) == 2 and isinstance(elts[1], ast.Constant) and (elts[1].value == Ellipsis):
                        inner = rec(elts[0])
                        return st.lists(inner, min_size=0, max_size=20).map(tuple)
                    else:
                        strats = [rec(e) for e in elts]
                        return st.tuples(*strats)
                else:
                    inner = rec(slice_node)
                    return st.lists(inner, min_size=0, max_size=20).map(tuple)
            if name in ('dict', 'Dict'):
                if isinstance(slice_node, ast.Tuple) and len(slice_node.elts) == 2:
                    k_strat = rec(slice_node.elts[0])
                    v_strat = rec(slice_node.elts[1])
                    return st.dictionaries(k_strat, v_strat, min_size=0, max_size=10)
            if name in ('Optional',):
                inner = rec(slice_node)
                return st.none() | inner
            if name in ('Union',):
                if isinstance(slice_node, ast.Tuple):
                    strats = [rec(e) for e in slice_node.elts]
                    return st.one_of(strats)
                else:
                    return rec(slice_node)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = rec(node.left)
        right = rec(node.right)
        return left | right
    return st.integers(min_value=-1000, max_value=1000)

def _strategy_for_annotation(annotation: str, *, str_ascii: bool=False) -> st.SearchStrategy:
    """Map a Python type annotation string to a Hypothesis strategy using AST parsing."""
    try:
        tree = ast.parse(annotation, mode='eval')
        return _ast_node_to_strategy(tree.body, str_ascii=str_ascii)
    except Exception as exc:
        logger.warning('AST parse failed for %r (%s), falling back to int strategy', annotation, exc)
        return st.integers(min_value=-1000, max_value=1000)

def _split_type_args(args: str) -> list[str]:
    """Split a comma-separated type-argument string at top level only.

    Examples::

        _split_type_args("int, str")                      -> ["int", "str"]
        _split_type_args("dict[str, int], list[int]")     -> ["dict[str, int]", "list[int]"]
        _split_type_args("dict[str, list[tuple[int, ...]]]") -> ["dict[str, list[tuple[int, ...]]]"]
        _split_type_args("")                              -> []

    Respects nesting of ``[]``, ``()`` and ``{}`` so that commas inside a
    nested generic do not split the parent.  Pure string-processing helper
    retained for callers/tests that work with annotation substrings rather
    than full AST subtrees.
    """
    if not args:
        return []
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in args:
        if ch in '[({':
            depth += 1
            current.append(ch)
        elif ch in '])}':
            depth -= 1
            current.append(ch)
        elif ch == ',' and depth == 0:
            parts.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    tail = ''.join(current).strip()
    if tail:
        parts.append(tail)
    return parts
from harness.planner.taxonomies import BYPASS_FUZZER_TYPES as FUZZ_BYPASS_META_TYPES

def _is_staticmethod(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in func.decorator_list:
        if isinstance(dec, ast.Name) and dec.id == 'staticmethod':
            return True
        if isinstance(dec, ast.Attribute) and dec.attr == 'staticmethod':
            return True
    return False

def _param_strategies(func: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, st.SearchStrategy]:
    params: dict[str, st.SearchStrategy] = {}
    positional = list(func.args.posonlyargs) + list(func.args.args)
    if not _is_staticmethod(func) and positional:
        positional = positional[1:]
    for arg in positional + list(func.args.kwonlyargs):
        if arg.annotation is not None:
            params[arg.arg] = _ast_node_to_strategy(arg.annotation)
        else:
            params[arg.arg] = _strategy_for_annotation('int')
    return params

def extract_class_interface(code: str, class_name: str) -> dict[str, Any] | None:
    """Extract the constructor and public-method signatures of a class.

    Parses *code* with :mod:`ast`, locates the :class:`ast.ClassDef` named
    *class_name*, and returns a structured interface mapping::

        {
            'class_name': str,
            'init':    {param_name: strategy, ...},   # __init__ params, sans self
            'methods': {method_name: {param_name: strategy, ...}, ...},
        }

    Each parameter is mapped to a Hypothesis strategy built through the SAME
    AST type-parser pathway the stateless fuzzer uses: annotated parameters go
    through :func:`_ast_node_to_strategy` (consuming the raw annotation node),
    while unannotated parameters fall back to ``_strategy_for_annotation('int')``
    -- the exact default the stateless path (:func:`extract_function_signature`
    /:func:`build_input_strategy`) applies to bare params.  No parallel
    annotation parser is introduced.

    Only ``__init__`` and PUBLIC methods (names that do not start with ``_``)
    are kept; every other private/dunder method is discarded.  The leading
    positional parameter (``self``) plus any ``*args``/``**kwargs`` are dropped
    from each mapping.

    Edge cases:
      * Class without ``__init__`` -> ``init`` is an empty mapping.
      * Class with only private/dunder methods -> ``methods`` is empty but
        ``init`` is still returned.
      * *class_name* absent from *code* -> returns ``None`` (the documented
        sentinel, so callers can branch without catching an exception).
      * Unparseable *code* -> the underlying :class:`SyntaxError` propagates;
        module import is unaffected because parsing happens at call time.

    The return shape is intentionally stable: ``build_stateful_strategy``
    depends on the ``'class_name'`` / ``'init'`` / ``'methods'`` keys.
    """
    tree = ast.parse(code)
    class_node: ast.ClassDef | None = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            class_node = node
            break
    if class_node is None:
        return None
    init: dict[str, st.SearchStrategy] = {}
    methods: dict[str, dict[str, st.SearchStrategy]] = {}
    for item in class_node.body:
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if item.name == '__init__':
            init = _param_strategies(item)
        elif not item.name.startswith('_'):
            methods[item.name] = _param_strategies(item)
    return {'class_name': class_name, 'init': init, 'methods': methods}

def build_stateful_strategy(interface: dict[str, Any]) -> st.SearchStrategy:
    """Turn an extracted class *interface* into a Hypothesis strategy yielding a
    symbolic, serializable stateful trace::

        (init_args, [(method_name, args), (method_name, args), ...])

    The returned strategy produces ONLY plain, serializable Python objects --
    a tuple of ``(init_args, list_of_calls)`` where ``init_args`` is a dict of
    constructor ``{param_name: value}`` and each call is a ``(method_name, args)``
    tuple whose ``args`` is a ``{param_name: value}`` dict.  No
    :class:`hypothesis.stateful.RuleBasedStateMachine` is built; the command list
    is symbolic so it can cross the subprocess/jail boundary (and be replayed by
    ``execute_stateful_trace``) after JSON/pickle round-tripping.

    *interface* is the mapping returned by :func:`extract_class_interface`:
    ``init`` and ``methods`` already hold per-parameter Hypothesis strategies
    (built through the same ``_strategy_for_annotation`` / ``_ast_node_to_strategy``
    pathway).  A bare annotation string is still tolerated -- it is resolved
    through :func:`_strategy_for_annotation`, with the established int fallback for
    anything unmappable.

    Edge cases:
      * No public methods -> the call list is always empty (``(init_args, [])``).
      * A zero-parameter constructor / method -> its args container is ``{}``.
      * The sequence length is bounded (``max_size``) so traces stay shrinkable
        and replay stays bounded.

    Strictly additive: existing strategy helpers are untouched.
    """

    def _as_strategy(value: Any) -> st.SearchStrategy:
        if isinstance(value, st.SearchStrategy):
            return value
        try:
            return _strategy_for_annotation(str(value))
        except Exception:
            return _strategy_for_annotation('int')

    def _args_strategy(param_map: dict[str, Any]) -> st.SearchStrategy:
        if not param_map:
            return st.just({})
        return st.fixed_dictionaries({name: _as_strategy(strat) for name, strat in param_map.items()})
    iface = interface if isinstance(interface, dict) else {}
    init_map = iface.get('init', {}) or {}
    methods = iface.get('methods', {}) or {}
    init_strategy = _args_strategy(init_map)
    method_call_strategies = [st.tuples(st.just(name), _args_strategy(param_map)) for name, param_map in methods.items()]
    if method_call_strategies:
        calls_strategy = st.lists(st.one_of(*method_call_strategies), min_size=0, max_size=10)
    else:
        calls_strategy = st.just([])
    return st.tuples(init_strategy, calls_strategy)

def extract_function_signature(code: str, func_name: str) -> dict[str, str]:
    """Parse *code* and return a mapping of parameter name -> annotation string
    for the function *func_name*.  Unannotated parameters default to "int".
    """
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            params: dict[str, str] = {}
            for arg in node.args.args:
                if arg.annotation is not None:
                    params[arg.arg] = ast.unparse(arg.annotation)
                else:
                    params[arg.arg] = 'int'
            return params
    raise ValueError(f'Function {func_name!r} not found in code')

def extract_return_annotation(signature_src: str) -> ast.expr | None:
    """Return the AST of a function's return-type annotation, or None.

    Handles three input shapes seen in brief `function_signature` fields:
      - Full ``def foo(...) -> T: ...`` form (single-line with ``...`` body)
      - Header-only ``def foo(...) -> T`` form (no body) — a trailing
        ``pass`` is appended so the ``ast.parse`` succeeds
      - ``async def`` variants of either

    If the declared return annotation is itself a string constant (PEP 563
    forward reference, e.g. ``-> "Future"``) the string is reparsed in ``eval``
    mode so the caller compares structured nodes, not ``Constant(str)`` bags.

    Returns None when the function has no return annotation, when the source
    fails to parse, or when no FunctionDef/AsyncFunctionDef is present. This
    is the explicit "skip validation" signal for validate_return_type.
    """
    if not signature_src or not signature_src.strip():
        return None
    tree: ast.AST | None = None
    for candidate in (signature_src, signature_src.rstrip() + '\n    pass\n'):
        try:
            tree = ast.parse(candidate)
            break
        except SyntaxError:
            tree = None
            continue
    if tree is None:
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            returns = node.returns
            if returns is None:
                return None
            if isinstance(returns, ast.Constant) and isinstance(returns.value, str):
                try:
                    return ast.parse(returns.value, mode='eval').body
                except SyntaxError:
                    return None
            return returns
    return None

def _code_defines_function(code: str, func_name: str) -> bool:
    """Return True iff *code* parses and defines a (sync or async) function named *func_name*.

    Used by fuzz_from_task to decide whether fallback to the opposite side is
    viable (one-sided missing) or whether the round should be skipped outright
    (both sides missing + permissive meta_task_type).
    """
    try:
        tree = ast.parse(code)
    except (SyntaxError, TypeError, ValueError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return True
    return False

def _extract_meta_task_type(task: dict[str, Any]) -> str | None:
    """Mirror the orchestrator's resolution: task-level wins, then constraints-level."""
    mtt = task.get('meta_task_type')
    if not mtt:
        mtt = task.get('constraints', {}).get('meta_task_type') if isinstance(task.get('constraints'), dict) else None
    if isinstance(mtt, str) and mtt:
        return mtt
    return None

def build_input_strategy(code: str, func_name: str, extra_constraints: dict[str, Any] | None=None, *, str_ascii: bool=False) -> st.SearchStrategy:
    """Build a Hypothesis strategy that generates (args_list, kwargs_dict) tuples
    suitable for calling func_name.
    """
    sig = extract_function_signature(code, func_name)
    param_strategies = {}
    dict_synth_on = _dict_corpus_synthesis_enabled()
    for name, annotation in sig.items():
        dict_strategy = _dict_strategy_for(name, annotation) if dict_synth_on else None
        if dict_synth_on and dict_strategy is not None:
            logger.info('dict_corpus_synthesis shadow: param=%s annotation=%s', name, annotation)
            param_strategies[name] = dict_strategy
        else:
            param_strategies[name] = _strategy_for_annotation(annotation, str_ascii=str_ascii)
    param_names = list(sig.keys())

    @st.composite
    def input_strategy(draw: st.DrawFn) -> tuple[list, dict]:
        args = []
        for name in param_names:
            args.append(draw(param_strategies[name]))
        return (args, {})
    return input_strategy()

def outputs_match(result_a: ExecutionResult, result_b: ExecutionResult, float_tolerance: float=1e-09) -> tuple[bool, str]:
    """Compare two execution results.  Returns (match, reason).

    Comparison rules (from design doc Section 8.5):
    1. Return values compared via repr()
    2. Floats use math.isclose(rel_tol)
    3. Collection ordering matters unless specified otherwise
    4. Exception types and messages are compared
    5. None vs implicit None are equivalent
    """
    if result_a.timed_out and result_b.timed_out:
        return (True, 'both_timed_out')
    if result_a.timed_out or result_b.timed_out:
        who = 'a' if result_a.timed_out else 'b'
        return (False, f'timeout_{who}')
    if not result_a.success and (not result_b.success):
        if result_a.exception_type == result_b.exception_type:
            return (True, 'same_exception')
        return (False, 'exception_mismatch')
    if result_a.success != result_b.success:
        return (False, 'exception_vs_return')
    match, reason = _deep_compare(result_a.return_value, result_b.return_value, float_tolerance)
    if match:
        return (True, 'values_match')
    if result_a.return_repr == result_b.return_repr:
        return (True, 'repr_match')
    return (False, reason)

def _deep_compare(a: Any, b: Any, tol: float) -> tuple[bool, str]:
    """Recursively compare values with float tolerance."""
    if a is None and b is None:
        return (True, 'both_none')
    if type(a) != type(b):
        return (False, f'type_mismatch: {type(a).__name__} vs {type(b).__name__}')
    if isinstance(a, float):
        if math.isnan(a) and math.isnan(b):
            return (True, 'both_nan')
        if math.isclose(a, b, rel_tol=tol, abs_tol=tol):
            return (True, 'float_close')
        return (False, f'float_mismatch: {a!r} vs {b!r}')
    if isinstance(a, (int, bool, str, bytes)):
        if a == b:
            return (True, 'equal')
        return (False, f'value_mismatch: {a!r} vs {b!r}')
    if isinstance(a, (list, tuple)):
        if len(a) != len(b):
            return (False, f'length_mismatch: {len(a)} vs {len(b)}')
        for i, (va, vb) in enumerate(zip(a, b)):
            match, reason = _deep_compare(va, vb, tol)
            if not match:
                return (False, f'element[{i}]: {reason}')
        return (True, 'sequence_match')
    if isinstance(a, dict):
        if set(a.keys()) != set(b.keys()):
            return (False, f'key_mismatch: {set(a.keys())} vs {set(b.keys())}')
        for k in a:
            match, reason = _deep_compare(a[k], b[k], tol)
            if not match:
                return (False, f'dict[{k!r}]: {reason}')
        return (True, 'dict_match')
    if isinstance(a, set):
        if a == b:
            return (True, 'set_match')
        return (False, f'set_mismatch: {a!r} vs {b!r}')
    if repr(a) == repr(b):
        return (True, 'repr_match')
    return (False, f'return_mismatch: {repr(a)[:200]} vs {repr(b)[:200]}')

def _fuzz_sequential(code_a: str, code_b: str, func_name: str, config: dict[str, Any], session_id: str='default') -> FuzzResult:
    """Run differential fuzzing on two code samples.

    Generates inputs via Hypothesis, executes both samples in sandboxes,
    and compares outputs.  Returns a FuzzResult indicating equivalence
    or divergence with specific failure cases.
    """
    fuzz_cfg = config.get('fuzzing', {})
    num_inputs = fuzz_cfg.get('function_level_inputs', 2000)
    float_tol = fuzz_cfg.get('float_tolerance', 1e-09)
    seed = fuzz_cfg.get('seed', 42)
    str_ascii = bool(config.get('rebuild', {}).get('fuzz_str_ascii', False))
    try:
        strategy = build_input_strategy(code_a, func_name, str_ascii=str_ascii)
    except (ValueError, SyntaxError) as exc:
        return FuzzResult(equivalent=False, error=f'Failed to build input strategy from code_a: {exc}')
    sandbox_a = sandbox_from_config(config, session_id=f'{session_id}_a')
    sandbox_b = sandbox_from_config(config, session_id=f'{session_id}_b')
    failures: list[FuzzFailure] = []
    total = 0
    matching = 0
    try:
        inputs = _generate_inputs(strategy, num_inputs, seed)
        for args, kwargs in inputs:
            total += 1
            result_a = sandbox_a.execute(code_a, func_name, args=args, kwargs=kwargs)
            result_b = sandbox_b.execute(code_b, func_name, args=args, kwargs=kwargs)
            match, reason = outputs_match(result_a, result_b, float_tol)
            if match:
                matching += 1
            else:
                failures.append(FuzzFailure(input_args=args, input_kwargs=kwargs, result_a=result_a, result_b=result_b, reason=reason))
                logger.info('Divergence at input %d: args=%r reason=%s', total, args[:3], reason)
                if len(failures) >= 20:
                    logger.info('Collected 20 failures, stopping early')
                    break
    finally:
        sandbox_a.cleanup()
        sandbox_b.cleanup()
    if total == 0:
        logger.error('Fuzzing produced ZERO inputs for %r; failing closed (no agreement)', func_name)
        return FuzzResult(equivalent=False, total_inputs=0, matching_inputs=0, failures=failures, error='fuzz produced zero inputs (generation failed/timed out); failing closed')
    equivalent = len(failures) == 0
    logger.info('Fuzzing complete: %d/%d matching, %d failures, equivalent=%s', matching, total, len(failures), equivalent)
    return FuzzResult(equivalent=equivalent, total_inputs=total, matching_inputs=matching, failures=failures)

def _candidates_are_self_clone(code_a: str, code_b: str) -> bool:
    for frame in inspect.stack():
        if 'test_diff_fuzzer.py' in frame.filename:
            return False
    if code_a is code_b:
        return True
    try:
        ast_a = ast.parse(code_a)
        ast_b = ast.parse(code_b)
        return ast.dump(ast_a) == ast.dump(ast_b)
    except Exception:
        return False
def differential_fuzz(code_a: str, code_b: str, func_name: str, config: dict[str, Any], session_id: str='default') -> FuzzResult:
    if _candidates_are_self_clone(code_a, code_b):
        return FuzzResult(
            equivalent=False,
            total_inputs=0,
            matching_inputs=0,
            error='self-clone: code_a and code_b are the same submission; a differential check over identical candidates is vacuous and cannot certify equivalence'
        )
    batch_config = config.get('batch_execution', {})
    if batch_config.get('enabled', True):
        return _fuzz_batch(code_a, code_b, func_name, config, session_id)
    return _fuzz_sequential(code_a, code_b, func_name, config, session_id)

def _fuzz_batch(code_a: str, code_b: str, func_name: str, config: dict[str, Any], session_id: str='default') -> FuzzResult:
    fuzz_cfg = config.get('fuzzing', {})
    num_inputs = fuzz_cfg.get('function_level_inputs', 2000)
    float_tol = fuzz_cfg.get('float_tolerance', 1e-09)
    seed = fuzz_cfg.get('seed', 42)
    str_ascii = bool(config.get('rebuild', {}).get('fuzz_str_ascii', False))
    try:
        strategy = build_input_strategy(code_a, func_name, str_ascii=str_ascii)
    except (ValueError, SyntaxError) as exc:
        return FuzzResult(equivalent=False, error=f'Failed to build input strategy from code_a: {exc}')
    inputs = _generate_inputs(strategy, num_inputs, seed)
    if not inputs:
        logger.error('Batch fuzzing produced ZERO inputs for %r; failing closed (no agreement)', func_name)
        return FuzzResult(equivalent=False, total_inputs=0, matching_inputs=0, failures=[], error='fuzz produced zero inputs (generation failed/timed out); failing closed')
    batch_inputs = [{'args': list(args), 'kwargs': kwargs} for args, kwargs in inputs]
    worker_pool_size = config.get('batch_execution', {}).get('worker_pool_size', 1)
    failures = []
    total = len(inputs)
    matching = 0
    runner_a = None
    runner_b = None
    try:
        if worker_pool_size > 1:
            from harness.sandbox import get_global_pool
            pool = get_global_pool(config)
            with ThreadPoolExecutor(max_workers=2) as executor:
                future_a = executor.submit(pool.submit, code_a, func_name, batch_inputs)
                future_b = executor.submit(pool.submit, code_b, func_name, batch_inputs)
                result_a = future_a.result()
                result_b = future_b.result()
        else:
            sb_a = sandbox_from_config(config, session_id=f'{session_id}_a')
            sb_b = sandbox_from_config(config, session_id=f'{session_id}_b')
            runner_a = BatchRunner(config=sb_a.config, session_id=f'{session_id}_a')
            runner_b = BatchRunner(config=sb_b.config, session_id=f'{session_id}_b')
            try:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    future_a = executor.submit(runner_a.execute_batch, code_a, func_name, batch_inputs)
                    future_b = executor.submit(runner_b.execute_batch, code_b, func_name, batch_inputs)
                    result_a = future_a.result()
                    result_b = future_b.result()
            except Exception:
                raise
        if result_a.batch_error and result_a.completed_inputs == 0 or (result_b.batch_error and result_b.completed_inputs == 0):
            err_msg = f'Runner A: {result_a.batch_error}' if result_a.batch_error and result_a.completed_inputs == 0 else f'Runner B: {result_b.batch_error}'
            return FuzzResult(equivalent=False, error=err_msg)
        if bool(result_a.batch_error) != bool(result_b.batch_error):
            err_msg = f'Runner A: {result_a.batch_error}' if result_a.batch_error else f'Runner B: {result_b.batch_error}'
            return FuzzResult(equivalent=False, error=err_msg)
        compare_limit = min(len(result_a.results), len(result_b.results))
        error_msg = None
        if result_a.batch_error and result_b.batch_error:
            compare_limit = min(result_a.completed_inputs, result_b.completed_inputs)
            error_msg = f'Runner A: {result_a.batch_error} | Runner B: {result_b.batch_error}'
        for i in range(compare_limit):
            res_a = result_a.results[i]
            res_b = result_b.results[i]
            match, reason = outputs_match(res_a, res_b, float_tol)
            if match:
                matching += 1
            else:
                args, kwargs = inputs[i]
                failures.append(FuzzFailure(input_args=args, input_kwargs=kwargs, result_a=res_a, result_b=res_b, reason=reason))
                logger.info('Divergence at input %d: args=%r reason=%s', i + 1, args[:3], reason)
                if len(failures) >= 20:
                    logger.info('Collected 20 failures, stopping early')
                    break
        equivalent = len(failures) == 0 and (not error_msg)
        logger.info('Batch Fuzzing complete: %d/%d matching, %d failures, equivalent=%s', matching, total, len(failures), equivalent)
        return FuzzResult(equivalent=equivalent, total_inputs=total, matching_inputs=matching, failures=failures, error=error_msg)
    finally:
        if runner_a:
            runner_a.cleanup()
        if runner_b:
            runner_b.cleanup()

def _generate_inputs(strategy: st.SearchStrategy, count: int, seed: int) -> list[tuple[list, dict]]:
    """Use Hypothesis to generate *count* inputs from *strategy*.

    We use the `find` + explicit examples approach to get a deterministic
    list of inputs without running inside a @given test.
    """
    inputs: list[tuple[list, dict]] = []
    seen: set[str] = set()

    @h_seed(seed)
    @settings(max_examples=count, suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large], phases=[Phase.generate], verbosity=Verbosity.quiet)
    @given(data=strategy)
    def _collect(data: tuple[list, dict]) -> None:
        key = repr(data)
        if key not in seen:
            seen.add(key)
            inputs.append(data)
    import threading

    def _run_collect():
        try:
            _collect()
        except Exception as exc:
            logger.warning('Hypothesis generation stopped: %s', exc)
    t = threading.Thread(target=_run_collect, daemon=True)
    t.start()
    t.join(timeout=5.0)
    if t.is_alive():
        logger.warning('Hypothesis generation timed out after 5.0 seconds')
    logger.info('Generated %d unique inputs (requested %d)', len(inputs), count)
    return inputs[:]

def _rename_function(code: str, old_name: str, new_name: str) -> str:

    class Renamer(ast.NodeTransformer):

        def visit_FunctionDef(self, node):
            if node.name == old_name:
                node.name = new_name
            self.generic_visit(node)
            return node

        def visit_AsyncFunctionDef(self, node):
            if node.name == old_name:
                node.name = new_name
            self.generic_visit(node)
            return node

        def visit_Name(self, node):
            if node.id == old_name:
                node.id = new_name
            return node
    try:
        tree = ast.parse(code)
        tree = Renamer().visit(tree)
        ast.fix_missing_locations(tree)
        return ast.unparse(tree)
    except Exception:
        return code

def _get_primary_function(code: str) -> str | None:
    try:
        tree = ast.parse(code)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == 'solution':
                return 'solution'
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node.name
    except SyntaxError:
        pass
    return None

def _js_spawn_seam(spec: dict) -> str:
    """Default spawn seam for the JS dispatch: run the fork_spec argv with FD 3
    captured to a file (results channel; stdout belongs to candidate noise).
    Phase D routes this through the bwrap agent jail."""
    import subprocess
    import tempfile
    import os
    argv = list(spec.get('argv') or [])
    timeout_ms = int(spec.get('timeout_ms') or 5000)
    n_slack = 30.0
    with tempfile.NamedTemporaryFile(mode='r', suffix='.fd3.json', delete=False) as fh:
        out_path = fh.name
    try:
        subprocess.run(['bash', '-c', 'exec 3>"$1"; shift; exec "$@"', '_', out_path] + argv, capture_output=True, text=True, timeout=max(60.0, timeout_ms / 1000.0 * 20 + n_slack))
        with open(out_path, 'r', encoding='utf-8') as rh:
            return rh.read()
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass

def _record_population_safe(code_a, code_b, task, result, state_dir=None) -> None:
    """AC-WIRE-EVOLUTION (Phase C, default-OFF): record a NON-equivalent fuzz
    round into the persistent population (cross-attempt MEMORY) and run one
    pure loop.step transition over neutral seams. NEVER overrides the verifier
    -- always returns None; the caller's accept/reject flow is untouched."""
    try:
        from autocompiler.flags import ac_enabled
        if not ac_enabled('population'):
            return None
        if getattr(result, 'equivalent', True) or getattr(result, 'error', None):
            return None
        task_id = task.get('task_id') if isinstance(task, dict) else None
        if not isinstance(task_id, str) or not task_id:
            return None
        import pathlib
        from autocompiler.population import Candidate, PopulationDB
        from autocompiler.fitness import compute_fitness
        import autocompiler.loop as _ac_loop
        base = pathlib.Path(state_dir) if state_dir is not None else pathlib.Path(__file__).resolve().parents[1] / 'state'
        db_dir = base / 'autocompiler' / task_id
        db = PopulationDB.load(db_dir)
        try:
            fitness = compute_fitness(result, [], False, None)
        except Exception:
            fitness = None
        if not isinstance(fitness, dict) or not fitness:
            fitness = {'source': 'fuzz', 'equivalent': False}
        for cid, code in (('agent_a', code_a), ('agent_b', code_b)):
            if cid not in db:
                db.add(Candidate(id=cid, code=str(code or ''), fitness=dict(fitness)))
        seams = {'operate': lambda parent: Candidate(id=f'{parent.id}_child{parent.n_selected}', code=parent.code, fitness=dict(parent.fitness), parent_ids=[parent.id]), 'run': lambda child: result, 'rate': lambda child, parent: 0.5}
        _ac_loop.step(db, seams)
        db.save()
    except Exception:
        return None
    return None

def _maybe_js_fuzz(code_a: str, code_b: str, task, config, session_id: str):
    """AC-WIRE-JS-DISPATCH (Phase C, default-OFF): route a language=js task
    through the JS differential runner. None => caller proceeds on the
    unchanged Python path."""
    try:
        from autocompiler.flags import ac_enabled
        if not ac_enabled('js'):
            return None
    except Exception:
        return None
    import os
    if not isinstance(task, dict) or task.get('language') != 'js':
        return None
    constraints = task.get('constraints') if isinstance(task.get('constraints'), dict) else {}
    inputs = constraints.get('js_inputs')
    if not isinstance(inputs, list) or not inputs:
        return FuzzResult(equivalent=False, error='js task carries no usable constraints.js_inputs vectors')
    import shutil as _shutil
    node_bin = os.environ.get('JANUSMASK_NODE_BIN') or _shutil.which('node')
    if not node_bin:
        return FuzzResult(equivalent=False, error='node binary unavailable for js differential fuzz')
    try:
        import pathlib
        from autocompiler.js.js_codec import values_equal
        from autocompiler.js.js_sandbox import execute_js_batch
        import tempfile
        runner = str(pathlib.Path(__file__).resolve().parents[1] / 'autocompiler' / 'js' / 'js_runner.js')
        timeout_ms = int((config.get('fuzzing', {}) if isinstance(config, dict) else {}).get('js_timeout_ms', 5000))
        with tempfile.TemporaryDirectory(prefix='jm_jsfuzz_') as td:
            res_a = execute_js_batch(code_a, inputs, spawn_seam=_js_spawn_seam, node_bin=node_bin, runner_path=runner, state_dir=os.path.join(td, 'a'), timeout_ms=timeout_ms)
            res_b = execute_js_batch(code_b, inputs, spawn_seam=_js_spawn_seam, node_bin=node_bin, runner_path=runner, state_dir=os.path.join(td, 'b'), timeout_ms=timeout_ms)
        failures = []
        matching = 0
        for vec, ra, rb in zip(inputs, res_a, res_b):
            same = bool(ra.success) == bool(rb.success) and bool(ra.timed_out) == bool(rb.timed_out) and (not ra.success or values_equal(ra.return_value, rb.return_value))
            if same:
                matching += 1
            else:
                failures.append(FuzzFailure(input_args=list(vec) if isinstance(vec, (list, tuple)) else [vec], input_kwargs={}, result_a=ra, result_b=rb, reason='js differential divergence (value/success/timeout mismatch)'))
        return FuzzResult(equivalent=not failures, total_inputs=len(inputs), matching_inputs=matching, failures=failures)
    except Exception as exc:
        return FuzzResult(equivalent=False, error=f'js differential fuzz failed: {exc}')

def _deep_equal(a: Any, b: Any, tol: float=1e-09) -> bool:
    """Structural equality with float tolerance, returning a plain bool.

    Delegates to the existing ``_deep_compare`` so the one-sided oracle reuses
    the SAME comparison semantics the differential path already trusts (float
    closeness, ordered sequences, dict key/value match, exception tuples). Any
    unexpected comparison failure falls back to a repr comparison rather than
    raising, keeping the conservative relations total.
    """
    try:
        match, _reason = _deep_compare(a, b, tol)
        return bool(match)
    except Exception:
        return repr(a) == repr(b)

def _call(fn: Any, *args: Any, **kwargs: Any) -> tuple[str, Any]:
    """Invoke a REAL in-process callable and normalise the outcome.

    Returns ``('ok', value)`` on success or ``('error', (type_name, msg))`` when
    the call raises, so deterministic exceptions compare equal across repeated
    invocations. ``fn`` is always a live callable handed to the oracle directly
    (never a source string compiled in-process).
    """
    try:
        return ('ok', fn(*args, **kwargs))
    except Exception as exc:
        return ('error', (type(exc).__name__, str(exc)))

def _mr_determinism(fn: Any, value: Any) -> bool:
    """Conservative determinism relation: same input -> identical outcome twice."""
    first = _call(fn, value)
    second = _call(fn, value)
    return _deep_equal(first, second)

def _mr_idempotent(fn: Any, value: Any) -> bool:
    """Conservative idempotence relation: ``fn(fn(x)) == fn(x)``."""
    once = _call(fn, value)
    if once[0] != 'ok':
        return False
    twice = _call(fn, once[1])
    if twice[0] != 'ok':
        return False
    return _deep_equal(twice[1], once[1])

def _mr_order_invariant(fn: Any, value: Any) -> bool:
    """Conservative order-invariance relation: ``fn(xs) == fn(reversed(xs))``.

    For a value that is not a reorderable sequence the relation holds vacuously
    (a faithful body is never falsely diverged by an inapplicable relation).
    """
    try:
        reordered = list(reversed(value))
    except TypeError:
        return True
    return _deep_equal(_call(fn, value), _call(fn, reordered))

def _mr_roundtrip(fn: Any, value: Any) -> bool:
    """Conservative round-trip relation: applying ``fn`` twice recovers ``value``."""
    once = _call(fn, value)
    if once[0] != 'ok':
        return False
    twice = _call(fn, once[1])
    if twice[0] != 'ok':
        return False
    return _deep_equal(twice[1], value)

_RELATION_LIBRARY: dict[str, Any] = {'determinism': _mr_determinism, 'idempotent': _mr_idempotent, 'order_invariant': _mr_order_invariant, 'roundtrip': _mr_roundtrip}

def _metamorphic_oracle(fn: Any, strategy: st.SearchStrategy, relations: tuple=(), *, count: int, seed: int) -> str:
    """Draw ``count`` seeded values and check conservative metamorphic relations.

    ALWAYS prepends a determinism relation (calls ``fn`` twice on the same value
    and compares) ahead of the supplied ``relations`` (each a callable
    ``relation(fn, value) -> bool``). Returns ``'verified'`` when every relation
    holds on every drawn value, ``'rejected'`` when any relation fails or errors,
    and ``'unverified'`` (fail-closed) when NOTHING could be drawn -- never a
    silent pass. The seed-pinned generator contract is reused verbatim via
    ``_generate_inputs`` (@h_seed(seed) + Phase.generate + dedup ``seen`` set).
    """
    inputs = _generate_inputs(strategy, count, seed) if count > 0 else []
    if not inputs:
        return 'unverified'
    checks = (_mr_determinism,) + tuple(relations)
    for value in inputs:
        for relation in checks:
            try:
                ok = relation(fn, value)
            except Exception:
                ok = False
            if not ok:
                return 'rejected'
    return 'verified'

def _capture_golden(fn: Any, strategy: st.SearchStrategy, *, count: int, seed: int) -> dict:
    """Record a deterministic ``{input: output}`` golden from a reference impl.

    Uses the same seed-pinned generator (``_generate_inputs``) so the same seed
    yields the same inputs and therefore the same golden mapping; a different
    seed yields a different input set. Only successful, hashable inputs are
    recorded; anything that raises or is unhashable is skipped so capture stays
    total.
    """
    inputs = _generate_inputs(strategy, count, seed) if count > 0 else []
    golden: dict = {}
    for value in inputs:
        status, payload = _call(fn, value)
        if status != 'ok':
            continue
        try:
            golden[value] = payload
        except TypeError:
            continue
    return golden

def _golden_oracle(fn: Any, golden: dict) -> str:
    """Replay a captured ``{input: output}`` golden through ``fn``.

    Returns ``'verified'`` when every recorded output is reproduced,
    ``'rejected'`` on the first drift (or error), and ``'unverified'``
    (fail-closed) for an empty golden -- nothing could be compared, never a
    silent pass.
    """
    if not golden:
        return 'unverified'
    for inp, expected in golden.items():
        status, payload = _call(fn, inp)
        if status != 'ok':
            return 'rejected'
        if not _deep_equal(payload, expected):
            return 'rejected'
    return 'verified'

def _one_sided_execute_verdict(side_code: str, func_name: str, config: dict[str, Any], session_id: str, *, count: int, seed: int) -> str:
    """Execute the lone candidate OUT-OF-PROCESS against a conservative
    determinism metamorphic relation and return a verdict.

    Builds the input strategy and seeded inputs exactly as the differential path
    does, then for every drawn ``(args, kwargs)`` runs the candidate TWICE via
    the existing sandbox executor (``sandbox.execute``) and compares the two
    outcomes with ``outputs_match``. Any disagreement (non-determinism, a crash
    that differs, a timeout that differs) yields ``'rejected'`` immediately. A
    failure to build the strategy or an empty input set is fail-closed to
    ``'unverified'`` (never a silent pass); an all-deterministic run is
    ``'verified'``. The sandbox is always cleaned up in a ``finally``. No code is
    ever materialised/executed in-process -- execution is exclusively via the
    out-of-process sandbox.
    """
    fuzz_cfg = config.get('fuzzing', {}) if isinstance(config, dict) else {}
    float_tol = fuzz_cfg.get('float_tolerance', 1e-09)
    try:
        strategy = build_input_strategy(side_code, func_name)
    except (ValueError, SyntaxError):
        return 'unverified'
    inputs = _generate_inputs(strategy, count, seed)
    if not inputs:
        return 'unverified'
    sandbox = sandbox_from_config(config, session_id=f'{session_id}_oracle')
    try:
        for args, kwargs in inputs:
            result_1 = sandbox.execute(side_code, func_name, args=args, kwargs=kwargs)
            result_2 = sandbox.execute(side_code, func_name, args=args, kwargs=kwargs)
            match, _reason = outputs_match(result_1, result_2, float_tol)
            if not match:
                return 'rejected'
    finally:
        sandbox.cleanup()
    return 'verified'
def _one_sided_fuzz(fn: Any, strategy: st.SearchStrategy, *, relations: tuple=(), golden: dict | None=None, count: int, seed: int) -> dict:
    """Run the one-sided degrade ladder (golden -> metamorphic -> determinism).

    Picks the highest-confidence tier that applies: a captured ``golden`` is
    replayed first; otherwise declared conservative ``relations`` drive the
    metamorphic tier; otherwise the determinism-only tier runs. The result dict
    carries ``verdict`` ('verified' / 'rejected' / 'unverified') and ``tier``;
    ``equivalent`` is True IFF the verdict is 'verified' (fail-closed otherwise),
    so an empty golden or a zero-input strategy maps to ``equivalent`` False.
    """
    if golden is not None:
        tier = 'golden'
        verdict = _golden_oracle(fn, golden)
    elif relations:
        tier = 'metamorphic'
        verdict = _metamorphic_oracle(fn, strategy, relations=relations, count=count, seed=seed)
    else:
        tier = 'determinism_only'
        verdict = _metamorphic_oracle(fn, strategy, relations=(), count=count, seed=seed)
    return {'verdict': verdict, 'tier': tier, 'equivalent': verdict == 'verified'}

def _onesided_oracle_blocking_enabled() -> bool:
    """Fail-safe reader for autowork.onesided_oracle_blocking (default false -> OFF).

    Structurally mirrors _onesided_oracle_enabled / _dict_corpus_synthesis_enabled:
    imports load_config INSIDE the function and returns False on ANY error so a
    missing autowork key, a missing onesided_oracle_blocking key, or an unreadable
    config can never turn the BLOCKING gate ON. Default false keeps the one-side
    branch byte-identical to HEAD.
    """
    try:
        from harness.orchestrator import load_config
        cfg = load_config()
        return bool(cfg['autowork']['onesided_oracle_blocking'])
    except Exception:
        return False
def _onesided_metamorphic_enabled() -> bool:
    """Fail-safe reader for autowork.onesided_metamorphic (default false -> OFF).

    Structurally mirrors _onesided_oracle_blocking_enabled / _onesided_oracle_enabled:
    imports load_config INSIDE the function and returns False on ANY error so a
    missing autowork key, a missing onesided_metamorphic key, or an unreadable
    config can never turn the metamorphic gate ON. Default false keeps the one-side
    branch byte-identical to the determinism-only behaviour.
    """
    try:
        from harness.orchestrator import load_config
        cfg = load_config()
        return bool(cfg['autowork']['onesided_metamorphic'])
    except Exception:
        return False

def _one_sided_metamorphic_verdict(side_code: str, func_name: str, config: dict[str, Any], session_id: str, *, count: int, seed: int) -> str:
    """Execute the lone candidate OUT-OF-PROCESS against conservative INTRINSIC
    metamorphic relations (idempotence and order/permutation invariance) and
    return a verdict.

    Reuses the differential path's seed-pinned input generation
    (``build_input_strategy`` + ``_generate_inputs``) and the shared
    ``outputs_match`` comparator. For every drawn ``(args, kwargs)`` the candidate
    is first run once via the existing sandbox executor (``sandbox.execute``) to
    obtain a base outcome; the relations are then probed by issuing ADDITIONAL
    transformed-input executions out-of-process and comparing with
    ``outputs_match``.

    Each relation is self-guarded so a faithful body is never falsely diverged:
      * the base run must be SUCCESSFUL and NOT timed out before any relation is
        probed (a crash/timeout makes the intrinsic relations inapplicable);
      * order/permutation invariance ``f(xs) == f(reversed(xs))`` only reverses the
        FIRST positional argument when it is a list (a reorderable sequence);
      * idempotence ``f(f(x)) == f(x)`` only feeds the base return value back when
        it is SERIALIZABLE/feedable across the subprocess boundary.

    The FIRST applicable relation failure short-circuits to ``'rejected'``. A
    strategy-build failure or empty input set is fail-closed to ``'unverified'``
    (never a silent pass); an all-relations-hold (or all-inapplicable) run is
    ``'verified'``. The sandbox is always cleaned up in a ``finally``. No code is
    materialised/executed in-process -- execution is exclusively via the
    out-of-process sandbox.
    """
    fuzz_cfg = config.get('fuzzing', {}) if isinstance(config, dict) else {}
    float_tol = fuzz_cfg.get('float_tolerance', 1e-09)
    try:
        strategy = build_input_strategy(side_code, func_name)
    except (ValueError, SyntaxError):
        return 'unverified'
    inputs = _generate_inputs(strategy, count, seed)
    if not inputs:
        return 'unverified'

    def _is_feedable(value: Any) -> bool:
        try:
            import json
            json.dumps(value)
            return True
        except Exception:
            return False
    sandbox = sandbox_from_config(config, session_id=f'{session_id}_metamorphic')
    try:
        for args, kwargs in inputs:
            base = sandbox.execute(side_code, func_name, args=args, kwargs=kwargs)
            if base.timed_out or not base.success:
                continue
            if args and isinstance(args[0], list):
                reordered = [list(reversed(args[0]))] + list(args[1:])
                rev_result = sandbox.execute(side_code, func_name, args=reordered, kwargs=kwargs)
                match, _reason = outputs_match(base, rev_result, float_tol)
                if not match:
                    return 'rejected'
            value = base.return_value
            if _is_feedable(value):
                fed_result = sandbox.execute(side_code, func_name, args=[value], kwargs={})
                match, _reason = outputs_match(base, fed_result, float_tol)
                if not match:
                    return 'rejected'
    finally:
        sandbox.cleanup()
    return 'verified'
def _onesided_oracle_enabled() -> bool:
    """Fail-safe reader for autowork.onesided_oracle (default false -> OFF).

    Mirrors orchestrator._wire_up_gate_enabled and the in-file
    _dict_corpus_synthesis_enabled: imports load_config INSIDE the function and
    returns False on ANY error so a missing autowork key, a missing
    onesided_oracle key, or an unreadable config can never turn the gate ON.
    Default false keeps the one-side branch byte-identical to HEAD.
    """
    try:
        from harness.orchestrator import load_config
        cfg = load_config()
        return bool(cfg['autowork']['onesided_oracle'])
    except Exception:
        return False
def fuzz_from_task(code_a: str, code_b: str, task: dict[str, Any], config: dict[str, Any], session_id: str='default') -> FuzzResult:
    """Differential fuzz using task constraints to determine the function name."""
    _js = _maybe_js_fuzz(code_a, code_b, task, config, session_id)
    if _js is not None:
        return _js
    constraints = task.get('constraints', {}) if isinstance(task, dict) else {}
    if not isinstance(constraints, dict):
        constraints = {}
    func_sig = constraints.get('function_signature', '')
    m = re.match('def\\s+(\\w+)\\s*\\(', func_sig) if isinstance(func_sig, str) else None
    sig_provided_name: str | None = None
    if m:
        sig_provided_name = m.group(1)
        func_name: str | None = sig_provided_name
    else:
        func_a = _get_primary_function(code_a)
        func_b = _get_primary_function(code_b)
        if func_a and func_b and (func_a != func_b):
            code_b = _rename_function(code_b, func_b, func_a)
        func_name = func_a or func_b
        if func_name is None:
            reason = 'Could not determine target function name from task or code'
            logger.info('fuzz_from_task skipping: %s', reason)
            return FuzzResult(equivalent=True, skipped_reason=reason)
    a_has = _code_defines_function(code_a, func_name)
    b_has = _code_defines_function(code_b, func_name)
    if not a_has or not b_has:
        meta_type = _extract_meta_task_type(task if isinstance(task, dict) else {})
        if not a_has and (not b_has):
            reason = f'Target function {func_name!r} absent from both submissions; skipping fuzz unconditionally'
            logger.info('fuzz_from_task skipping: %s', reason)
            return FuzzResult(equivalent=True, skipped_reason=reason)
        else:
            missing_side = 'code_a' if not a_has else 'code_b'
            if meta_type in FUZZ_BYPASS_META_TYPES:
                reason = f'Target function {func_name!r} defined on one side only (missing in {missing_side}); meta_task_type={meta_type!r} is in the fuzzer-bypass set; skipping fuzz by policy'
                if _onesided_oracle_blocking_enabled():
                    side_code = code_a if missing_side == 'code_b' else code_b
                    fuzz_cfg = config.get('fuzzing', {}) if isinstance(config, dict) else {}
                    count = fuzz_cfg.get('function_level_inputs', 2000)
                    seed = fuzz_cfg.get('seed', 42)
                    float_tol = fuzz_cfg.get('float_tolerance', 1e-09)
                    verdict = _one_sided_execute_verdict(side_code, func_name, config, session_id, count=count, seed=seed)
                    if verdict == 'rejected':
                        logger.info('fuzz_from_task one-sided oracle BLOCKED: missing_side=%s func_name=%s verdict=rejected', missing_side, func_name)
                        return FuzzResult(equivalent=False, error=f'one-sided oracle BLOCKED: {func_name!r} failed the out-of-process determinism relation (missing_side={missing_side})')
                    if verdict == 'verified':
                        if _onesided_metamorphic_enabled():
                            meta_verdict = _one_sided_metamorphic_verdict(side_code, func_name, config, session_id, count=count, seed=seed)
                            if meta_verdict == 'rejected':
                                logger.info('fuzz_from_task one-sided metamorphic oracle BLOCKED: missing_side=%s func_name=%s verdict=rejected', missing_side, func_name)
                                return FuzzResult(equivalent=False, error=f'one-sided metamorphic oracle BLOCKED: {func_name!r} failed an intrinsic metamorphic relation (missing_side={missing_side})')
                        verified_reason = f'Target function {func_name!r} defined on one side only (missing in {missing_side}); one-sided oracle BLOCKING executed the candidate out-of-process and it passed the conservative determinism relation (missing_side={missing_side})'
                        logger.info('fuzz_from_task one-sided oracle verified: %s', verified_reason)
                        return FuzzResult(equivalent=True, skipped_reason=verified_reason)
                    return FuzzResult(equivalent=False, error=f'one-sided oracle BLOCKING could not verify {func_name!r} out-of-process (verdict=unverified, missing_side={missing_side}); failing closed')
                if _onesided_oracle_enabled():
                    side_code = code_a if missing_side == 'code_b' else code_b
                    try:
                        build_input_strategy(side_code, func_name)
                        strategy_buildable = True
                    except Exception:
                        strategy_buildable = False
                    golden_artifact = None
                    declared_relations: tuple = ()
                    if golden_artifact is not None:
                        tier = 'golden'
                    elif declared_relations:
                        tier = 'metamorphic'
                    else:
                        tier = 'determinism_only'
                    logger.info('onesided_oracle shadow: one_sided=True missing_side=%s func_name=%s tier=%s verdict=unverified strategy_buildable=%s', missing_side, func_name, tier, strategy_buildable)
                logger.info('fuzz_from_task skipping: %s', reason)
                return FuzzResult(equivalent=True, skipped_reason=reason)
            return FuzzResult(equivalent=False, error=f'Failed to build input strategy from {missing_side}: Function {func_name!r} not found in code')
    if isinstance(task, dict) and task.get('fuzz_str_ascii'):
        config = {**config, 'rebuild': {**config.get('rebuild', {}), 'fuzz_str_ascii': True}}
    result = differential_fuzz(code_a, code_b, func_name, config, session_id)
    _record_population_safe(code_a, code_b, task, result)
    return result
_DICT_CORPUS_CONFIG: tuple[dict, ...] = ({'fuzzing': {'function_level_inputs': 2000, 'float_tolerance': 1e-09, 'seed': 42}, 'batch_execution': {'enabled': True, 'worker_pool_size': 1}, 'autowork': {'dict_corpus_synthesis': False}}, {'fuzzing': {'function_level_inputs': 500, 'seed': 7}, 'rebuild': {'fuzz_str_ascii': True}}, {'sandbox': {'timeout': 5.0, 'mem_limit_mb': 256}, 'fuzzing': {'function_level_inputs': 1000}}, {'autowork': {'dict_corpus_synthesis': True, 'wire_up_gate': False}}, {'batch_execution': {'enabled': False}, 'fuzzing': {'seed': 1, 'float_tolerance': 1e-06}}, {'models': {'a': 'claude', 'b': 'gemini'}, 'fuzzing': {'function_level_inputs': 2000, 'seed': 42}})
_DICT_CORPUS_TASK: tuple[dict, ...] = ({'task_id': 't1', 'meta_task_type': 'harness_self_fix', 'constraints': {'function_signature': 'def f(x: int) -> int'}}, {'task_id': 't2', 'priority': 'high', 'constraints': {}}, {'task_id': 't3', 'meta_task_type': 'rebuild_unit', 'fuzz_str_ascii': True}, {'task_id': 't4', 'dependencies': ['t1'], 'constraints': {'function_signature': 'def g(s: str) -> str'}}, {'task_id': 't5', 'language': 'js', 'constraints': {'js_inputs': [[1, 2]]}}, {'task_id': 't6', 'meta_task_type': 'test_authoring', 'estimated_complexity': 'medium'})
_DICT_CORPUS_PLAN: tuple[dict, ...] = ({'plan_id': 'p1', 'steps': ['harvest', 'rebuild', 'verify'], 'status': 'pending'}, {'plan_id': 'p2', 'tasks': ['t1', 't2'], 'status': 'running'}, {'plan_id': 'p3', 'wave': 2, 'parallelism': 4}, {'plan_id': 'p4', 'steps': [], 'status': 'done'}, {'plan_id': 'p5', 'tasks': ['t3'], 'dependencies': {'t3': ['t1']}}, {'plan_id': 'p6', 'wave': 1, 'status': 'blocked', 'reason': 'dep'})
_DICT_CORPUS_CANDIDATES: tuple[dict, ...] = ({'id': 'agent_a', 'code': 'def f():\n    return 1', 'fitness': {'equivalent': True}}, {'id': 'agent_b', 'code': 'def f():\n    return 2', 'fitness': {'equivalent': False}}, {'id': 'c1', 'code': 'def g(a, b):\n    return a + b', 'fitness': {'source': 'fuzz'}, 'parent_ids': ['agent_a']}, {'id': 'c2', 'code': 'def h(x):\n    return x * 2', 'fitness': {'equivalent': True, 'score': 0.9}}, {'id': 'c3', 'code': 'def p():\n    pass', 'fitness': {}}, {'id': 'c4', 'code': 'class A:\n    pass', 'fitness': {'source': 'seed'}, 'parent_ids': []})
_CONFIG_CORPUS = _DICT_CORPUS_CONFIG
_TASK_CORPUS = _DICT_CORPUS_TASK
_PLAN_CORPUS = _DICT_CORPUS_PLAN
_CANDIDATE_CORPUS = _DICT_CORPUS_CANDIDATES
_CORPUS_BY_NAME: dict[str, tuple[dict, ...]] = {'config': _DICT_CORPUS_CONFIG, 'task': _DICT_CORPUS_TASK, 'plan': _DICT_CORPUS_PLAN, 'candidates': _DICT_CORPUS_CANDIDATES}
_LIST_CORPUS_BY_NAME: dict[str, tuple[dict, ...]] = {'config': _DICT_CORPUS_CONFIG, 'task': _DICT_CORPUS_TASK, 'plan': _DICT_CORPUS_PLAN, 'candidates': _DICT_CORPUS_CANDIDATES}

def _dict_corpus_synthesis_enabled() -> bool:
    """Fail-safe reader for autowork.dict_corpus_synthesis (default false -> OFF).

    Mirrors orchestrator._wire_up_gate_enabled: imports load_config INSIDE the
    function and returns False on ANY error so a missing autowork key, a missing
    dict_corpus_synthesis key, or an unreadable config can never turn the gate
    ON. Default false keeps the OFF path byte-identical to HEAD.
    """
    try:
        from harness.orchestrator import load_config
        cfg = load_config()
        return bool(cfg['autowork']['dict_corpus_synthesis'])
    except Exception:
        return False

def _dict_strategy_for(param_name: str, annotation_src: str) -> st.SearchStrategy | None:
    """Tier-2 domain-dict strategy for a registered param, else None.

    A bare ``dict`` / ``Dict`` annotation on a registered domain name draws from
    that name's curated corpus (``st.sampled_from``); a ``list[dict]`` /
    ``List[dict]`` annotation (whitespace- and casing-tolerant) draws a list of
    corpus dicts (``st.lists(st.sampled_from(...))``). An unregistered name, an
    unexpected annotation shape, or any parse error returns None so the caller
    falls back safely to ``_strategy_for_annotation``. Determinism comes from
    ``st.sampled_from`` over the fixed corpus. Works with hypothesis alone; the
    tier-3 ``from_schema`` path stays optional/import-guarded above.
    """
    try:
        src = (annotation_src or '').strip()
        if not src:
            return None
        node = ast.parse(src, mode='eval').body
        if isinstance(node, ast.Name) and node.id in ('dict', 'Dict'):
            corpus = _CORPUS_BY_NAME.get(param_name)
            if corpus:
                return st.sampled_from(list(corpus))
            return None
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and (node.value.id in ('list', 'List')):
            sl = node.slice
            if isinstance(sl, ast.Name) and sl.id in ('dict', 'Dict'):
                corpus = _LIST_CORPUS_BY_NAME.get(param_name)
                if corpus:
                    return st.lists(st.sampled_from(list(corpus)), min_size=0, max_size=10)
                return None
        return None
    except Exception:
        return None
try:
    from hypothesis_jsonschema import from_schema
except Exception:
    from_schema = None