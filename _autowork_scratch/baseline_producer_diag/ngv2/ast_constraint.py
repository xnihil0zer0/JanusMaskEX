"""Pure stdlib-``ast`` policy constraint module for NobleGreedv2.

This module scans Python source strings for unsafe or sloppy patterns using
only the standard library ``ast`` module. It reports findings as deterministic
violation dicts. It performs no I/O beyond reading files in :func:`check_file`,
uses no clock, randomness, network, or external tools, and depends on no
third-party packages.

Detected rules
--------------
``syntax_error``        (error)   -- source failed to parse.
``bare_except_pass``    (error)   -- ``except:`` body that only swallows.
``except_exception_pass`` (error) -- ``except Exception``/``BaseException``
                                      body that only swallows.
``os_system_call``      (warning) -- a call to ``os.system(...)``.
``subprocess_no_check``  (warning) -- ``subprocess.run(...)`` lacking both
                                      ``check`` and ``capture_output``.
``dev_null_stderr``     (warning) -- a string literal containing
                                      ``2>/dev/null``.
``file_not_found``      (error)   -- :func:`check_file` target is missing.
"""
from __future__ import annotations
import ast
from pathlib import Path
from typing import Union
VIOLATION_FIELDS = ('rule', 'line', 'description', 'severity')
MAX_CODE_CHARS = 50000
_SEVERITY_ERROR = 'error'
_SEVERITY_WARNING = 'warning'
_DEV_NULL_STDERR = '2>/dev/null'
_SWALLOW_EXCEPTIONS = frozenset({'Exception', 'BaseException'})

def _make_violation(rule: str, line: int, description: str, severity: str) -> dict:
    """Build a violation dict with the frozen :data:`VIOLATION_FIELDS` keys."""
    return {'rule': rule, 'line': int(line), 'description': description, 'severity': severity}

def _is_swallow_body(body: list) -> bool:
    """True when *body* contains only ``pass`` statements and/or docstrings."""
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
            continue
        return False
    return True

class _RuleVisitor(ast.NodeVisitor):
    """Walk a parsed AST and accumulate policy violations."""

    def __init__(self) -> None:
        self.violations: list[dict] = []

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if _is_swallow_body(node.body):
            if node.type is None:
                self.violations.append(_make_violation('bare_except_pass', node.lineno, "Bare 'except:' that silently swallows the exception.", _SEVERITY_ERROR))
            elif isinstance(node.type, ast.Name) and node.type.id in _SWALLOW_EXCEPTIONS:
                self.violations.append(_make_violation('except_exception_pass', node.lineno, "'except %s' that silently swallows the exception." % node.type.id, _SEVERITY_ERROR))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            module = func.value.id
            attr = func.attr
            if module == 'os' and attr == 'system':
                self.violations.append(_make_violation('os_system_call', node.lineno, 'Use of os.system(); prefer subprocess with explicit args.', _SEVERITY_WARNING))
            elif module == 'subprocess' and attr == 'run':
                kwargs = {kw.arg for kw in node.keywords if kw.arg is not None}
                if 'check' not in kwargs and 'capture_output' not in kwargs:
                    self.violations.append(_make_violation('subprocess_no_check', node.lineno, 'subprocess.run() without check= or capture_output=.', _SEVERITY_WARNING))
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and _DEV_NULL_STDERR in node.value:
            self.violations.append(_make_violation('dev_null_stderr', node.lineno, "String discards stderr via '2>/dev/null'.", _SEVERITY_WARNING))
        self.generic_visit(node)

def check_code_string(code: str) -> list[dict]:
    """Scan *code* and return a list of violation dicts.

    Returns an empty list for non-strings, empty source, or source longer than
    :data:`MAX_CODE_CHARS`. On a parse failure, returns exactly one
    ``syntax_error`` violation.
    """
    if not isinstance(code, str):
        return []
    if not code or len(code) > MAX_CODE_CHARS:
        return []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        line = exc.lineno if isinstance(exc.lineno, int) else 0
        message = exc.msg or 'syntax error'
        return [_make_violation('syntax_error', line, 'Failed to parse source: %s' % message, _SEVERITY_ERROR)]
    visitor = _RuleVisitor()
    visitor.visit(tree)
    return visitor.violations

def check_file(file_path: Union[Path, str]) -> list[dict]:
    """Read *file_path* as UTF-8 and delegate to :func:`check_code_string`.

    Returns a single ``file_not_found`` violation if the path does not exist.
    """
    path = Path(file_path)
    if not path.is_file():
        return [_make_violation('file_not_found', 0, 'File not found: %s' % path, _SEVERITY_ERROR)]
    text = path.read_text(encoding='utf-8')
    return check_code_string(text)

def format_violations(violations: list[dict], verbose: bool=False) -> str:
    """Render *violations* into a human-readable summary string."""
    if not violations:
        return 'No violations found.'
    lines: list[str] = []
    for v in violations:
        severity = str(v['severity']).upper()
        line = v['line']
        rule = v['rule']
        description = v['description']
        lines.append('[%s] line %s: %s - %s' % (severity, line, rule, description))
    if verbose:
        header = 'Found %d violation(s):' % len(violations)
        lines.insert(0, header)
    return '\n'.join(lines)

class ASTConstraint:
    """Stateless object-oriented facade over the module-level functions."""

    def check(self, code: str) -> list[dict]:
        return check_code_string(code)

    def check_file(self, path: Union[Path, str]) -> list[dict]:
        return check_file(path)

    def is_clean(self, code: str) -> bool:
        return not check_code_string(code)

    def has_error_violations(self, code: str) -> bool:
        return any((v['severity'] == _SEVERITY_ERROR for v in check_code_string(code)))
__all__ = ['check_code_string', 'check_file', 'format_violations', 'ASTConstraint', 'VIOLATION_FIELDS', 'MAX_CODE_CHARS']