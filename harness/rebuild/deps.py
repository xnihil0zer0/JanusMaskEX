"""DEPS: discover a project's EXTERNAL dependencies + the units that use them.

The clean-room rebuild engine needs to reconstruct a project in an
environment-faithful way: a unit that imports a 3rd-party package can't be
rebuilt BLIND against the merged==original oracle (the dep is unavailable /
nondeterministic), so it must be routed to the oracle-skip + fuzzer-bypass
path. Two responsibilities live here:

  * :func:`discover_dependencies` -- extract the project's declared external
    deps (and the manifest files they came from), trying requirements files,
    ``pyproject.toml``, ``setup.cfg``, ``setup.py`` in that order, with a
    last-resort AST import scan. The FIRST source that yields a dependency
    wins; sources are never merged.
  * :func:`external_units` -- given one module's source and the set of known
    external top-level package names, return the names of the functions /
    methods whose body references a name bound from one of those deps.

Pure stdlib only (``ast`` / ``re`` / ``sys`` / ``configparser`` / ``tomllib``
/ ``pathlib``); no filesystem access outside ``source_root`` and no
home-directory lookups (clone-portable).
"""
from __future__ import annotations
import ast
import configparser
import re
import sys
import tomllib
from pathlib import Path
_SKIP_DIRS = {'__pycache__', '.git', '.hg', 'state', 'build', 'dist', '.eggs', 'node_modules', '.tox', '.venv', 'venv', '.mypy_cache', '.pytest_cache'}

def _norm_name(dep: str) -> str:
    """PEP 503 normalized project name of a requirement string (or '').

    Reads the leading name token (stopping at the first version operator,
    extras bracket, marker, or URL ``@``), then lowercases and collapses every
    run of ``-`` / ``_`` / ``.`` to a single ``-``.
    """
    match = re.match('\\s*([A-Za-z0-9][A-Za-z0-9._-]*)', dep)
    if not match:
        return ''
    return re.sub('[-_.]+', '-', match.group(1)).lower()

def _dedup(deps: list[str]) -> list[str]:
    """De-duplicate by PEP 503 normalized name, preserving the first-seen line."""
    seen: set[str] = set()
    result: list[str] = []
    for dep in deps:
        key = _norm_name(dep)
        if key in seen:
            continue
        seen.add(key)
        result.append(dep)
    return result

def _include_target(line: str) -> str | None:
    """Return the FILE of a ``-r FILE`` / ``--requirement FILE`` line, else None."""
    match = re.match('\\s*(?:-r|--requirement)(?:\\s+|\\s*=\\s*)(.+)', line)
    if not match:
        return None
    return match.group(1).strip().strip('\'"') or None

def _from_requirements(root: Path) -> tuple[list[str], list[str]]:
    """Parse ``requirements*.txt`` / ``requirements.lock`` at ``root``.

    Returns ``(deps, requirements_files)``. Comment lines and inline comments
    are stripped, blank lines dropped, ``-`` option lines skipped EXCEPT
    ``-r``/``--requirement`` includes (followed recursively, relative to
    ``root``). Each manifest actually read is recorded as a rel POSIX path.
    """
    deps: list[str] = []
    files: list[str] = []
    seen: set[Path] = set()

    def _read(path: Path) -> None:
        resolved = path.resolve()
        if resolved in seen or not path.is_file():
            return
        seen.add(resolved)
        files.append(path.relative_to(root).as_posix())
        for raw in path.read_text(encoding='utf-8', errors='replace').splitlines():
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            line = re.split('\\s+#', line, maxsplit=1)[0].strip()
            if not line:
                continue
            if line.startswith('-'):
                target = _include_target(line)
                if target is not None:
                    _read(root / target)
                continue
            deps.append(line)
    manifests = sorted(root.glob('requirements*.txt'))
    lock = root / 'requirements.lock'
    if lock.is_file():
        manifests.append(lock)
    for manifest in manifests:
        _read(manifest)
    return (deps, files)

def _from_pyproject(root: Path) -> list[str]:
    """``[project].dependencies`` + ``[tool.poetry.dependencies]`` keys (no 'python')."""
    raise NotImplementedError

def _from_setup_cfg(root: Path) -> list[str]:
    """``[options] install_requires`` (one dependency per line)."""
    raise NotImplementedError

def _from_setup_py(root: Path) -> list[str]:
    """Best-effort: a literal ``install_requires=[...]`` string list (AST)."""
    raise NotImplementedError

def _project_py_files(root: Path) -> list[Path]:
    """Rel paths of the project's own ``.py`` files (skipping vendor/build dirs)."""
    raise NotImplementedError

def _intra_project_names(root: Path, py_files: list[Path]) -> set[str]:
    """Top-level package/module names owned by the project (+ ``source_root.name``)."""
    raise NotImplementedError

def _from_ast(root: Path) -> list[str]:
    """Fallback: external top-level import names across the project's modules.

    Top-level (module-body) imports across every project ``.py`` file, minus
    the stdlib (``sys.stdlib_module_names``) and the project's own top-level
    package/module names. Relative imports are intra-project and ignored.
    """
    raise NotImplementedError

def discover_dependencies(source_root) -> tuple[list[str], list[str]]:
    """Discover ``(dependencies, requirements_files)`` for ``source_root``.

    Dependency sources are tried in order -- requirements manifests,
    ``pyproject.toml``, ``setup.cfg``, ``setup.py``, then an AST import scan --
    and the FIRST that yields any dependency wins (sources are not merged).
    Dependencies are de-duplicated by PEP 503 normalized name (the first-seen
    line, with its version specifier, is kept). ``requirements_files`` always
    lists every requirements manifest found as a rel POSIX path, regardless of
    which source supplied the dependencies.
    """
    raise NotImplementedError

def _references(node: ast.AST, names: set[str]) -> bool:
    """True iff ``node``'s subtree references any name in ``names``.

    A bare ``ast.Name`` use counts; an attribute access ``pkg.attr`` is caught
    via the ``ast.Name`` at the root of the attribute chain, which ``ast.walk``
    visits directly.
    """
    raise NotImplementedError

def external_units(module_source: str, external_modules) -> set[str]:
    """Names of top-level functions/methods that depend on an external package.

    A unit (top-level ``def``/``async def`` or class method) is included when
    EITHER:

    (a) it references a name bound by a MODULE-TOP-LEVEL import of an external
        module -- ``import pkg`` binds ``pkg`` (or its asname); ``from pkg
        import a, b as c`` binds ``a`` and ``c`` -- detected via the preserved
        ``_references`` helper, OR
    (b) its OWN body contains a FUNCTION-LOCAL import of an external module
        (e.g. ``def f(): import inflection`` or ``def f(): from inflection
        import pluralize``).

    ``external_modules`` is the set of known external top-level package names
    (e.g. ``{'inflection'}``). Returns an empty set when ``external_modules``
    is falsy or the source is unparseable. Names are returned as their short
    name (``node.name``).
    """
    raise NotImplementedError

def module_has_top_level_external_import(module_source: str, external_modules) -> bool:
    """True iff the module's TOP LEVEL imports an external package.

    Scans only ``ast.parse(module_source).body`` -- never descending into any
    function or class body -- for an ``import pkg`` / ``from pkg import ...``
    whose top-level module name is in ``external_modules``. Relative imports
    (``node.level``) are skipped. Returns False when ``external_modules`` is
    falsy or the source is unparseable.
    """
    raise NotImplementedError
'Reconstructed leaf unit: harness.rebuild.deps._include_target.'
'Reconstructed leaf unit: harness.rebuild.deps._from_requirements.'