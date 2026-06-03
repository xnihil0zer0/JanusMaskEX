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
from dataclasses import dataclass, field
from typing import Any
from hypothesis import given, seed as h_seed, settings, HealthCheck, Phase, Verbosity
from hypothesis import strategies as st
from concurrent.futures import ThreadPoolExecutor
from harness.sandbox import ExecutionResult, Sandbox, SandboxConfig, sandbox_from_config, BatchRunner
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

# ---------------------------------------------------------------------------
# Structured-input synthesis for the clean-room REBUILD oracle: ast.* nodes +
# pathlib.Path. The base strategy table only synthesizes primitives/containers;
# an ast.*/Path-typed param falls through to the garbage-int fallback, which
# FALSE-diverges a faithful body and forces an operator pin. For a clean-room
# rebuild we possess the original, so the merged==original fuzz is ground truth:
# synthesizing representative ast nodes / Paths from a curated corpus flips those
# units to oracle-USABLE so blind reconstruction is gated by ground truth with NO
# hand-written pin. The generated values round-trip through the sandbox JSON codec
# (ast -> source + category, re-parsed child-side; Path -> str) — see
# harness/sandbox.py SandboxEncoder/sandbox_decoder (all 3 copies).
_AST_STMT_CORPUS: dict[str, tuple[str, ...]] = {
    'FunctionDef': (
        'def f():\n    return 1',
        'def g(a, b=2):\n    return a + b',
        'def h(*args, **kw):\n    x = sum(args)\n    return x',
        'def p(n):\n    import random\n    return random.random() + n',
        'def q(path):\n    with open(path) as fh:\n        return fh.read()',
        'def t():\n    import time\n    return time.time()',
        'def deco(fn):\n    return fn',
        'def recurse(n):\n    if n <= 0:\n        return 0\n    return recurse(n - 1)',
    ),
    'AsyncFunctionDef': (
        'async def af():\n    return 1',
        'async def ag(x):\n    await x\n    return x',
    ),
    'ClassDef': (
        'class A:\n    pass',
        'class B(Base):\n    x = 1\n\n    def m(self):\n        return self.x',
        'class C:\n    def __init__(self, v):\n        self.v = v',
        'class D:\n    def __post_init__(self):\n        self.ready = True',
    ),
    'Import': ('import os', 'import os, sys'),
    'ImportFrom': ('from a.b import c', 'from . import x', 'from .mod import y, z'),
    'Assign': ('x = 1', 'a = b = []', 'GLOBAL.append(v)'),
}
_AST_MODULE_CORPUS: tuple[str, ...] = (
    'import os\nx = 1\n\ndef f():\n    return x',
    'from a import b\n\nclass C:\n    pass',
    'GLOBAL = []\n\ndef reg(v):\n    GLOBAL.append(v)',
)
_AST_EXPR_CORPUS: tuple[str, ...] = (
    '1 + 2',
    'foo(bar, baz=1)',
    'a.b.c',
    '[x for x in range(3)]',
    "{'k': v}",
    'lambda x: x + 1',
    'a if b else c',
)
_AST_BROAD_CORPUS: tuple[str, ...] = (
    _AST_STMT_CORPUS['FunctionDef'] + _AST_STMT_CORPUS['ClassDef'] + _AST_STMT_CORPUS['Assign']
    + _AST_STMT_CORPUS['Import'] + _AST_STMT_CORPUS['ImportFrom']
    + ('for i in range(3):\n    pass', 'if a:\n    b = 1', 'return x', 'raise ValueError("x")')
)


