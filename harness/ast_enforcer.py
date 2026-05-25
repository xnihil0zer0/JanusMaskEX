"""AST enforcer for JanusMask: validates and normalizes Python code submissions.

Validation checks code against policy rules (syntax, determinism, safety).
Normalization canonicalizes code to AST form for structural comparison between
agent outputs.
"""
from __future__ import annotations
import ast
import logging
import re
from dataclasses import dataclass
logger = logging.getLogger(__name__)

@dataclass
class Violation:
    rule: str
    severity: str
    line: int
    message: str
_NONDETERMINISTIC_MODULES = frozenset({'random', 'uuid'})
_NONDETERMINISTIC_CALLS = frozenset({('time', 'time'), ('datetime', 'now'), ('os', 'urandom')})
_SIDE_EFFECT_NAMES = frozenset({'print', 'open'})
_SIDE_EFFECT_ATTRS = frozenset({('sys', 'stdout', 'write')})

def _get_nondeterministic_modules():
    mod = sys.modules.get('harness.ast_enforcer')
    if mod is not None and hasattr(mod, '_NONDETERMINISTIC_MODULES'):
        return getattr(mod, '_NONDETERMINISTIC_MODULES')
    return globals().get('_NONDETERMINISTIC_MODULES', frozenset({'random', 'uuid'}))

def _get_nondeterministic_calls():
    mod = sys.modules.get('harness.ast_enforcer')
    if mod is not None and hasattr(mod, '_NONDETERMINISTIC_CALLS'):
        return getattr(mod, '_NONDETERMINISTIC_CALLS')
    return globals().get('_NONDETERMINISTIC_CALLS', frozenset({('time', 'time'), ('datetime', 'now'), ('os', 'urandom')}))

def _get_side_effect_names():
    mod = sys.modules.get('harness.ast_enforcer')
    if mod is not None and hasattr(mod, '_SIDE_EFFECT_NAMES'):
        return getattr(mod, '_SIDE_EFFECT_NAMES')
    return globals().get('_SIDE_EFFECT_NAMES', frozenset({'print', 'open'}))

def _get_side_effect_attrs():
    mod = sys.modules.get('harness.ast_enforcer')
    if mod is not None and hasattr(mod, '_SIDE_EFFECT_ATTRS'):
        return getattr(mod, '_SIDE_EFFECT_ATTRS')
    return globals().get('_SIDE_EFFECT_ATTRS', frozenset({('sys', 'stdout', 'write')}))

def _is_credential_name(name: str) -> bool:
    name_lower = name.lower()
    keywords = {'password', 'secret', 'key', 'token', 'credential', 'passwd'}
    return any((kw in name_lower for kw in keywords))

def _is_string_literal(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    if hasattr(ast, 'Str') and isinstance(node, ast.Str):
        return True
    return False

def _is_silent_body(body: list[ast.stmt]) -> bool:
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
            continue
        if hasattr(ast, 'Str') and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Str):
            continue
        return False
    return True

def _get_attribute_path(node_expr) -> tuple[str, ...] | None:
    parts = []
    curr = node_expr
    while isinstance(curr, ast.Attribute):
        parts.append(curr.attr)
        curr = curr.value
    if isinstance(curr, ast.Name):
        parts.append(curr.id)
        return tuple(reversed(parts))
    return None

