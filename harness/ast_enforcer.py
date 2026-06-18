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
        self._function_stack: list[str] = []

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
                top = alias.name.split('.')[0]
                if top in _NONDETERMINISTIC_MODULES:
                    self._add('nondeterminism', 'error', node.lineno, f'import {alias.name} introduces non-determinism')
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if not self.allow_nondeterminism and node.module:
            top = node.module.split('.')[0]
            if top in _NONDETERMINISTIC_MODULES:
                self._add('nondeterminism', 'error', node.lineno, f'from {node.module} import ... introduces non-determinism')
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        self._check_nondeterministic_call(node)
        self._check_os_system(node)
        self._check_subprocess_check(node)
        self._check_side_effects(node)
        self._check_dangerous_calls(node)
        self.generic_visit(node)

    def _check_dangerous_calls(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in {'eval', 'exec', '__import__'}:
            self._add('security', 'error', node.lineno, f'{node.func.id}() is banned for security reasons')

    def visit_Assign(self, node: ast.Assign) -> None:
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if _looks_like_hardcoded_credential(target.id, node.value.value):
                        self._add('security', 'error', node.lineno, f"Hardcoded credential detected in variable '{target.id}'")
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            if isinstance(node.target, ast.Name):
                if _looks_like_hardcoded_credential(node.target.id, node.value.value):
                    self._add('security', 'error', node.lineno, f"Hardcoded credential detected in variable '{node.target.id}'")
        self.generic_visit(node)

    def _check_nondeterministic_call(self, node: ast.Call) -> None:
        """Rule 3: detect time.time(), datetime.now(), os.urandom()."""
        if self.allow_nondeterminism:
            return
        if isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            if isinstance(node.func.value, ast.Name):
                module_name = node.func.value.id
                if (module_name, attr_name) in _NONDETERMINISTIC_CALLS:
                    self._add('nondeterminism', 'error', node.lineno, f'{module_name}.{attr_name}() introduces non-determinism')

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is None:
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                self._add('bare_except', 'error', node.lineno, "bare 'except: pass' silently swallows all exceptions")
        self.generic_visit(node)

    def _check_os_system(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr == 'system' and isinstance(node.func.value, ast.Name) and (node.func.value.id == 'os'):
            self._add('os_system', 'error', node.lineno, 'os.system() is banned; use subprocess with explicit args')

    def _check_subprocess_check(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Attribute):
            return
        if not isinstance(node.func.value, ast.Name):
            return
        if node.func.value.id != 'subprocess':
            return
        if node.func.attr not in ('run', 'call'):
            return
        has_check = False
        for kw in node.keywords:
            if kw.arg == 'check':
                has_check = True
                break
        if not has_check:
            self._add('subprocess_no_check', 'warning', node.lineno, f'subprocess.{node.func.attr}() without check=True; consider adding check=True or explicitly inspecting returncode')

    def _check_side_effects(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in _SIDE_EFFECT_NAMES:
            self._add('side_effect', 'warning', node.lineno, f'{node.func.id}() is a side effect; prefer pure functions')
            return
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == 'write' and isinstance(node.func.value, ast.Attribute) and (node.func.value.attr == 'stdout') and isinstance(node.func.value.value, ast.Name) and (node.func.value.value.id == 'sys'):
                self._add('side_effect', 'warning', node.lineno, 'sys.stdout.write() is a side effect; prefer pure functions')

    def _check_recursion(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Warn if a function contains a recursive call without a visible
        base case.  Heuristic: walk top-level statements in body order.  If a
        recursive call is found before any ``if`` or ``return`` statement, flag
        it as potentially unbounded."""
        func_name = node.name
        seen_guard = False

        class _CallFinder(ast.NodeVisitor):

            def __init__(self) -> None:
                self.unguarded: ast.Call | None = None
                self.in_guard = False

            def visit_Call(self, cnode: ast.Call) -> None:
                if isinstance(cnode.func, ast.Name) and cnode.func.id == func_name:
                    if not self.in_guard and self.unguarded is None:
                        self.unguarded = cnode
                self.generic_visit(cnode)

            def visit_If(self, cnode: ast.If) -> None:
                old = self.in_guard
                self.in_guard = True
                self.generic_visit(cnode)
                self.in_guard = old

            def visit_IfExp(self, cnode: ast.IfExp) -> None:
                old = self.in_guard
                self.in_guard = True
                self.generic_visit(cnode)
                self.in_guard = old

            def visit_For(self, cnode: ast.For) -> None:
                old = self.in_guard
                self.in_guard = True
                self.generic_visit(cnode)
                self.in_guard = old

            def visit_While(self, cnode: ast.While) -> None:
                old = self.in_guard
                self.in_guard = True
                self.generic_visit(cnode)
                self.in_guard = old
        for stmt in node.body:
            finder = _CallFinder()
            finder.visit(stmt)
            if finder.unguarded and (not seen_guard):
                self._add('unbounded_recursion', 'warning', getattr(finder.unguarded, 'lineno', node.lineno), f"function '{func_name}' appears to recurse without a visible base case")
                return
            if isinstance(stmt, (ast.If, ast.Return)):
                seen_guard = True

def validate_code(code: str, *, allow_nondeterminism: bool=False, declared_signature: str | None=None, relax_external_constructs: bool=False) -> list[Violation]:
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
    relax_external_constructs:
        REV22 §4-3 (CR-1/CR-2/CR-3). When True (caller has determined the
        target resolves OUTSIDE the JanusMask tree via
        ``not _target_is_self(working_dir)``), suppress ONLY the
        eval/exec/__import__ security findings emitted by
        ``_check_dangerous_calls`` (message suffix
        ``"() is banned for security reasons"``). Hardcoded-credential findings
        (also rule ``'security'`` but with a distinct message) and every other
        rule (``os_system``, ``bare_except``, ...) stay STRICT. CR-3:
        ``allow_nondeterminism`` is coerced to ``False`` FIRST so external code
        can never relax the reproducibility rule, overriding any meta-task
        auto-relax. Defaults to ``False`` (fail-safe to self).
    """
    if relax_external_constructs:
        allow_nondeterminism = False
    violations: list[Violation] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        violations.append(Violation(rule='syntax', severity='error', line=exc.lineno or 0, message=f'SyntaxError: {exc.msg}'))
        return violations
    visitor = _ValidationVisitor(allow_nondeterminism=allow_nondeterminism)
    visitor.visit(tree)
    if relax_external_constructs:
        _dangerous_suffix = '() is banned for security reasons'
        visitor.violations = [v for v in visitor.violations if not (v.rule == 'security' and v.message.endswith(_dangerous_suffix))]
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
    line_count = len(code.split('\n'))
    if line_count > 1500:
        violations.append(Violation(rule='module_too_large', severity='warning', line=0, message=f'Module has {line_count} lines, which exceeds the recommended limit of 1500 lines.'))
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
    for candidate in (signature_src, signature_src.rstrip() + '\n    pass\n'):
        try:
            tree = ast.parse(candidate)
        except SyntaxError:
            continue
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

def _looks_like_hardcoded_credential(name: str, value: str) -> bool:
    """Return True only when *name* names a credential-ish field AND *value*
    looks like a real hardcoded secret rather than a benign identifier string.

    NAME tokens are stratified: STRONG tokens
    (``password|passwd|pwd|secret|token``) flag any non-empty value; the WEAK
    token (``key``) only flags numeric values, or values of length >= 8 that
    are not pure-lowercase ``[a-z_]`` identifiers. The name is split on
    underscores AND on case boundaries and each segment is tested for equality
    (word/segment match, NOT arbitrary substring).
    """
    _strong_tokens = {'password', 'secret', 'token', 'passwd', 'pwd'}
    _weak_tokens = {'key'}
    segments: list[str] = []
    for chunk in name.split('_'):
        for piece in re.findall('[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|[0-9]+', chunk):
            segments.append(piece.lower())
    has_strong = any(seg in _strong_tokens for seg in segments)
    has_weak = any(seg in _weak_tokens for seg in segments)
    if not (has_strong or has_weak):
        return False
    if not value:
        return False
    if has_strong:
        return True
    # For weak tokens (e.g. variable name contains "key" but no strong token):
    if value.isdigit():
        return True
    if len(value) >= 8 and not re.fullmatch('[a-z_]+', value):
        return True
    return False
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
    aliases = set(_TYPING_ALIAS_EQUIVALENTS.values())

    def head_name(n: ast.expr) -> str | None:
        if isinstance(n, ast.Name):
            return n.id
        if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name):
            return n.value.id
        return None
    a_head = head_name(a)
    b_head = head_name(b)
    if a_head is None or b_head is None or a_head != b_head:
        return False
    if a_head not in aliases:
        return False
    a_bare = isinstance(a, ast.Name)
    b_bare = isinstance(b, ast.Name)
    return a_bare != b_bare

class _DocstringRemover(ast.NodeTransformer):
    """Remove docstrings from module, class, and function bodies."""

    def _strip_docstring(self, body: list[ast.stmt]) -> list[ast.stmt]:
        if not body:
            return body
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, (ast.Constant,)) and isinstance(first.value.value, str):
            return body[1:] or [ast.Pass()]
        return body

    def visit_Module(self, node: ast.Module) -> ast.Module:
        node.body = self._strip_docstring(node.body)
        self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        node.body = self._strip_docstring(node.body)
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
        node.body = self._strip_docstring(node.body)
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        node.body = self._strip_docstring(node.body)
        self.generic_visit(node)
        return node

class _RedundantPassRemover(ast.NodeTransformer):
    """Remove 'pass' statements from bodies that contain other statements."""

    def _clean_body(self, body: list[ast.stmt]) -> list[ast.stmt]:
        if len(body) <= 1:
            return body
        cleaned = [stmt for stmt in body if not isinstance(stmt, ast.Pass)]
        return cleaned if cleaned else [ast.Pass()]

    def generic_visit(self, node: ast.AST) -> ast.AST:
        if hasattr(node, 'body') and isinstance(node.body, list):
            node.body = self._clean_body(node.body)
        if hasattr(node, 'orelse') and isinstance(node.orelse, list):
            node.orelse = self._clean_body(node.orelse)
        if hasattr(node, 'finalbody') and isinstance(node.finalbody, list):
            node.finalbody = self._clean_body(node.finalbody)
        return super().generic_visit(node)

class _ImportSorter(ast.NodeTransformer):
    """Sort import statements alphabetically within their contiguous groups."""

    def visit_Module(self, node: ast.Module) -> ast.Module:
        node.body = self._sort_imports(node.body)
        self.generic_visit(node)
        return node

    def _import_sort_key(self, node: ast.stmt) -> str:
        if isinstance(node, ast.Import):
            return node.names[0].name if node.names else ''
        if isinstance(node, ast.ImportFrom):
            return node.module or ''
        return ''

    def _sort_imports(self, body: list[ast.stmt]) -> list[ast.stmt]:
        """Find contiguous runs of import statements and sort each run."""
        result: list[ast.stmt] = []
        import_group: list[ast.stmt] = []
        for stmt in body:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                import_group.append(stmt)
            else:
                if import_group:
                    import_group.sort(key=self._import_sort_key)
                    result.extend(import_group)
                    import_group = []
                result.append(stmt)
        if import_group:
            import_group.sort(key=self._import_sort_key)
            result.extend(import_group)
        return result

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
        super().__init__()
        self._global_names: set[str] = set()
        self._param_names: set[str] = set()
        self._func_class_names: set[str] = set()
        self._imported_names: set[str] = set()

    def visit_Module(self, node: ast.Module) -> ast.Module:
        self._collect_protected_names(node)
        self.generic_visit(node)
        return node

    def _collect_protected_names(self, module: ast.Module) -> None:
        """Collect names that should not be renamed."""
        for stmt in module.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._func_class_names.add(stmt.name)
            elif isinstance(stmt, ast.ClassDef):
                self._func_class_names.add(stmt.name)
            elif isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    name = alias.asname if alias.asname else alias.name.split('.')[0]
                    self._imported_names.add(name)
            elif isinstance(stmt, ast.ImportFrom):
                for alias in stmt.names:
                    name = alias.asname if alias.asname else alias.name
                    self._imported_names.add(name)
            elif isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    for name_node in ast.walk(target):
                        if isinstance(name_node, ast.Name):
                            self._global_names.add(name_node.id)
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                self._global_names.add(stmt.target.id)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        self._normalize_function_locals(node)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
        self._normalize_function_locals(node)
        return node

    def _normalize_function_locals(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Rename local variables inside a function body."""
        param_names: set[str] = set()
        for arg in node.args.args:
            param_names.add(arg.arg)
        for arg in node.args.posonlyargs:
            param_names.add(arg.arg)
        for arg in node.args.kwonlyargs:
            param_names.add(arg.arg)
        if node.args.vararg:
            param_names.add(node.args.vararg.arg)
        if node.args.kwarg:
            param_names.add(node.args.kwarg.arg)
        protected = param_names | self._global_names | self._func_class_names | self._imported_names
        local_order: list[str] = []
        seen: set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                if child.id not in protected and child.id not in seen:
                    local_order.append(child.id)
                    seen.add(child.id)
        rename_map: dict[str, str] = {}
        for idx, name in enumerate(local_order):
            rename_map[name] = f'v{idx}'
        if rename_map:
            _apply_rename(node, rename_map, protected)
        for child in ast.walk(node):
            if child is node:
                continue
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._normalize_function_locals(child)

def _apply_rename(node: ast.AST, rename_map: dict[str, str], protected: set[str]) -> None:
    """Rename Name nodes within *node* according to *rename_map*."""
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in rename_map:
            child.id = rename_map[child.id]

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
    tree = ast.parse(code)
    tree = _DocstringRemover().visit(tree)
    tree = _ImportSorter().visit(tree)
    tree = _VariableNormalizer().visit(tree)
    tree = _RedundantPassRemover().visit(tree)
    ast.fix_missing_locations(tree)
    return tree

def ast_to_canonical(tree: ast.Module) -> str:
    """Convert a normalized AST back to canonical source code."""
    return ast.unparse(tree)

def are_structurally_equivalent(code_a: str, code_b: str) -> bool:
    """Return True if two code samples produce identical normalized ASTs."""
    try:
        canonical_a = ast_to_canonical(normalize_ast(code_a))
        canonical_b = ast_to_canonical(normalize_ast(code_b))
    except SyntaxError:
        return False
    return canonical_a == canonical_b