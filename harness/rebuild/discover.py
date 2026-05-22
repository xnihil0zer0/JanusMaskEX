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
__all__ = ['discover_modules', 'build_descriptor', 'discover_dependencies', 'module_import_graph', 'order_modules', 'relative_base']
_SEED_NAMES = {'__init__.py', 'conftest.py'}
_SKIP_DIRS = {'__pycache__', '.git', '.hg', 'state', 'build', 'dist', '.eggs', 'node_modules'}

def _is_test_file(name: str) -> bool:
    raise NotImplementedError

def _skip_dir(rel_parts: tuple[str, ...]) -> bool:
    raise NotImplementedError

def discover_modules(source_root: Path) -> tuple[list[str], list[str], list[str]]:
    """Scan ``source_root`` and return ``(modules, test_files, seed_files)``.

    Paths are returned relative to ``source_root``, POSIX-style, sorted. Test
    files (``test_*.py`` / ``*_test.py``) and seeds (``__init__.py`` /
    ``conftest.py``) are NOT rebuild targets; everything else is a module.
    Hidden dirs, ``__pycache__``, ``state``, and build artifacts are skipped.
    """
    raise NotImplementedError

def _stem_map(modules: list[str]) -> dict[str, str]:
    """Map an import name -> module rel path for intra-project resolution.

    A flat module ``casing.py`` is importable as ``casing``; a packaged module
    ``pkg/sub.py`` as ``pkg.sub`` (and, best-effort, its leaf ``sub``). Both the
    dotted path and the leaf are registered so ``import casing`` and
    ``from pkg.sub import x`` both resolve.
    """
    raise NotImplementedError

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
    raise NotImplementedError

def module_import_graph(source_root: Path, modules: list[str]) -> dict[str, set[str]]:
    """Return ``{module_rel: set(intra-project module_rels it imports)}``.

    Only edges to OTHER modules in ``modules`` count (external deps and stdlib
    are ignored). Both top-level and function-local imports are considered, so a
    lazily-imported cross-module dependency still orders/taints correctly. A
    module never depends on itself.
    """
    raise NotImplementedError

def order_modules(source_root: Path, modules: list[str]) -> list[str]:
    """Order ``modules`` so an imported (callee) module precedes its importer.

    Deterministic depth-first topological order over
    :func:`module_import_graph`; ties and import CYCLES fall back to the given
    source order (so a circular ``a <-> b`` import pair is stable, never an
    error). Unit-level call dependencies are resolved separately by the loop, so
    a module-level cycle does not block reconstruction.
    """
    raise NotImplementedError

def build_descriptor(source_root: Path, *, output_dir: Path, stash_dir: Path, name: str | None=None, modules: list[str] | None=None, test_files: list[str] | None=None, seed_files: list[str] | None=None, dependencies: list[str] | None=None, requirements_files: list[str] | None=None) -> TargetDescriptor:
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
    raise NotImplementedError