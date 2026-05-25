"""DISCOVER: build a TargetDescriptor from a BARE project directory.

Session #31's engine required a hand-authored descriptor (explicit module list,
test list, selector). This makes the engine work on an ARBITRARY python/ast
project -- including JanusMask itself -- by scanning a directory: classify each
``.py`` file as a rebuild target module, a pytest spec file, or seed scaffolding
(package ``__init__`` / ``conftest``), then synthesize the descriptor fields the
loop needs (full test command + per-unit ``-k`` selector).

Callers may still override any inferred field (``modules=`` / ``test_files=`` /
``seed_files=``) to rebuild a narrow SLICE of a large project without scanning
the whole tree (e.g. a single JanusMask leaf module into JR).
"""

from __future__ import annotations

import ast
from pathlib import Path

from harness.rebuild.deps import discover_dependencies
from harness.rebuild.target import TargetDescriptor

__all__ = [
    'discover_modules',
    'build_descriptor',
    'discover_dependencies',
    'module_import_graph',
    'order_modules',
    'relative_base',
]

_SEED_NAMES = {'__init__.py', 'conftest.py'}
_SKIP_DIRS = {'__pycache__', '.git', '.hg', 'state', 'build', 'dist', '.eggs', 'node_modules'}


def _is_test_file(name: str) -> bool:
    return name.startswith('test_') and name.endswith('.py') or name.endswith('_test.py')


def _skip_dir(rel_parts: tuple[str, ...]) -> bool:
    return any(p in _SKIP_DIRS or (p.startswith('.') and p not in ('.', '..')) for p in rel_parts)


def discover_modules(source_root: Path) -> tuple[list[str], list[str], list[str]]:
    """Scan ``source_root`` and return ``(modules, test_files, seed_files)``.

    Paths are returned relative to ``source_root``, POSIX-style, sorted. Test
    files (``test_*.py`` / ``*_test.py``) and seeds (``__init__.py`` /
    ``conftest.py``) are NOT rebuild targets; everything else is a module.
    Hidden dirs, ``__pycache__``, ``state``, and build artifacts are skipped.
    """
    source_root = Path(source_root).resolve()
    modules: list[str] = []
    tests: list[str] = []
    seeds: list[str] = []
    for path in sorted(source_root.rglob('*.py')):
        rel = path.relative_to(source_root)
        if _skip_dir(rel.parts[:-1]):
            continue
        relstr = rel.as_posix()
        name = path.name
        if _is_test_file(name):
            tests.append(relstr)
        elif name in _SEED_NAMES:
            seeds.append(relstr)
        else:
            modules.append(relstr)
    return modules, tests, seeds


def _stem_map(modules: list[str]) -> dict[str, str]:
    """Map an import name -> module rel path for intra-project resolution.

    A flat module ``casing.py`` is importable as ``casing``; a packaged module
    ``pkg/sub.py`` as ``pkg.sub`` (and, best-effort, its leaf ``sub``). Both the
    dotted path and the leaf are registered so ``import casing`` and
    ``from pkg.sub import x`` both resolve.
    """
    out: dict[str, str] = {}
    for m in modules:
        dotted = m[:-3].replace('/', '.') if m.endswith('.py') else m.replace('/', '.')
        out[dotted] = m
        leaf = dotted.split('.')[-1]
        out.setdefault(leaf, m)
    return out


def relative_base(importing_rel: str, level: int) -> list[str] | None:
    """Return the absolute dotted prefix a relative import resolves against.

    For a module ``pkg/sub.py`` (dotted ``pkg.sub``, package ``pkg``) a
    ``level``-dot relative import drops ``level-1`` trailing components from the
    importing module's PACKAGE (Python's ``importlib`` semantics): ``level=1`` ->
    ``['pkg']`` (current package), ``level=2`` -> ``[]`` (parent / top-level).
    Returns ``None`` when the level ascends beyond the top-level package (an
    invalid relative import). Callers append the imported module/name to build the
    absolute dotted target, then resolve it via :func:`_stem_map`.
    """
    dotted = importing_rel[:-3].replace('/', '.') if importing_rel.endswith('.py') else importing_rel.replace('/', '.')
    pkg_parts = dotted.split('.')[:-1]
    keep = len(pkg_parts) - (level - 1)
    if keep < 0:
        return None
    return pkg_parts[:keep]


def _import_from_targets(importing_rel: str, node: ast.ImportFrom) -> list[str]:
    """Absolute dotted module name(s) an ``ImportFrom`` (absolute OR relative) names.

    Absolute ``from pkg.x import y`` -> ``['pkg.x']``. Relative ``from .x import y``
    / ``from . import x`` are resolved through :func:`relative_base` to the
    absolute package, then each ``from . import <name>`` submodule (or the single
    ``from .x`` module) is returned. Empty when a relative import is out of bounds.
    """
    if not node.level:
        return [node.module] if node.module else []
    base = relative_base(importing_rel, node.level)
    if base is None:
        return []
    if node.module:
        return ['.'.join(base + node.module.split('.'))]
    return ['.'.join(base + [a.name]) for a in node.names]