class _ValidationVisitor(ast.NodeVisitor):
    """Walk the AST and collect Violation instances."""

    def __init__(self, *, allow_nondeterminism: bool=False) -> None:
        self.violations: list[Violation] = []
        self.allow_nondeterminism = allow_nondeterminism
        self._has_funcdef = False
        self._in_except_handler = False

    def _add(self, rule: str, severity: str, line: int, message: str) -> None:
        self.violations.append(Violation(rule, severity, line, message))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._has_funcdef = True
        self._check_recursion(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._has_funcdef = True
        self._check_recursion(node)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        if not self.allow_nondeterminism:
            nondet_mods = _get_nondeterministic_modules()
            for alias in node.names:
                root_mod = alias.name.split('.')[0]
                if root_mod in nondet_mods:
                    self._add(rule='nondeterminism', severity='error', line=node.lineno, message=f'Nondeterministic module import: {alias.name}')
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if not self.allow_nondeterminism and node.module:
            nondet_mods = _get_nondeterministic_modules()
            root_mod = node.module.split('.')[0]
            if root_mod in nondet_mods:
                self._add(rule='nondeterminism', severity='error', line=node.lineno, message=f'Nondeterministic module import: {node.module}')
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        self._check_dangerous_calls(node)
        self._check_nondeterministic_call(node)
        self._check_os_system(node)
        self._check_subprocess_check(node)
        self._check_side_effects(node)
        self.generic_visit(node)

    def _check_dangerous_calls(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in {'eval', 'exec', '__import__'}:
            self._add(rule='security', severity='error', line=node.lineno, message=f'Banned dangerous function call: {node.func.id}')

    def visit_Assign(self, node: ast.Assign) -> None:
        if _is_string_literal(node.value):
            for target in node.targets:
                names_to_check = []
                if isinstance(target, ast.Name):
                    names_to_check.append(target.id)
                elif isinstance(target, ast.Attribute):
                    names_to_check.append(target.attr)
                if any((_is_credential_name(name) for name in names_to_check)):
                    self._add(rule='security', severity='error', line=node.lineno, message='Hardcoded credentials detected in assignment')
                    break
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value and _is_string_literal(node.value):
            names_to_check = []
            if isinstance(node.target, ast.Name):
                names_to_check.append(node.target.id)
            elif isinstance(node.target, ast.Attribute):
                names_to_check.append(node.target.attr)
            if any((_is_credential_name(name) for name in names_to_check)):
                self._add(rule='security', severity='error', line=node.lineno, message='Hardcoded credentials detected in annotated assignment')
        self.generic_visit(node)

    def _check_nondeterministic_call(self, node: ast.Call) -> None:
        """Rule 3: detect time.time(), datetime.now(), os.urandom()."""
        if not self.allow_nondeterminism:
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                call_tuple = (node.func.value.id, node.func.attr)
                if call_tuple in _get_nondeterministic_calls():
                    self._add(rule='nondeterminism', severity='error', line=node.lineno, message=f'Nondeterministic function call: {node.func.value.id}.{node.func.attr}')

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is None:
            if _is_silent_body(node.body):
                self._add(rule='bare_except', severity='error', line=node.lineno, message='Silent bare except handler detected')
        old_in_except = getattr(self, '_in_except_handler', False)
        self._in_except_handler = True
        self.generic_visit(node)
        self._in_except_handler = old_in_except

    def _check_os_system(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and (node.func.value.id == 'os') and (node.func.attr == 'system'):
            self._add(rule='os_system', severity='error', line=node.lineno, message='os.system() is banned; use subprocess with check=True or similar secure alternatives')

    def _check_subprocess_check(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and (node.func.value.id == 'subprocess') and (node.func.attr in {'run', 'call'}):
            has_check = any((kw.arg == 'check' for kw in node.keywords))
            if not has_check:
                self._add(rule='subprocess_no_check', severity='error', line=node.lineno, message=f'subprocess.{node.func.attr}() called without check parameter')

    def _check_side_effects(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            if node.func.id in _get_side_effect_names():
                if node.func.id == 'print' and getattr(self, '_in_except_handler', False):
                    return
                self._add(rule='side_effect', severity='error', line=node.lineno, message=f'Banned side-effect function call: {node.func.id}')
                return
        path = _get_attribute_path(node.func)
        if path is not None:
            if path in _get_side_effect_attrs():
                path_str = '.'.join(path)
                self._add(rule='side_effect', severity='error', line=node.lineno, message=f'Banned side-effect attribute call: {path_str}')

    def _check_recursion(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Warn if a function contains a recursive call without a visible
        base case.  Heuristic: walk top-level statements in body order.  If a
        recursive call is found before any ``if`` or ``return`` statement, flag
        it as potentially unbounded."""
        func_name = node.name
        for stmt in node.body:
            if isinstance(stmt, (ast.If, ast.Return)):
                break
            rec_calls = []
            for n in ast.walk(stmt):
                if isinstance(n, ast.Call):
                    if isinstance(n.func, ast.Name) and n.func.id == func_name:
                        rec_calls.append(n)
            if rec_calls:
                has_guard = False
                for n in ast.walk(stmt):
                    if isinstance(n, (ast.If, ast.IfExp, ast.Return, ast.For, ast.While, ast.Try, ast.With, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        has_guard = True
                        break
                if not has_guard:
                    self._add(rule='unbounded_recursion', severity='warning', line=stmt.lineno, message=f'Potentially unbounded recursion in {func_name}')
                    break

def validate_code(code: str, *, allow_nondeterminism: bool=False, declared_signature: str | None=None) -> list[Violation]:
    """Validate *code* against all rules. Return list of violations.

    Parameters
    ----------
    code:
        Source under inspection.
    allow_nondeterminism:
        Suppress the ``nondeterminism`` rule (existing semantics).
    declared_signature:
        W76b wire-in. When provided (a brief's ``function_signature`` string,
        e.g. ``"def f(x) -> dict: ..."``), the return-type contract is checked
        against the impl's ``FunctionDef.returns`` and any mismatch is appended
        to the returned violations as a ``return_type_mismatch`` rule. ``None``
        (default) preserves all pre-W76b call-site semantics.
    """
    raise NotImplementedError

def _check_declared_return_type(code: str, declared_signature: str) -> list[Violation]:
    """Reconcile the brief's declared signature against the impl.

    Extracts the declared return annotation and the function name from
    *declared_signature*, then defers to :func:`validate_return_type`.

    Returns ``[]`` when the brief signature does not parse to a usable
    ``FunctionDef`` (logged at WARNING). This is the "no-op skip" path
    documented in W76b: a malformed brief should not crash the validator nor
    spuriously reject otherwise-valid impls.
    """
    raise NotImplementedError

def _extract_func_name_from_signature(signature_src: str) -> str | None:
    """Return the function name declared in a brief signature, or None.

    Mirrors the parsing strategy of
    :func:`harness.diff_fuzzer.extract_return_annotation` -- accepts both
    full-form (``def foo(...) -> T: ...``) and header-only (``def foo(...)``)
    inputs, with sync and async variants.
    """
    raise NotImplementedError
_TYPING_ALIAS_EQUIVALENTS: dict[str, str] = {'Dict': 'dict', 'List': 'list', 'Tuple': 'tuple', 'Set': 'set', 'FrozenSet': 'frozenset', 'Type': 'type'}

class _AnnotationNormalizer(ast.NodeTransformer):
    """Strip surface-level typing noise so structurally-equal annotations compare equal.

    Rules:
      - ``typing.Dict`` / bare ``Dict`` → ``dict`` (and friends).
      - ``typing.Dict[K, V]`` / ``Dict[K, V]`` / ``dict[K, V]`` → ``dict``. The
        subscript is stripped so that ``-> dict`` in a brief compares equal to
        ``-> Dict[str, Any]`` in an implementation — the common "declared loose,
        implemented tight" brief idiom. Subscript parameters on *non*-collection
        generics (e.g. ``List[int]`` vs ``List[str]``) are preserved because
        they share the same head (``list``) and only the slice varies.
      - ``typing.Optional[X]`` → ``Union[X, None]`` so ``Optional[int]`` and
        ``Union[int, None]`` collapse to the same dump.
      - ``ctx`` fields on Name/Attribute/Subscript are always ``Load()`` in an
        annotation context, but ast.dump with ``include_attributes=False`` already
        omits them — no manual stripping needed beyond that flag.
    """

    def _bare_alias(self, name: str) -> str:
        raise NotImplementedError

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        raise NotImplementedError

    def visit_Name(self, node: ast.Name) -> ast.AST:
        raise NotImplementedError

    def visit_Subscript(self, node: ast.Subscript) -> ast.AST:
        raise NotImplementedError

def _resolve_string_annotation(node: ast.expr) -> ast.expr | None:
    """Unwrap ``Constant(value=<str>)`` PEP-563 forward references."""
    raise NotImplementedError

def _normalize_annotation(node: ast.expr) -> ast.expr | None:
    """Apply string-unwrap + typing-alias normalisation. Returns None on failure."""
    raise NotImplementedError

def _dump_annotation(node: ast.expr) -> str:
    """Deterministic string form of an annotation for comparison."""
    raise NotImplementedError

def validate_return_type(code: str, declared_return: ast.expr | None, func_name: str) -> list[Violation]:
    """Validate that *code*'s ``FunctionDef.returns`` matches *declared_return*.

    Parameters
    ----------
    code:
        Full source of the implementation.
    declared_return:
        Return-annotation AST from the brief's function_signature, as produced
        by ``harness.diff_fuzzer.extract_return_annotation``. ``None`` means
        the brief did not declare a return type, in which case validation is
        skipped (returning ``[]``).
    func_name:
        Name of the function to locate in *code*.

    Returns
    -------
    list[Violation]
        Empty on match / skip. A single ``return_type_mismatch`` error on
        mismatch, unannotated impl, function-not-found, or unparsable source.
    """
    raise NotImplementedError

def _bare_alias_matches_subscripted(a: ast.expr, b: ast.expr) -> bool:
    """Return True if one side is a bare collection alias and the other is a
    subscripted form of the same head (post-normalisation).

    Example equivalents handled here:
      - ``dict`` vs ``dict[str, Any]``
      - ``list`` vs ``list[int]``

    Asymmetric by design: requires exactly one side bare, the other subscripted.
    Two subscripted forms with differing slices (e.g. ``List[int]`` vs
    ``List[str]``) do NOT match here — they hit the earlier dump-inequality
    branch and surface as violations.
    """
    raise NotImplementedError

class _DocstringRemover(ast.NodeTransformer):
    """Remove docstrings from module, class, and function bodies."""

    def _strip_docstring(self, body: list[ast.stmt]) -> list[ast.stmt]:
        raise NotImplementedError

    def visit_Module(self, node: ast.Module) -> ast.Module:
        raise NotImplementedError

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        raise NotImplementedError

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
        raise NotImplementedError

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        raise NotImplementedError

class _RedundantPassRemover(ast.NodeTransformer):
    """Remove 'pass' statements from bodies that contain other statements."""

    def _clean_body(self, body: list[ast.stmt]) -> list[ast.stmt]:
        raise NotImplementedError

    def generic_visit(self, node: ast.AST) -> ast.AST:
        raise NotImplementedError

class _ImportSorter(ast.NodeTransformer):
    """Sort import statements alphabetically within their contiguous groups."""

    def visit_Module(self, node: ast.Module) -> ast.Module:
        raise NotImplementedError

    def _import_sort_key(self, node: ast.stmt) -> str:
        raise NotImplementedError

    def _sort_imports(self, body: list[ast.stmt]) -> list[ast.stmt]:
        """Find contiguous runs of import statements and sort each run."""
        raise NotImplementedError

class _VariableNormalizer(ast.NodeTransformer):
    """Rename local variables to v0, v1, v2... in order of first appearance.

    Does NOT rename:
    - Function/method parameters (they are part of the signature)
    - Names that are defined at module scope (global names)
    - Function and class names
    - Imported names
    - Built-in names
    """

    def __init__(self) -> None:
        raise NotImplementedError

    def visit_Module(self, node: ast.Module) -> ast.Module:
        raise NotImplementedError

    def _collect_protected_names(self, module: ast.Module) -> None:
        """Collect names that should not be renamed."""
        raise NotImplementedError

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        raise NotImplementedError

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
        raise NotImplementedError

    def _normalize_function_locals(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Rename local variables inside a function body."""
        raise NotImplementedError

def _apply_rename(node: ast.AST, rename_map: dict[str, str], protected: set[str]) -> None:
    """Rename Name nodes within *node* according to *rename_map*."""
    raise NotImplementedError

def normalize_ast(code: str) -> ast.Module:
    """Normalize AST for structural comparison.

    Pipeline:
    1. Parse to AST
    2. Remove docstrings
    3. Normalize variable names (locals only)
    4. Sort imports alphabetically
    5. Remove redundant pass statements
    6. Fix missing locations
    """
    raise NotImplementedError

def ast_to_canonical(tree: ast.Module) -> str:
    """Convert a normalized AST back to canonical source code."""
    raise NotImplementedError

def are_structurally_equivalent(code_a: str, code_b: str) -> bool:
    """Return True if two code samples produce identical normalized ASTs."""
    raise NotImplementedError
AnnotationNormalizer = _AnnotationNormalizer
DocstringRemover = _DocstringRemover
RedundantPassRemover = _RedundantPassRemover
ImportSorter = _ImportSorter
import sys
from typing import Any
try:
    from harness.ast_enforcer import Violation
except ImportError:
    from dataclasses import dataclass

    @dataclass
    class Violation:
        rule: str
        severity: str
        line: int
        message: str