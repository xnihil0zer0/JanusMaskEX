"""HARVEST: AST-walk a module into reconstructible units + intra-module dep order.

A unit is one top-level ``def`` / ``async def``. For each we capture the
signature line, docstring, decorators, and the set of sibling top-level names
it references (the dependency edges). ``order_units`` returns a dependency
order (callees before callers) so a unit's reconstruction can rely on already
real sibling bodies.
"""
from __future__ import annotations
import ast
from dataclasses import dataclass
from dataclasses import field
from harness.rebuild.deps import external_units
from harness.rebuild.deps import module_has_top_level_external_import

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
_IMPURE_MODULES = frozenset({'time', 'random', 'datetime', 'os', 'sys', 'socket', 'secrets', 'uuid', 'subprocess', 'requests', 'urllib', 'shutil', 'tempfile', 'threading', 'multiprocessing', 'asyncio'})
_IMPURE_BUILTINS = frozenset({'open', 'input'})

def _is_impure(node: ast.AST) -> bool:
    """True iff ``node``'s body references nondeterministic / IO-bound names."""
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute):
            value = child.value
            if isinstance(value, ast.Name) and value.id in _IMPURE_MODULES:
                return True
        elif isinstance(child, ast.Name) and child.id in _IMPURE_BUILTINS:
            return True
    return False
_MUTATING_METHODS = frozenset({'append', 'insert', 'extend', 'remove', 'pop', 'clear', 'sort', 'reverse', 'update', 'add', 'discard', 'setdefault', 'popitem', 'intersection_update', 'difference_update', 'symmetric_difference_update'})

def _module_global_names(tree: ast.Module) -> set[str]:
    """Names bound at MODULE top level (the module's mutable global state)."""
    names: set[str] = set()
    targets: list[ast.expr] = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            targets.extend(stmt.targets)
        elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
            targets.append(stmt.target)
    while targets:
        target = targets.pop()
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            targets.extend(target.elts)
        elif isinstance(target, ast.Starred):
            targets.append(target.value)
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
    mutating_methods = frozenset({'append', 'insert', 'extend', 'remove', 'pop', 'clear', 'sort', 'reverse', 'update', 'add', 'discard', 'setdefault', 'popitem', 'intersection_update', 'difference_update', 'symmetric_difference_update'})
    global_decls: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Global):
            global_decls.update(child.names)

    def _root_name(expr: ast.expr) -> str | None:
        while isinstance(expr, (ast.Attribute, ast.Subscript)):
            expr = expr.value
        return expr.id if isinstance(expr, ast.Name) else None

    def _leaf_targets(targets: list[ast.expr]):
        stack = list(targets)
        while stack:
            target = stack.pop()
            if isinstance(target, (ast.Tuple, ast.List)):
                stack.extend(target.elts)
            elif isinstance(target, ast.Starred):
                stack.append(target.value)
            else:
                yield target
    for child in ast.walk(node):
        if isinstance(child, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = child.targets if isinstance(child, ast.Assign) else [child.target]
            for target in _leaf_targets(targets):
                if isinstance(target, ast.Name):
                    if target.id in global_decls:
                        return True
                elif isinstance(target, (ast.Subscript, ast.Attribute)):
                    if _root_name(target) in module_globals:
                        return True
        elif isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute) and func.attr in mutating_methods:
                if isinstance(func.value, ast.Name) and func.value.id in module_globals:
                    return True
    return False