def module_import_graph(source_root: Path, modules: list[str]) -> dict[str, set[str]]:
    """Return ``{module_rel: set(intra-project module_rels it imports)}``.

    Only edges to OTHER modules in ``modules`` count (external deps and stdlib
    are ignored). Both top-level and function-local imports are considered, so a
    lazily-imported cross-module dependency still orders/taints correctly. A
    module never depends on itself.
    """
    source_root = Path(source_root).resolve()
    stem_map = _stem_map(modules)
    graph: dict[str, set[str]] = {m: set() for m in modules}
    for m in modules:
        try:
            tree = ast.parse((source_root / m).read_text(encoding='utf-8'))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                # Absolute AND relative (``node.level>0``, e.g. ``from .x import y``)
                # both resolve to intra-project module targets -- packages with
                # relative imports are first-class (C9.9).
                names = _import_from_targets(m, node)
            for nm in names:
                target = stem_map.get(nm) or stem_map.get(nm.split('.')[0])
                if target and target != m:
                    graph[m].add(target)
    return graph


def order_modules(source_root: Path, modules: list[str]) -> list[str]:
    """Order ``modules`` so an imported (callee) module precedes its importer.

    Deterministic depth-first topological order over
    :func:`module_import_graph`; ties and import CYCLES fall back to the given
    source order (so a circular ``a <-> b`` import pair is stable, never an
    error). Unit-level call dependencies are resolved separately by the loop, so
    a module-level cycle does not block reconstruction.
    """
    graph = module_import_graph(source_root, modules)
    source_index = {m: i for i, m in enumerate(modules)}
    ordered: list[str] = []
    placed: set[str] = set()
    visiting: set[str] = set()

    def visit(m: str) -> None:
        if m in placed or m in visiting:
            return
        visiting.add(m)
        for dep in sorted(graph.get(m, ()), key=lambda x: source_index.get(x, 1 << 30)):
            visit(dep)
        visiting.discard(m)
        if m not in placed:
            placed.add(m)
            ordered.append(m)

    for m in modules:
        visit(m)
    return ordered


def build_descriptor(
    source_root: Path,
    *,
    output_dir: Path,
    stash_dir: Path,
    name: str | None = None,
    modules: list[str] | None = None,
    test_files: list[str] | None = None,
    seed_files: list[str] | None = None,
    dependencies: list[str] | None = None,
    requirements_files: list[str] | None = None,
) -> TargetDescriptor:
    """Build a working ``TargetDescriptor`` from a bare dir (fields auto-inferred).

    Any of ``modules`` / ``test_files`` / ``seed_files`` may be supplied to
    rebuild a narrow slice; whatever is omitted is discovered by scanning.
    ``unit_test_selector`` is derived only when exactly one test file exists
    (the unambiguous case); otherwise it is left empty and the loop falls back
    to running the whole test list per unit. External ``dependencies`` and the
    ``requirements_files`` they came from are discovered via
    :func:`harness.rebuild.deps.discover_dependencies` unless supplied (so the
    replicant can provision its own ``.venv`` and run standalone).
    """
    source_root = Path(source_root).resolve()
    if modules is None or test_files is None or seed_files is None:
        scan_mods, scan_tests, scan_seeds = discover_modules(source_root)
        if modules is None:
            modules = scan_mods
        if test_files is None:
            test_files = scan_tests
        if seed_files is None:
            seed_files = scan_seeds
    if dependencies is None or requirements_files is None:
        scan_deps, scan_reqs = discover_dependencies(source_root)
        if dependencies is None:
            dependencies = scan_deps
        if requirements_files is None:
            requirements_files = scan_reqs
    # Order modules so an imported (callee) module is reconstructed before its
    # importer; an import cycle falls back to source order (stable).
    modules = order_modules(source_root, list(modules))
    name = name or source_root.name
    full_test_command = 'python -m pytest -q'
    if test_files:
        full_test_command = 'python -m pytest -q ' + ' '.join(test_files)
    # Per-unit ``-k`` scoping works across ANY number of test files (a unit's
    # own tests are selected by name); the exit-5 fallback in task.build_unit_task
    # covers behavior-named suites. This lets a TA-generated oracle for a
    # test-less module coexist with the project's shipped tests.
    unit_test_selector = ''
    if test_files:
        unit_test_selector = ' '.join(test_files) + ' -k {unit}'
    return TargetDescriptor(
        name=name,
        source_root=source_root,
        modules=list(modules),
        test_files=list(test_files),
        output_dir=Path(output_dir),
        stash_dir=Path(stash_dir),
        seed_files=list(seed_files),
        full_test_command=full_test_command,
        unit_test_selector=unit_test_selector,
        dependencies=list(dependencies),
        requirements_files=list(requirements_files),
    )
