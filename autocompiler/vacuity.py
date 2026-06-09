"""AST-level fitness-integrity gates for autocompiler candidate code.

Three pure, fail-closed gates that detect "gamed" candidate code by
inspecting its abstract syntax tree:

* :func:`check_vacuity_stub` -- rejects modules in which every function /
  method body is a stub (``pass`` / ``...`` / ``raise NotImplementedError`` /
  a lone constant or docstring).
* :func:`check_complexity_floor` -- rejects nodes whose body has fewer than a
  configured minimum number of statements (docstrings not counted).
* :func:`check_no_exception_swallow` -- rejects ``except`` handlers whose body
  is only ``pass`` or ``...``.

Every gate returns a :class:`GateResult` (attributes ``ok``, ``reason``,
``fix_hint``) and fails closed (``ok=False``) on syntax / AST errors without
ever raising. Pure / stdlib-only.
"""
from __future__ import annotations
import ast
from typing import Dict, List, Sequence
try:
    from overseer.gates import GateResult
except Exception:
    from dataclasses import dataclass

    @dataclass
    class GateResult:
        ok: bool
        reason: str = ''
        fix_hint: str = ''
try:
    from harness.embedded_test_runner import should_run_embedded_tests
except Exception:

    def should_run_embedded_tests(src: str) -> bool:
        return False

def _result(ok: bool, reason: str='', fix_hint: str='') -> GateResult:
    """Construct a GateResult robustly across possible constructor shapes."""
    try:
        return GateResult(ok=ok, reason=reason, fix_hint=fix_hint)
    except TypeError:
        pass
    try:
        return GateResult(ok=ok, reason=reason)
    except TypeError:
        pass
    res = GateResult(ok)
    try:
        res.reason = reason
        res.fix_hint = fix_hint
    except Exception:
        pass
    return res

def _parse(src: str) -> ast.AST:
    """Parse ``src`` to an AST, raising on failure (callers fail-closed)."""
    return ast.parse(src)

def _is_constant_expr(stmt: ast.stmt) -> bool:
    """True for a lone constant statement (docstring, number, ellipsis, ...)."""
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)

def _is_ellipsis_expr(stmt: ast.stmt) -> bool:
    """True for a lone ``...`` expression statement."""
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and (stmt.value.value is Ellipsis)

def _is_not_implemented_raise(stmt: ast.stmt) -> bool:
    """True for ``raise NotImplementedError`` (bare class or called)."""
    if not isinstance(stmt, ast.Raise):
        return False
    exc = stmt.exc
    if exc is None:
        return False
    if isinstance(exc, ast.Call):
        exc = exc.func
    if isinstance(exc, ast.Name):
        return exc.id in ('NotImplementedError', 'NotImplemented')
    if isinstance(exc, ast.Attribute):
        return exc.attr in ('NotImplementedError', 'NotImplemented')
    return False

def _is_stub_function(node: ast.AST) -> bool:
    """True when a function/method body does no real work."""
    body: Sequence[ast.stmt] = getattr(node, 'body', [])
    if not body:
        return True
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        if _is_constant_expr(stmt):
            continue
        if _is_not_implemented_raise(stmt):
            continue
        return False
    return True

def _strip_docstring(body: Sequence[ast.stmt]) -> List[ast.stmt]:
    """Return body statements with a leading string docstring removed."""
    stmts = list(body)
    if stmts and isinstance(stmts[0], ast.Expr) and isinstance(stmts[0].value, ast.Constant) and isinstance(stmts[0].value.value, str):
        return stmts[1:]
    return stmts

def check_vacuity_stub(src: str) -> GateResult:
    """Reject modules whose every function/method body is a stub.

    A module with no functions but real top-level statements is accepted.
    Files containing legitimate embedded test scaffolding bypass the check.
    """
    try:
        if should_run_embedded_tests(src):
            return _result(True, 'embedded test scaffolding present')
    except Exception:
        pass
    try:
        tree = _parse(src)
    except SyntaxError as exc:
        return _result(False, f'unparseable source: {exc}', 'fix the syntax error so the candidate can be analysed')
    except Exception as exc:
        return _result(False, f'parse error: {exc}', 'ensure source is valid Python')
    functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if not functions:
        if getattr(tree, 'body', None):
            return _result(True, 'no functions defined but top-level work present')
        return _result(False, 'empty module: no functions and no top-level statements', 'add real implementation')
    if all((_is_stub_function(fn) for fn in functions)):
        names = ', '.join((getattr(fn, 'name', '?') for fn in functions))
        return _result(False, f'every function is a stub ({names})', 'implement at least one function with real behaviour')
    return _result(True, 'at least one function performs real work')

def check_complexity_floor(src: str, min_by_type: Dict[str, int]) -> GateResult:
    """Reject any node in ``min_by_type`` below its body-statement floor.

    ``min_by_type`` maps an AST node type name (e.g. ``'FunctionDef'``) to the
    minimum number of body statements such a node must contain. A leading
    string docstring is not counted toward the floor.
    """
    try:
        tree = _parse(src)
    except SyntaxError as exc:
        return _result(False, f'unparseable source: {exc}', 'fix the syntax error so the candidate can be analysed')
    except Exception as exc:
        return _result(False, f'parse error: {exc}', 'ensure source is valid Python')
    if not min_by_type:
        return _result(True, 'no complexity floor configured')
    for node in ast.walk(tree):
        type_name = type(node).__name__
        floor = min_by_type.get(type_name)
        if floor is None:
            continue
        body = getattr(node, 'body', None)
        if body is None:
            continue
        stmts = _strip_docstring(body)
        if len(stmts) < floor:
            label = getattr(node, 'name', type_name)
            return _result(False, f"{type_name} '{label}' has {len(stmts)} statement(s); floor is {floor}", f'add real logic so each {type_name} has >= {floor} statements')
    return _result(True, 'all node types meet their complexity floor')

def _is_swallow_handler(body: Sequence[ast.stmt]) -> bool:
    """True when an except handler body is only ``pass`` / ``...``."""
    if not body:
        return True
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        if _is_ellipsis_expr(stmt):
            continue
        return False
    return True

def check_no_exception_swallow(src: str) -> GateResult:
    """Reject ``except`` handlers whose body is only ``pass`` or ``...``."""
    try:
        tree = _parse(src)
    except SyntaxError as exc:
        return _result(False, f'unparseable source: {exc}', 'fix the syntax error so the candidate can be analysed')
    except Exception as exc:
        return _result(False, f'parse error: {exc}', 'ensure source is valid Python')
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and _is_swallow_handler(node.body):
            lineno = getattr(node, 'lineno', '?')
            return _result(False, f'except handler at line {lineno} swallows the exception', 're-raise, log, or otherwise handle the caught exception')
    return _result(True, 'no exception swallowing handlers found')