_PATH_CORPUS: tuple[str, ...] = (
    'a.py', 'b/c.txt', 'x', 'dir/sub/f.json', '__init__.py',
    'test_x.py', '.hidden', 'm.pyc', 'pkg/mod.py', 'tests/test_y.py',
)


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
            # REBUILD-SCOPED restricted alphabet. Opt-in via str_ascii (threaded
            # ONLY through the rebuild oracle + per-unit rebuild task, never the
            # main differential pipeline). A WORD-transform lib (inflection's
            # pluralize/titleize/tableize) is only behaviorally well-defined on its
            # MEANINGFUL domain -- alphabetic words. On adversarial digit/punct/
            # mixed-case/empty garbage several spec-equivalent implementations
            # legitimately differ (titleize word-boundary capitalization of
            # '8kk974'; pluralize empty-string handling), so a faithful blind
            # reconstruction false-diverges there. Restricting the rebuild oracle's
            # str fuzz to ASCII letters + space (non-empty) fuzzes the functions'
            # real domain and closes that false-divergence frontier (W1/C9.14).
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

    def _param_strategies(func: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, st.SearchStrategy]:
        params: dict[str, st.SearchStrategy] = {}
        for arg in func.args.args[1:]:
            if arg.annotation is not None:
                params[arg.arg] = _ast_node_to_strategy(arg.annotation)
            else:
                params[arg.arg] = _strategy_for_annotation('int')
        return params
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
    for name, annotation in sig.items():
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
        # Fail-CLOSED (M4): zero inputs fuzzed means input generation failed or
        # timed out (see _generate_inputs swallowing exceptions/timeouts). An
        # empty failure list must NOT surface as equivalent=True (INV-5).
        logger.error('Fuzzing produced ZERO inputs for %r; failing closed (no agreement)', func_name)
        return FuzzResult(equivalent=False, total_inputs=0, matching_inputs=0, failures=failures, error='fuzz produced zero inputs (generation failed/timed out); failing closed')
    equivalent = len(failures) == 0
    logger.info('Fuzzing complete: %d/%d matching, %d failures, equivalent=%s', matching, total, len(failures), equivalent)
    return FuzzResult(equivalent=equivalent, total_inputs=total, matching_inputs=matching, failures=failures)

def differential_fuzz(code_a: str, code_b: str, func_name: str, config: dict[str, Any], session_id: str='default') -> FuzzResult:
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
        # Fail-CLOSED (M4): zero inputs generated must never surface as
        # equivalent=True (INV-5) — mirrors the sequential path guard.
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

def fuzz_from_task(code_a: str, code_b: str, task: dict[str, Any], config: dict[str, Any], session_id: str='default') -> FuzzResult:
    """Differential fuzz using task constraints to determine the function name."""
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
            if meta_type in FUZZ_BYPASS_META_TYPES:
                reason = f'Target function {func_name!r} absent from both submissions and meta_task_type={meta_type!r} is in the fuzzer-bypass set; skipping fuzz by policy'
                logger.info('fuzz_from_task skipping: %s', reason)
                return FuzzResult(equivalent=True, skipped_reason=reason)
        else:
            missing_side = 'code_a' if not a_has else 'code_b'
            if meta_type in FUZZ_BYPASS_META_TYPES:
                reason = f'Target function {func_name!r} defined on one side only (missing in {missing_side}); meta_task_type={meta_type!r} is in the fuzzer-bypass set; skipping fuzz by policy'
                logger.info('fuzz_from_task skipping: %s', reason)
                return FuzzResult(equivalent=True, skipped_reason=reason)
            return FuzzResult(equivalent=False, error=f'Failed to build input strategy from {missing_side}: Function {func_name!r} not found in code')
    # REBUILD-SCOPED str alphabet: a per-unit rebuild task may opt the Claude==Gemini
    # gate into the restricted str alphabet (W1). Only rebuild units set this flag in
    # their spec; main-pipeline tasks never do, so the global pipeline is unchanged.
    if isinstance(task, dict) and task.get('fuzz_str_ascii'):
        config = {**config, 'rebuild': {**config.get('rebuild', {}), 'fuzz_str_ascii': True}}
    return differential_fuzz(code_a, code_b, func_name, config, session_id)