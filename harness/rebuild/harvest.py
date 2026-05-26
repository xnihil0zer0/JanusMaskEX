"""HARVEST: AST-walk a module into reconstructible units + intra-module dep order.

A unit is one top-level ``def`` / ``async def``. For each we capture the
signature line, docstring, decorators, and the set of sibling top-level names
it references (the dependency edges). ``order_units`` returns a dependency
order (callees before callers) so a unit's reconstruction can rely on already
real sibling bodies.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

from harness.rebuild.deps import external_units, module_has_top_level_external_import


@dataclass
class Unit:
    """One reconstructible function (top-level ``def`` or a class method).

    ``cls`` is ``None`` for a module-level function; for a method it is the
    enclosing class name and ``qualname`` reads ``module:Class.method``.
    """

    module: str
    name: str
    qualname: str
    signature: str
    docstring: str | None
    decorators: list[str]
    calls: set[str] = field(default_factory=set)
    cls: str | None = None
    impure: bool = False
    needs_deps: bool = False
    untyped: bool = False
    whole_class: bool = False
    methods: list[str] = field(default_factory=list)
    class_skeleton: str = ''
    rel_import: bool = False
    self_mutating: bool = False
    unfuzzable: bool = False


# Modules/builtins whose use makes a unit non-deterministic or IO-bound, so the
# merged==original differential ORACLE is unreliable for it and the engine must
# fall back to the unit's scoped tests. Conservative: a false positive only
# costs the (redundant) oracle gate, never correctness.
_IMPURE_MODULES = frozenset({
    'time', 'random', 'datetime', 'os', 'sys', 'socket', 'secrets', 'uuid',
    'subprocess', 'requests', 'urllib', 'shutil', 'tempfile', 'threading',
    'multiprocessing', 'asyncio',
})
_IMPURE_BUILTINS = frozenset({'open', 'input'})


def _is_impure(node: ast.AST) -> bool:
    """True iff ``node``'s body references nondeterministic / IO-bound names."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and (sub.id in _IMPURE_BUILTINS or sub.id in _IMPURE_MODULES):
            return True
        if isinstance(sub, ast.Attribute):
            root: ast.AST = sub
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name) and root.id in _IMPURE_MODULES:
                return True
    return False


# In-place mutators that, called on a module-level global, change shared module
# state as a side effect (the function's real contract is that mutation, not its
# return value).
_MUTATING_METHODS = frozenset({
    'append', 'insert', 'extend', 'remove', 'pop', 'clear', 'sort', 'reverse',
    'update', 'add', 'discard', 'setdefault', 'popitem', 'intersection_update',
    'difference_update', 'symmetric_difference_update',
})


def _module_global_names(tree: ast.Module) -> set[str]:
    """Names bound at MODULE top level (the module's mutable global state)."""
    names: set[str] = set()
    for n in tree.body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            names.add(n.target.id)
    return names


def _mutates_module_globals(node: ast.AST, module_globals: set[str]) -> bool:
    """True iff ``node`` mutates module-level global state as a side effect.

    A module-level helper like inflection's ``_irregular`` (``PLURALS.insert(...)``,
    returns ``None``) is contractually a side-effecting INITIALIZER -- it is only
    ever called at import time with valid inputs, never the arbitrary fuzz inputs
    the merged==original differential oracle throws at it. Fuzzing it produces
    spurious ``exception_mismatch`` divergences (e.g. ``caps('')`` -> IndexError on
    the original) that no correct reconstruction can match. Worse, such a helper is
    typically CALLED at module level, so until it is reconstructed every other
    unit's candidate module fails to import. Route it (like ``impure``) to the
    tests-only path so the authored pytest oracle -- which calls it with real
    inputs -- is the honest gate. Detection: a rebind of a ``global``-declared
    name, or an in-place subscript/attribute store or mutating method call on a
    module global.
    """
    declared_global: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Global):
            declared_global.update(sub.names)
    targets = module_globals | declared_global
    if not targets:
        return False
    for sub in ast.walk(node):
        if isinstance(sub, ast.AugAssign) and isinstance(sub.target, ast.Name) and sub.target.id in declared_global:
            return True
        if isinstance(sub, ast.Assign):
            for t in sub.targets:
                if isinstance(t, ast.Name) and t.id in declared_global:
                    return True
        if isinstance(sub, (ast.Subscript, ast.Attribute)) and isinstance(sub.ctx, ast.Store):
            root: ast.AST = sub
            while isinstance(root, (ast.Subscript, ast.Attribute)):
                root = root.value
            if isinstance(root, ast.Name) and root.id in targets:
                return True
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr in _MUTATING_METHODS:
            obj = sub.func.value
            if isinstance(obj, ast.Name) and obj.id in targets:
                return True
    return False