def _signature_line(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Render the ``def`` header line (no body) for a function node."""
    prefix = 'async def' if isinstance(node, ast.AsyncFunctionDef) else 'def'
    args = ast.unparse(node.args)
    returns = f' -> {ast.unparse(node.returns)}' if node.returns is not None else ''
    return f'{prefix} {node.name}({args}){returns}:'

def _has_relative_import(tree: ast.Module) -> bool:
    """True iff the module uses a relative import (``from .x import y``).

    The merged==original differential oracle execs the module source STANDALONE
    (no package context), so a relative import raises ``ImportError`` there. A
    module that uses one therefore can't be gated by that oracle and must route
    to the tests-only path (run inside the real package), mirroring the ``impure``
    precedent -- a conservative false oracle-skip only costs the redundant oracle.
    """
    return any((isinstance(node, ast.ImportFrom) and (node.level or 0) > 0 for node in ast.walk(tree)))

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

    def _self_attrs(method: ast.AST, ctx: type) -> set:
        attrs = set()
        for sub in ast.walk(method):
            if isinstance(sub, ast.Attribute) and isinstance(sub.ctx, ctx) and isinstance(sub.value, ast.Name) and (sub.value.id == 'self'):
                attrs.add(sub.attr)
        return attrs
    init = None
    others = []
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.name == '__init__':
                init = item
            else:
                others.append(item)
    if init is None:
        return False
    stored = _self_attrs(init, ast.Store)
    if not stored:
        return False
    return any((_self_attrs(method, ast.Load) & stored for method in others))

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
    if node.name == '__post_init__':
        return True
    stores_self = False
    for sub in ast.walk(node):
        if isinstance(sub, ast.Return) and sub.value is not None:
            return False
        if isinstance(sub, ast.Attribute) and isinstance(sub.ctx, ast.Store) and isinstance(sub.value, ast.Name) and (sub.value.id == 'self'):
            stores_self = True
    return stores_self
_FUZZABLE_NAMES = frozenset({'None', 'NoneType', 'bool', 'int', 'float', 'str', 'bytes', 'Any'})
_FUZZABLE_CONTAINERS = frozenset({'list', 'List', 'set', 'Set', 'tuple', 'Tuple', 'dict', 'Dict', 'Optional', 'Union'})

def _is_fuzzable_annotation(node: ast.expr | None) -> bool:
    """True iff ``node`` is built only from fuzzer-synthesizable primitives/containers."""
    raise NotImplementedError

def _has_unfuzzable_params(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True iff a value-bearing param is TYPED with a type the fuzzer can't synthesize.

    A ``Path``/domain-object param is fuzzed as a garbage ``int`` (the strategy
    table's fallback), so the merged==original differential ORACLE over-fuzzes a
    correct body into a FALSE divergence (e.g. a thin constructor wrapper that
    forwards path args into a dataclass -- ``target.mathlib_descriptor``). Such a
    unit routes to the tests-only path, where the authored oracle constructs real
    inputs. ``self``/``cls`` are exempt; an UN-typed param is handled by ``untyped``.
    """
    raise NotImplementedError

def _has_untyped_params(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True iff any value-bearing parameter lacks a type annotation.

    A method's leading ``self``/``cls`` is exempt (it is never a fuzz input). A
    no-arg function is trivially typed. An un-typed parameter leaves the hint-aware
    differential fuzzer (``diff_fuzzer._strategy_for_annotation``) with an
    unconstrained input domain, which over-fuzzes a correct body into a FALSE
    value-divergence (the #34 ``longest([[]])`` reject), so such a unit must route
    to the tests-only path rather than the merged==original fuzz oracle.
    """
    raise NotImplementedError

def _unit_calls(node: ast.AST, sibling_names: set[str], own_name: str) -> set[str]:
    calls = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            if child.id in sibling_names and child.id != own_name:
                calls.add(child.id)
    return calls

def _is_test_function(name: str) -> bool:
    """A module-level pytest test function (collected by the ``test_`` prefix).

    Embedded pytest tests are not reconstructible code: rebuilding them blind
    wastes reconstruction attempts and would clobber the in-module pin. They are
    preserved verbatim in the skeleton instead of being harvested as units.
    """
    raise NotImplementedError

def _is_pytest_class(name: str, method_defs: list) -> bool:
    """A ``Test``-prefixed class holding ``test*`` methods (a pytest test class).

    Distinguishes an embedded pytest class (skip entirely) from a real domain
    class that merely starts with ``Test`` (e.g. ``TestAuthorError(Exception)``,
    which has no ``test*`` methods).
    """
    raise NotImplementedError

def harvest_module(module_rel: str, source: str, *, include_methods: bool=False, external_modules: set[str] | frozenset[str] | None=None) -> list[Unit]:
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
    raise NotImplementedError

def unit_cross_calls(source: str, module_aliases: dict[str, str], importing_rel: str | None=None) -> dict[str, set[tuple[str, str]]]:
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
    raise NotImplementedError

def order_units(units: list[Unit]) -> list[Unit]:
    """Return units in dependency order (callees before callers).

    Pure intra-module: only edges to siblings present in ``units`` count.
    Deterministic: ties and cycles fall back to source order, so the result is
    stable across runs.
    """
    by_name: dict[str, Unit] = {}
    for unit in units:
        by_name.setdefault(unit.name, unit)
    source_index = {id(unit): i for i, unit in enumerate(units)}
    deps: dict[int, set[int]] = {}
    for unit in units:
        callees: set[int] = set()
        for name in unit.calls:
            target = by_name.get(name)
            if target is not None and target is not unit:
                callees.add(id(target))
        deps[id(unit)] = callees
    emitted: set[int] = set()
    remaining = list(units)
    ordered: list[Unit] = []
    while remaining:
        ready = [u for u in remaining if deps[id(u)] <= emitted]
        pool = ready if ready else remaining
        nxt = min(pool, key=lambda u: source_index[id(u)])
        ordered.append(nxt)
        emitted.add(id(nxt))
        remaining.remove(nxt)
    return ordered
'Dependency ordering for harvested intra-module units.'