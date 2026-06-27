"""Pure, stdlib-only (``ast``) symbolic policy verifier for Python source.

This module is fully deterministic: no network, LLM, subprocess, clock, or
randomness. It parses code with the standard-library ``ast`` module and reports
policy :class:`Violation` objects (syntax / bare-except / ``os.system`` /
``subprocess.run`` without ``check`` / undocumented ``2>/dev/null``).

It has no dependency on any sibling Epic-4 leaf (ast_constraint, backtrack,
z3_bridge): any constraint-shaped inputs would arrive as ordinary plain
arguments and be interpreted locally. Only the standard library is imported.
"""
from __future__ import annotations
import ast
from dataclasses import dataclass, field
from typing import List
SEVERITY_ERROR = 'ERROR'
SEVERITY_WARNING = 'WARNING'
_DEVNULL_TOKEN = '2>/dev/null'

@dataclass
class Violation:
    """A single policy finding reported by :class:`ASTVerifier`."""
    rule: str
    line: int
    message: str
    severity: str

@dataclass
class ASTResult:
    """Outcome of verifying a unit of source.

    ``valid`` is ``True`` when no ERROR-severity violation is present; WARNING
    findings do not invalidate the result.
    """
    valid: bool
    violations: List[Violation] = field(default_factory=list)

    def has_errors(self) -> bool:
        return any((v.severity == SEVERITY_ERROR for v in self.violations))

    def has_warnings(self) -> bool:
        return any((v.severity == SEVERITY_WARNING for v in self.violations))

    def summary(self) -> str:
        if not self.violations:
            return 'OK (no violations)'
        n_err = sum((1 for v in self.violations if v.severity == SEVERITY_ERROR))
        n_warn = sum((1 for v in self.violations if v.severity == SEVERITY_WARNING))
        return f'{n_err} error(s), {n_warn} warning(s)'

class PocMarkerStubChecker:
    """Narrowly-scoped check for PoC "success-marker" stub functions.

    A function that simply ``return``s a hardcoded success-marker STRING
    constant (e.g. ``"VULNERABLE"`` / ``"CONFIRMED"`` / ``"SUCCESS"``) reads as
    a proof-of-concept stub rather than a real implementation. The scope is
    deliberately tight:

    * Only an ``ast.Return`` whose value is a string ``ast.Constant`` equal to
      one of the success markers is treated as a hit.
    * Returns of ``True`` / ``False`` / ``None``, numeric constants, the empty
      string, or any non-marker string are ignored.
    * A marker reaching the return via a variable (an ``ast.Name``) rather than
      a literal is ignored.
    * A marker string used anywhere other than as a return value is ignored.

    The checker carries no global "constant return" ban -- it is success-marker
    strings only.
    """
    SUCCESS_MARKERS = frozenset({'VULNERABLE', 'CONFIRMED', 'SUCCESS'})
    rule = 'poc_success_marker'

    def marker_for_return(self, node):
        """Return the marker string if ``node`` is a marker-returning stub, else None."""
        if not isinstance(node, ast.Return):
            return None
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            if value.value in self.SUCCESS_MARKERS:
                return value.value
        return None
class ASTVerifier:
    """Walks a parsed ``ast`` tree and evaluates a fixed set of policy rules."""

    def __init__(self):
        self._poc_marker_checker = PocMarkerStubChecker()

    def verify(self, source: str) -> ASTResult:
        """Parse ``source`` and return an :class:`ASTResult` of findings."""
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            line = exc.lineno if exc.lineno and exc.lineno >= 1 else 1
            detail = exc.msg if exc.msg else str(exc)
            return ASTResult(valid=False, violations=[Violation(rule='syntax', line=line, message=f'SyntaxError: {detail}', severity=SEVERITY_ERROR)])
        source_lines = source.splitlines()
        handles_returncode = any((isinstance(node, ast.Attribute) and node.attr == 'returncode' for node in ast.walk(tree)))
        violations: List[Violation] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                violations.append(Violation(rule='bare_except', line=node.lineno, message='Bare except: catches everything and hides errors', severity=SEVERITY_ERROR))
            elif isinstance(node, ast.Call):
                self._check_call(node, violations, handles_returncode)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                self._check_string(node, source_lines, violations)
            elif isinstance(node, ast.Return):
                self._check_poc_marker(node, violations)
        valid = not any((v.severity == SEVERITY_ERROR for v in violations))
        return ASTResult(valid=valid, violations=violations)

    def verify_file(self, path: str) -> ASTResult:
        """Read ``path`` and delegate to :meth:`verify`."""
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                source = fh.read()
        except OSError as exc:
            return ASTResult(valid=False, violations=[Violation(rule='file_read', line=0, message=f'Cannot read file {path}: {exc}', severity=SEVERITY_ERROR)])
        return self.verify(source)

    def _check_poc_marker(self, node: ast.AST, violations: List[Violation]) -> None:
        marker = self._poc_marker_checker.marker_for_return(node)
        if marker is not None:
            violations.append(Violation(rule='poc_success_marker', line=node.lineno, message=f'function returns hardcoded success marker {marker!r} (suspected PoC stub)', severity=SEVERITY_WARNING))

    def _check_call(self, node: ast.Call, violations: List[Violation], handles_returncode: bool) -> None:
        func = node.func
        if not isinstance(func, ast.Attribute):
            return
        value = func.value
        base = value.id if isinstance(value, ast.Name) else None
        if base == 'os' and func.attr == 'system':
            violations.append(Violation(rule='os_system', line=node.lineno, message='os.system() call: use subprocess with check instead', severity=SEVERITY_ERROR))
        elif base == 'subprocess' and func.attr == 'run':
            has_check = any((kw.arg == 'check' and self._is_truthy(kw.value) for kw in node.keywords))
            if not has_check and (not handles_returncode):
                violations.append(Violation(rule='subprocess_no_check', line=node.lineno, message='subprocess.run() without check=True or returncode handling', severity=SEVERITY_ERROR))

    def _check_string(self, node: ast.Constant, source_lines: List[str], violations: List[Violation]) -> None:
        if _DEVNULL_TOKEN not in node.value:
            return
        if self._line_has_comment(node, source_lines):
            return
        violations.append(Violation(rule='devnull_no_comment', line=node.lineno, message='Redirection to /dev/null without an explanatory comment', severity=SEVERITY_WARNING))

    @staticmethod
    def _is_truthy(node: ast.AST) -> bool:
        return isinstance(node, ast.Constant) and bool(node.value)

    @staticmethod
    def _line_has_comment(node: ast.Constant, source_lines: List[str]) -> bool:
        start = node.lineno
        end = getattr(node, 'end_lineno', None) or start
        for lineno in range(start, end + 1):
            idx = lineno - 1
            if 0 <= idx < len(source_lines) and '#' in source_lines[idx]:
                return True
        return False