def _signature_line(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = ast.unparse(node.args)
    ret = f' -> {ast.unparse(node.returns)}' if node.returns is not None else ''
    prefix = 'async def' if isinstance(node, ast.AsyncFunctionDef) else 'def'
    return f'{prefix} {node.name}({args}){ret}:'


def _has_relative_import(tree: ast.Module) -> bool:
    """True iff the module uses a relative import (``from .x import y``).

    The merged==original differential oracle execs the module source STANDALONE
    (no package context), so a relative import raises ``ImportError`` there. A
    module that uses one therefore can't be gated by that oracle and must route
    to the tests-only path (run inside the real package), mirroring the ``impure``
    precedent -- a conservative false oracle-skip only costs the redundant oracle.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            return True
    return False


def _class_is_stateful(node: ast.ClassDef) -> bool:
    """True iff a class shares instance state across methods (reconstruct as ONE).

    Stateful = an ``__init__`` STORES ``self.<attr>`` AND at least one OTHER
    method READS a ``self.<attr>``. Such a class cannot be reconstructed
    per-method: a method verified first FAILS because the shared multi-method
    test also exercises its siblings, which are still ``NotImplementedError``
    stubs (the #34 per-method-recon-needs-per-method-tests gotcha). So it routes
    to CLASS-granular reconstruction (all methods in one blind submission, gated
    by the class's tests). A stateless class keeps per-method recon (#34).
    """
    init_attrs: set[str] = set()
    for m in node.body:
        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name == '__init__':
            for sub in ast.walk(m):
                if (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name)
                        and sub.value.id == 'self' and isinstance(sub.ctx, ast.Store)):
                    init_attrs.add(sub.attr)
    if not init_attrs:
        return False
    for m in node.body:
        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name != '__init__':
            for sub in ast.walk(m):
                if (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name)
                        and sub.value.id == 'self' and sub.attr in init_attrs):
                    return True
    return False


def _is_self_mutating(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True iff a method only mutates ``self`` with no meaningful fuzz domain.

    A dataclass ``__post_init__`` (or any method that STORES ``self.<attr>`` and
    returns no value) has no constructible fuzz inputs. The merged==original
    differential ORACLE resolves the target by name in the MODULE namespace, but
    a method lives inside its class, so the lookup finds nothing and reports every
    input as a matching ``NameError`` -> a VACUOUS ``equivalent=True`` (it would
    "pass" a body that is plainly WRONG). Such a unit must route to the tests-only
    path (like ``impure``) so the test-author pytest oracle is the sole, honest
    gate. ``__post_init__`` is always caught; the general rule covers other
    self-mutating, value-less methods (setters, in-place updates).
    """
    params = list(node.args.posonlyargs) + list(node.args.args)
    if not params or params[0].arg != 'self':
        return False
    if node.name == '__post_init__':
        return True
    stores_self = False
    returns_value = False
    for sub in ast.walk(node):
        if (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name)
                and sub.value.id == 'self' and isinstance(sub.ctx, ast.Store)):
            stores_self = True
        if isinstance(sub, ast.Return) and sub.value is not None:
            returns_value = True
    return stores_self and not returns_value


# Annotation names/containers the differential fuzzer (diff_fuzzer._ast_node_to_strategy)
# can synthesize MEANINGFUL values for. Anything else (e.g. ``Path``, a domain
# dataclass) falls through to the fuzzer's garbage ``int`` fallback, so fuzzing it
# produces type-invalid inputs and FALSE divergences -- the unit must route to the
# tests-only path instead (mirroring ``untyped``).
_FUZZABLE_NAMES = frozenset({'None', 'NoneType', 'bool', 'int', 'float', 'str', 'bytes', 'Any'})
_FUZZABLE_CONTAINERS = frozenset({
    'list', 'List', 'set', 'Set', 'tuple', 'Tuple', 'dict', 'Dict', 'Optional', 'Union',
})


def _is_fuzzable_annotation(node: ast.expr | None) -> bool:
    """True iff ``node`` is built only from fuzzer-synthesizable primitives/containers.

    Includes the STRUCTURED-INPUT types the rebuild fuzzer now synthesizes from a
    curated corpus (``diff_fuzzer._ast_strategy_for`` / ``_path_strategy``): any
    ``ast.<NodeType>`` and ``pathlib.Path`` (bare ``Path`` or dotted). Kept in
    lock-step with the diff_fuzzer strategy table so a unit classified oracle-USABLE
    here is one the fuzzer can actually generate meaningful inputs for.
    """
    if node is None:
        return False
    if isinstance(node, ast.Name):
        return node.id in _FUZZABLE_NAMES or node.id == 'Path'
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        base = node.value.id
        if base == 'ast':
            return node.attr != 'AST'
        if base == 'pathlib' and node.attr == 'Path':
            return True
        return False
    if isinstance(node, ast.Constant):
        return node.value is None
    if isinstance(node, ast.Subscript):
        base = node.value
        if not (isinstance(base, ast.Name) and base.id in _FUZZABLE_CONTAINERS):
            return False
        sl = node.slice
        elts = sl.elts if isinstance(sl, ast.Tuple) else [sl]
        return all(
            (isinstance(e, ast.Constant) and e.value is Ellipsis) or _is_fuzzable_annotation(e)
            for e in elts
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _is_fuzzable_annotation(node.left) and _is_fuzzable_annotation(node.right)
    return False


def _has_unfuzzable_params(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True iff a value-bearing param is TYPED with a type the fuzzer can't synthesize.

    A ``Path``/domain-object param is fuzzed as a garbage ``int`` (the strategy
    table's fallback), so the merged==original differential ORACLE over-fuzzes a
    correct body into a FALSE divergence (e.g. a thin constructor wrapper that
    forwards path args into a dataclass -- ``target.mathlib_descriptor``). Such a
    unit routes to the tests-only path, where the authored oracle constructs real
    inputs. ``self``/``cls`` are exempt; an UN-typed param is handled by ``untyped``.
    """
    a = node.args
    params = list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)
    if params and params[0].arg in ('self', 'cls'):
        params = params[1:]
    for p in params:
        if p.annotation is not None and not _is_fuzzable_annotation(p.annotation):
            return True
    for extra in (a.vararg, a.kwarg):
        if extra is not None and extra.annotation is not None and not _is_fuzzable_annotation(extra.annotation):
            return True
    return False


def _has_untyped_params(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True iff any value-bearing parameter lacks a type annotation.

    A method's leading ``self``/``cls`` is exempt (it is never a fuzz input). A
    no-arg function is trivially typed. An un-typed parameter leaves the hint-aware
    differential fuzzer (``diff_fuzzer._strategy_for_annotation``) with an
    unconstrained input domain, which over-fuzzes a correct body into a FALSE
    value-divergence (the #34 ``longest([[]])`` reject), so such a unit must route
    to the tests-only path rather than the merged==original fuzz oracle.
    """
    a = node.args
    params = list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)
    if params and params[0].arg in ('self', 'cls'):
        params = params[1:]
    args_anns = any(p.annotation is None for p in params)
    star_anns = (a.vararg is not None and a.vararg.annotation is None) or (
        a.kwarg is not None and a.kwarg.annotation is None
    )
    return args_anns or star_anns


def _unit_calls(node: ast.AST, sibling_names: set[str], own_name: str) -> set[str]:
    calls: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in sibling_names and sub.id != own_name:
            calls.add(sub.id)
    return calls


def _is_test_function(name: str) -> bool:
    """A module-level pytest test function (collected by the ``test_`` prefix).

    Embedded pytest tests are not reconstructible code: rebuilding them blind
    wastes reconstruction attempts and would clobber the in-module pin. They are
    preserved verbatim in the skeleton instead of being harvested as units.
    """
    return name.startswith('test_')


def _is_pytest_class(name: str, method_defs: list) -> bool:
    """A ``Test``-prefixed class holding ``test*`` methods (a pytest test class).

    Distinguishes an embedded pytest class (skip entirely) from a real domain
    class that merely starts with ``Test`` (e.g. ``TestAuthorError(Exception)``,
    which has no ``test*`` methods).
    """
    return name.startswith('Test') and any(
        m.name.startswith('test') for m in method_defs
    )


def harvest_module(
    module_rel: str,
    source: str,
    *,
    include_methods: bool = False,
    external_modules: set[str] | frozenset[str] | None = None,
) -> list[Unit]:
    """Parse ``source`` and return its reconstructible function units.

    Top-level ``def`` / ``async def`` are always returned (``cls=None``). When
    ``include_methods`` is set, each class's methods are also returned as units
    with ``qualname`` ``module:Class.method`` and ``cls`` set -- so harvest
    handles ClassDef method units, not just module-level functions. Order is
    source order (classes contribute their methods at the class's position).

    When ``external_modules`` (the set of the project's external 3rd-party
    top-level import names) is given AND this module references any of them, the
    merged==original ORACLE is unavailable for the whole module: the oracle
    execs the ORIGINAL module source in the parent python, which would
    ``ImportError`` on the absent dependency. So EVERY unit of a dep-importing
    module is flagged ``needs_deps`` and routed (in
    :func:`harness.rebuild.task.build_unit_task`) to the oracle-skip +
    fuzzer-bypass + venv-scoped-tests path, mirroring the ``impure`` precedent.
    """
    tree = ast.parse(source)
    module_globals = _module_global_names(tree)
    sibling_names = {
        n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    units: list[Unit] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_test_function(node.name):
                continue
            units.append(
                Unit(
                    module=module_rel,
                    name=node.name,
                    qualname=f'{module_rel}:{node.name}',
                    signature=_signature_line(node),
                    docstring=ast.get_docstring(node, clean=False),
                    decorators=[ast.unparse(d) for d in node.decorator_list],
                    calls=_unit_calls(node, sibling_names, node.name),
                    impure=_is_impure(node) or _mutates_module_globals(node, module_globals),
                    untyped=_has_untyped_params(node),
                    unfuzzable=_has_unfuzzable_params(node),
                )
            )
        elif include_methods and isinstance(node, ast.ClassDef):
            method_defs = [
                m for m in node.body
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            method_names = {m.name for m in method_defs}
            scope = sibling_names | method_names
            if _is_pytest_class(node.name, method_defs):
                continue
            if _class_is_stateful(node):
                # CLASS-granular: ONE unit reconstructs every method together,
                # gated by the class's (shared, multi-method) tests. The agent
                # gets the class skeleton (signatures + docstrings, bodies
                # stubbed) so it reveals the public API but no original body.
                from harness.rebuild.strip import strip_source  # lazy: no cycle
                class_src = ast.get_source_segment(source, node) or ''
                try:
                    skeleton = strip_source(class_src) if class_src else ''
                except SyntaxError:
                    skeleton = class_src
                calls: set[str] = set()
                for m in method_defs:
                    calls |= _unit_calls(m, sibling_names, m.name)
                units.append(
                    Unit(
                        module=module_rel,
                        name=node.name,
                        qualname=f'{module_rel}:{node.name}',
                        signature=f'class {node.name}:',
                        docstring=ast.get_docstring(node, clean=False),
                        decorators=[ast.unparse(d) for d in node.decorator_list],
                        calls=calls,
                        cls=node.name,
                        impure=any(_is_impure(m) or _mutates_module_globals(m, module_globals) for m in method_defs),
                        untyped=any(_has_untyped_params(m) for m in method_defs),
                        unfuzzable=any(_has_unfuzzable_params(m) for m in method_defs),
                        whole_class=True,
                        methods=[m.name for m in method_defs],
                        class_skeleton=skeleton,
                    )
                )
            else:
                for m in method_defs:
                    units.append(
                        Unit(
                            module=module_rel,
                            name=m.name,
                            qualname=f'{module_rel}:{node.name}.{m.name}',
                            signature=_signature_line(m),
                            docstring=ast.get_docstring(m, clean=False),
                            decorators=[ast.unparse(d) for d in m.decorator_list],
                            calls=_unit_calls(m, scope, m.name),
                            cls=node.name,
                            impure=_is_impure(m) or _mutates_module_globals(m, module_globals),
                            untyped=_has_untyped_params(m),
                            self_mutating=_is_self_mutating(m),
                            unfuzzable=_has_unfuzzable_params(m),
                        )
                    )
    if external_modules:
        if module_has_top_level_external_import(source, external_modules):
            # A TOP-LEVEL dep import breaks the parent-python oracle for the
            # WHOLE module (the oracle execs the original module, which
            # ImportErrors on the absent dep) -> route every unit to the
            # venv-tests-only path.
            for unit in units:
                unit.needs_deps = True
        else:
            # No top-level dep import: the oracle CAN exec the module, so only
            # the units that actually touch a dep (a function-LOCAL import, or a
            # name bound from a dep) are routed to the tests-only path. C9.8
            # function-level refinement.
            dep_units = external_units(source, external_modules)
            for unit in units:
                names = unit.methods if unit.whole_class else [unit.name]
                if any(n in dep_units for n in names):
                    unit.needs_deps = True
    if _has_relative_import(tree):
        for unit in units:
            unit.rel_import = True
    return units


def unit_cross_calls(
    source: str, module_aliases: dict[str, str], importing_rel: str | None = None
) -> dict[str, set[tuple[str, str]]]:
    """Map each unit's short name -> the cross-module callees it references.

    ``module_aliases`` maps an import name (``casing``, ``pkg.sub``) to the rel
    path of an intra-project module OTHER than this one. A reference resolves to
    a cross-module callee when it is ``<alias>.<attr>`` for an imported module
    alias, or a bare name imported via ``from <module> import <name>``. When
    ``importing_rel`` (this module's rel path) is given, RELATIVE imports
    (``from .x import y`` / ``from . import x``, ``node.level>0``) are resolved
    against the importing module's package too (C9.9 packages). The returned value
    is ``{unit_name: {(callee_module_rel, callee_name), ...}}``; the loop uses it
    to inject cross-module sibling signatures so a caller can be reconstructed
    against an already-real callee in another module.
    """
    if not module_aliases:
        return {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    from harness.rebuild.discover import _import_from_targets  # lazy: no cycle
    alias_to_mod: dict[str, str] = {}
    sym_to_mod: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                top = a.name.split('.')[0]
                mod = module_aliases.get(a.name) or module_aliases.get(top)
                if mod:
                    alias_to_mod[a.asname or top] = mod
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            top = node.module.split('.')[0]
            mod = module_aliases.get(node.module) or module_aliases.get(top)
            if mod:
                for a in node.names:
                    sym_to_mod[a.asname or a.name] = mod
        elif isinstance(node, ast.ImportFrom) and node.level and importing_rel:
            # Relative import: resolve the absolute module target per imported name.
            if node.module:
                # ``from .x import y, z`` -> module pkg.x; y/z are SYMBOLS of it.
                targets = _import_from_targets(importing_rel, node)
                mod = None
                for cand in targets:
                    mod = module_aliases.get(cand) or module_aliases.get(cand.split('.')[-1])
                    if mod:
                        break
                if mod:
                    for a in node.names:
                        sym_to_mod[a.asname or a.name] = mod
            else:
                # ``from . import sub`` -> each name is a SUBMODULE alias (sub.fn).
                base = _import_from_targets(importing_rel, node)
                for a, cand in zip(node.names, base):
                    mod = module_aliases.get(cand) or module_aliases.get(cand.split('.')[-1])
                    if mod:
                        alias_to_mod[a.asname or a.name] = mod
    if not alias_to_mod and not sym_to_mod:
        return {}
    result: dict[str, set[tuple[str, str]]] = {}

    def scan(node: ast.AST, name: str) -> None:
        calls: set[tuple[str, str]] = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name):
                if sub.value.id in alias_to_mod:
                    calls.add((alias_to_mod[sub.value.id], sub.attr))
            elif isinstance(sub, ast.Name) and sub.id in sym_to_mod:
                calls.add((sym_to_mod[sub.id], sub.id))
        if calls:
            result[name] = result.get(name, set()) | calls

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scan(node, node.name)
        elif isinstance(node, ast.ClassDef):
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    scan(m, m.name)
    return result


def order_units(units: list[Unit]) -> list[Unit]:
    """Return units in dependency order (callees before callers).

    Pure intra-module: only edges to siblings present in ``units`` count.
    Deterministic: ties and cycles fall back to source order, so the result is
    stable across runs.
    """
    by_name = {u.name: u for u in units}
    source_index = {u.name: i for i, u in enumerate(units)}
    ordered: list[Unit] = []
    placed: set[str] = set()
    visiting: set[str] = set()

    def visit(u: Unit) -> None:
        if u.name in placed or u.name in visiting:
            return
        visiting.add(u.name)
        for dep in sorted(u.calls, key=lambda n: source_index.get(n, 1 << 30)):
            dep_unit = by_name.get(dep)
            if dep_unit is not None:
                visit(dep_unit)
        visiting.discard(u.name)
        if u.name not in placed:
            placed.add(u.name)
            ordered.append(u)

    for u in units:
        visit(u)
    return ordered
