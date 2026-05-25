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

class _ValidationVisitor(ast.NodeVisitor):
    """Walk the AST and collect Violation instances."""

    def __init__(self, *, allow_nondeterminism: bool=False) -> None:
        self.violations: list[Violation] = []
        self.allow_nondeterminism = allow_nondeterminism
        self._has_funcdef = False
        self._in_except_handler = False

    def _add(self, rule: str, severity: str, line: int, message: str) -> None:
        self.violations.append(Violation(rule=rule, severity=severity, line=line, message=message))

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
            for alias in node.names:
                if alias.name in _NONDETERMINISTIC_MODULES:
                    self._add(rule='nondeterminism', severity='error', line=node.lineno, message=f"Nondeterministic module '{alias.name}' is imported.")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if not self.allow_nondeterminism and node.module:
            if node.module in _NONDETERMINISTIC_MODULES:
                self._add(rule='nondeterminism', severity='error', line=node.lineno, message=f"Nondeterministic module '{node.module}' is imported.")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        self._check_dangerous_calls(node)
        self._check_nondeterministic_call(node)
        self._check_os_system(node)
        self._check_subprocess_check(node)
        self._check_side_effects(node)
        self.generic_visit(node)

    def _check_dangerous_calls(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            if node.func.id in {'eval', 'exec', '__import__'}:
                self._add(rule='security', severity='error', line=node.lineno, message=f"Dangerous call '{node.func.id}' is banned.")

    def visit_Assign(self, node: ast.Assign) -> None:
        is_string = False
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            is_string = True
        elif isinstance(node.value, ast.Str):
            is_string = True
        if is_string:
            for target in node.targets:
                for subnode in ast.walk(target):
                    if isinstance(subnode, ast.Name):
                        name_lower = subnode.id.lower()
                        if any((k in name_lower for k in ('password', 'secret', 'key'))):
                            self._add(rule='security', severity='error', line=node.lineno, message=f"Hardcoded credential in assignment to '{subnode.id}'.")
                            self.generic_visit(node)
                            return
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            is_string = False
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                is_string = True
            elif isinstance(node.value, ast.Str):
                is_string = True
            if is_string:
                for subnode in ast.walk(node.target):
                    if isinstance(subnode, ast.Name):
                        name_lower = subnode.id.lower()
                        if any((k in name_lower for k in ('password', 'secret', 'key'))):
                            self._add(rule='security', severity='error', line=node.lineno, message=f"Hardcoded credential in assignment to '{subnode.id}'.")
                            self.generic_visit(node)
                            return
        self.generic_visit(node)

    def _check_nondeterministic_call(self, node: ast.Call) -> None:
        """Rule 3: detect time.time(), datetime.now(), os.urandom()."""
        if not self.allow_nondeterminism:
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                pair = (node.func.value.id, node.func.attr)
                if pair in _NONDETERMINISTIC_CALLS:
                    self._add(rule='nondeterminism', severity='error', line=node.lineno, message=f"Nondeterministic call '{pair[0]}.{pair[1]}()' is banned.")

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is None:
            non_doc_stmts = []
            for stmt in node.body:
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, (ast.Constant, ast.Str)):
                    continue
                non_doc_stmts.append(stmt)
            if len(non_doc_stmts) == 1 and isinstance(non_doc_stmts[0], ast.Pass):
                self._add(rule='bare_except', severity='error', line=node.lineno, message="Bare except containing only 'pass' is banned.")
        self._in_except_handler = True
        try:
            self.generic_visit(node)
        finally:
            self._in_except_handler = False

    def _check_os_system(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            if node.func.value.id == 'os' and node.func.attr == 'system':
                self._add(rule='os_system', severity='error', line=node.lineno, message='os.system() is banned; use subprocess with check=True instead.')

    def _check_subprocess_check(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            if node.func.value.id == 'subprocess' and node.func.attr in {'run', 'call'}:
                has_check = any((kw.arg == 'check' for kw in node.keywords))
                if not has_check:
                    self._add(rule='subprocess_no_check', severity='error', line=node.lineno, message=f'subprocess.{node.func.attr}() without check is banned.')

    def _check_side_effects(self, node: ast.Call) -> None:
        if getattr(self, '_in_except_handler', False):
            return
        if isinstance(node.func, ast.Name):
            if node.func.id in _SIDE_EFFECT_NAMES:
                self._add(rule='side_effect', severity='error', line=node.lineno, message=f"Side effect call '{node.func.id}' is banned.")
                return
        chain = []
        curr = node.func
        while isinstance(curr, ast.Attribute):
            chain.append(curr.attr)
            curr = curr.value
        if isinstance(curr, ast.Name):
            chain.append(curr.id)
            chain.reverse()
            if tuple(chain) in _SIDE_EFFECT_ATTRS:
                attr_path = '.'.join(chain)
                self._add(rule='side_effect', severity='error', line=node.lineno, message=f"Side effect call '{attr_path}' is banned.")

    def _check_recursion(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Warn if a function contains a recursive call without a visible
        base case.  Heuristic: walk top-level statements in body order.  If a
        recursive call is found before any ``if`` or ``return`` statement, flag
        it as potentially unbounded."""
        func_name = node.name

        def has_unprotected_recursive_call(n: ast.AST) -> bool:
            if isinstance(n, (ast.If, ast.IfExp, ast.For, ast.While, ast.Try, ast.With, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                return False
            if isinstance(n, ast.Call):
                if isinstance(n.func, ast.Name) and n.func.id == func_name:
                    return True
            for child in ast.iter_child_nodes(n):
                if has_unprotected_recursive_call(child):
                    return True
            return False
        for stmt in node.body:
            if isinstance(stmt, (ast.If, ast.Return)):
                break
            if has_unprotected_recursive_call(stmt):
                self._add(rule='unbounded_recursion', severity='warning', line=stmt.lineno, message=f'Function {func_name} contains a potentially unbounded recursive call.')
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
    violations: list[Violation] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        violations.append(Violation(rule='syntax', severity='error', line=exc.lineno or 0, message=f'SyntaxError: {exc.msg}'))
        return violations
    visitor = _ValidationVisitor(allow_nondeterminism=allow_nondeterminism)
    visitor.visit(tree)
    violations.extend(visitor.violations)
    if not visitor._has_funcdef:

        def _is_mergeable_top(n: ast.stmt) -> bool:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.ImportFrom)):
                return True
            if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                return True
            if isinstance(n, ast.Assign) and n.targets and isinstance(n.targets[0], (ast.Name, ast.Tuple, ast.List)):
                return True
            return False
        has_mergeable_top_level = any((_is_mergeable_top(n) for n in tree.body))
        if not has_mergeable_top_level:
            violations.append(Violation(rule='incomplete_ast', severity='error', line=0, message='code must contain at least one FunctionDef, AsyncFunctionDef, ClassDef, ImportFrom, or top-level Assign / AnnAssign that can merge into the target'))
    if declared_signature:
        violations.extend(_check_declared_return_type(code, declared_signature))
    return violations

def _check_declared_return_type(code: str, declared_signature: str) -> list[Violation]:
    """Reconcile the brief's declared signature against the impl.
    
    Extracts the declared return annotation and the function name from
    *declared_signature*, then defers to :func:`validate_return_type`.

    Returns ``[]`` when the brief signature does not parse to a usable
    ``FunctionDef`` (logged at WARNING). This is the "no-op skip" path
    documented in W76b: a malformed brief should not crash the validator nor
    spuriously reject otherwise-valid impls.
    """
    from harness.diff_fuzzer import extract_return_annotation
    declared_return = extract_return_annotation(declared_signature)
    func_name = _extract_func_name_from_signature(declared_signature)
    if func_name is None:
        logger.warning('validate_code: declared_signature did not parse to a FunctionDef; skipping return-type check. signature=%r', declared_signature)
        return []
    return validate_return_type(code, declared_return, func_name)

def _extract_func_name_from_signature(signature_src: str) -> str | None:
    """Return the function name declared in a brief signature, or None.
    
    Mirrors the parsing strategy of
    :func:`harness.diff_fuzzer.extract_return_annotation` -- accepts both
    full-form (``def foo(...) -> T: ...``) and header-only (``def foo(...)``)
    inputs, with sync and async variants.
    """
    if not signature_src or not signature_src.strip():
        return None
    tree: ast.AST | None = None
    for candidate in (signature_src, signature_src.rstrip() + '\n    pass\n'):
        try:
            tree = ast.parse(candidate)
            break
        except (SyntaxError, TypeError, ValueError):
            tree = None
            continue
    if tree is None:
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.name
    return None
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
        return _TYPING_ALIAS_EQUIVALENTS.get(name, name)

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.value, ast.Name) and node.value.id == 'typing' and (node.attr in _TYPING_ALIAS_EQUIVALENTS):
            return ast.Name(id=_TYPING_ALIAS_EQUIVALENTS[node.attr], ctx=ast.Load())
        if isinstance(node.value, ast.Name) and node.value.id == 'typing':
            return ast.Name(id=node.attr, ctx=ast.Load())
        return node

    def visit_Name(self, node: ast.Name) -> ast.AST:
        alias = self._bare_alias(node.id)
        if alias != node.id:
            return ast.Name(id=alias, ctx=ast.Load())
        return node

    def visit_Subscript(self, node: ast.Subscript) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.value, ast.Name) and node.value.id == 'Optional':
            inner = node.slice
            none_node = ast.Constant(value=None)
            union_slice = ast.Tuple(elts=[inner, none_node], ctx=ast.Load())
            return ast.Subscript(value=ast.Name(id='Union', ctx=ast.Load()), slice=union_slice, ctx=ast.Load())
        return node
    'Strip surface-level typing noise so structurally-equal annotations compare equal.'

def _resolve_string_annotation(node: ast.expr) -> ast.expr | None:
    """Unwrap ``Constant(value=<str>)`` PEP-563 forward references."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            return ast.parse(node.value, mode='eval').body
        except SyntaxError:
            return None
    return node

def _normalize_annotation(node: ast.expr) -> ast.expr | None:
    """Apply string-unwrap + typing-alias normalisation. Returns None on failure."""
    resolved = _resolve_string_annotation(node)
    if resolved is None:
        return None
    try:
        snapshot = ast.parse(ast.unparse(resolved), mode='eval').body
    except (SyntaxError, ValueError):
        return None
    return _AnnotationNormalizer().visit(snapshot)

def _dump_annotation(node: ast.expr) -> str:
    """Deterministic string form of an annotation for comparison."""
    return ast.dump(node, annotate_fields=False, include_attributes=False)

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
    if declared_return is None:
        return []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [Violation(rule='return_type_mismatch', severity='error', line=exc.lineno or 0, message=f'cannot validate return type for {func_name!r}: SyntaxError: {exc.msg}')]
    target: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            target = node
            break
    if target is None:
        return [Violation(rule='return_type_mismatch', severity='error', line=0, message=f'function {func_name!r} not found in code')]
    impl_returns = target.returns
    if impl_returns is None:
        declared_src = ast.unparse(declared_return)
        return [Violation(rule='return_type_mismatch', severity='error', line=target.lineno, message=f"function {func_name!r} has no return annotation; brief declared '-> {declared_src}'")]
    norm_declared = _normalize_annotation(declared_return)
    norm_impl = _normalize_annotation(impl_returns)
    if norm_declared is None or norm_impl is None:
        return [Violation(rule='return_type_mismatch', severity='error', line=target.lineno, message=f'could not normalise return annotations for {func_name!r}')]
    if _dump_annotation(norm_declared) != _dump_annotation(norm_impl):
        if _bare_alias_matches_subscripted(norm_declared, norm_impl):
            return []
        return [Violation(rule='return_type_mismatch', severity='error', line=target.lineno, message=f"return-type mismatch for {func_name!r}: brief '-> {ast.unparse(declared_return)}' vs impl '-> {ast.unparse(impl_returns)}'")]
    return []

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
    g = globals()
    normalize_fn = g.get('_normalize_annotation')
    alias_equivs = g.get('_TYPING_ALIAS_EQUIVALENTS')
    if normalize_fn is None or alias_equivs is None:
        try:
            import harness.ast_enforcer as target_mod
        except ImportError:
            target_mod = sys.modules.get('harness.ast_enforcer')
        if target_mod is not None:
            if normalize_fn is None:
                normalize_fn = getattr(target_mod, '_normalize_annotation', None)
            if alias_equivs is None:
                alias_equivs = getattr(target_mod, '_TYPING_ALIAS_EQUIVALENTS', None)
    if normalize_fn is None or alias_equivs is None:
        return False
    norm_a = normalize_fn(a)
    norm_b = normalize_fn(b)
    if norm_a is None or norm_b is None:
        return False
    collection_aliases = set(alias_equivs.values())
    if isinstance(norm_a, ast.Name) and isinstance(norm_b, ast.Subscript):
        if norm_a.id in collection_aliases:
            if isinstance(norm_b.value, ast.Name) and norm_b.value.id == norm_a.id:
                return True
    if isinstance(norm_b, ast.Name) and isinstance(norm_a, ast.Subscript):
        if norm_b.id in collection_aliases:
            if isinstance(norm_a.value, ast.Name) and norm_a.value.id == norm_b.id:
                return True
    return False

class _DocstringRemover:
    """Remove docstrings from module, class, and function bodies."""

    def _strip_docstring(self, body: list[ast.stmt]) -> list[ast.stmt]:
        if not body:
            return body
        first = body[0]
        is_docstring = False
        if isinstance(first, ast.Expr):
            val = first.value
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                is_docstring = True
            elif isinstance(val, ast.Str):
                is_docstring = True
        if is_docstring:
            if len(body) == 1:
                return [ast.Pass()]
            else:
                return body[1:]
        return body

    def visit_Module(self, node: ast.Module) -> ast.Module:
        node.body = self._strip_docstring(node.body)
        self.generic_visit(node)
        return node

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
try:
    from harness.ast_enforcer import Violation, _NONDETERMINISTIC_MODULES, _NONDETERMINISTIC_CALLS, _SIDE_EFFECT_NAMES, _SIDE_EFFECT_ATTRS
except ImportError:
    from dataclasses import dataclass

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
import sys
try:
    from harness.ast_enforcer import Violation, _resolve_string_annotation, _AnnotationNormalizer, _TYPING_ALIAS_EQUIVALENTS
except ImportError:

    @dataclass
    class Violation:
        rule: str
        severity: str
        line: int
        message: str
try:
    from harness.ast_enforcer import Violation, _normalize_annotation, _dump_annotation, _bare_alias_matches_subscripted
except ImportError:

    @dataclass
    class Violation:
        rule: str
        severity: str
        line: int
        message: str
try:
    from harness.ast_enforcer import Violation, _ValidationVisitor, _extract_func_name_from_signature, validate_return_type
except ImportError:

    @dataclass
    class Violation:
        rule: str
        severity: str
        line: int
        message: str