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
    m = re.match('\\s*([A-Za-z0-9][A-Za-z0-9._-]*)', dep)
    if not m:
        return ''
    return re.sub('[-_.]+', '-', m.group(1)).lower()

def _dedup(deps: list[str]) -> list[str]:
    """De-duplicate by PEP 503 normalized name, preserving the first-seen line."""
    seen: set[str] = set()
    out: list[str] = []
    for dep in deps:
        key = _norm_name(dep)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(dep)
    return out

def _include_target(line: str) -> str | None:
    """Return the FILE of a ``-r FILE`` / ``--requirement FILE`` line, else None."""
    m = re.match('(?:-r|--requirement)(?:\\s+|=)(.+)$', line)
    if not m:
        return None
    return m.group(1).strip().strip('"\'')

def _from_requirements(root: Path) -> tuple[list[str], list[str]]:
    """Parse ``requirements*.txt`` / ``requirements.lock`` at ``root``.

    Returns ``(deps, requirements_files)``. Comment lines and inline comments
    are stripped, blank lines dropped, ``-`` option lines skipped EXCEPT
    ``-r``/``--requirement`` includes (followed recursively, relative to
    ``root``). Each manifest actually read is recorded as a rel POSIX path.
    """
    root = root.resolve()
    manifests = sorted(root.glob('requirements*.txt'))
    lock = root / 'requirements.lock'
    if lock.is_file():
        manifests.append(lock)
    deps: list[str] = []
    req_files: list[str] = []
    seen_files: set[Path] = set()

    def parse(path: Path) -> None:
        resolved = path.resolve()
        if resolved in seen_files or not path.is_file():
            return
        seen_files.add(resolved)
        try:
            text = path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            return
        try:
            rel = resolved.relative_to(root).as_posix()
        except ValueError:
            rel = path.name
        if rel not in req_files:
            req_files.append(rel)
        for raw in text.splitlines():
            line = re.split('\\s+#', raw, maxsplit=1)[0].strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('-'):
                inc = _include_target(line)
                if inc is not None:
                    parse(root / inc)
                continue
            deps.append(line)
    for manifest in manifests:
        parse(manifest)
    return (deps, req_files)

def _from_pyproject(root: Path) -> list[str]:
    """``[project].dependencies`` + ``[tool.poetry.dependencies]`` keys (no 'python')."""
    path = root / 'pyproject.toml'
    if not path.is_file():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return []
    deps: list[str] = []
    project = data.get('project')
    if isinstance(project, dict):
        listed = project.get('dependencies')
        if isinstance(listed, list):
            deps.extend((x for x in listed if isinstance(x, str)))
    tool = data.get('tool')
    if isinstance(tool, dict):
        poetry = tool.get('poetry')
        if isinstance(poetry, dict):
            poetry_deps = poetry.get('dependencies')
            if isinstance(poetry_deps, dict):
                deps.extend((k for k in poetry_deps if k != 'python'))
    return deps

def _from_setup_cfg(root: Path) -> list[str]:
    """``[options] install_requires`` (one dependency per line)."""
    path = root / 'setup.cfg'
    if not path.is_file():
        return []
    parser = configparser.ConfigParser()
    try:
        parser.read_string(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, configparser.Error):
        return []
    if not parser.has_option('options', 'install_requires'):
        return []
    raw = parser.get('options', 'install_requires')
    deps: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        deps.append(stripped)
    return deps

def _from_setup_py(root: Path) -> list[str]:
    """Best-effort: a literal ``install_requires=[...]`` string list (AST)."""
    path = root / 'setup.py'
    if not path.is_file():
        return []
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return []
    for node in ast.walk(tree):
        value: ast.expr | None = None
        if isinstance(node, ast.keyword) and node.arg == 'install_requires':
            value = node.value
        elif isinstance(node, ast.Assign) and any((isinstance(t, ast.Name) and t.id == 'install_requires' for t in node.targets)):
            value = node.value
        if isinstance(value, ast.List):
            out = [el.value for el in value.elts if isinstance(el, ast.Constant) and isinstance(el.value, str)]
            if out:
                return out
    return []

def _project_py_files(root: Path) -> list[Path]:
    """Rel paths of the project's own ``.py`` files (skipping vendor/build dirs)."""
    out: list[Path] = []
    for path in sorted(root.rglob('*.py')):
        rel = path.relative_to(root)
        if any((part in _SKIP_DIRS or (part.startswith('.') and part not in ('.', '..')) for part in rel.parts[:-1])):
            continue
        out.append(rel)
    return out

def _intra_project_names(root: Path, py_files: list[Path]) -> set[str]:
    """Top-level package/module names owned by the project (+ ``source_root.name``)."""
    intra = {root.name}
    for rel in py_files:
        parts = rel.parts
        if len(parts) == 1:
            stem = parts[0][:-3] if parts[0].endswith('.py') else parts[0]
            intra.add(stem)
        else:
            intra.add(parts[0])
    return intra

def _from_ast(root: Path) -> list[str]:
    """Fallback: external top-level import names across the project's modules.

    Top-level (module-body) imports across every project ``.py`` file, minus
    the stdlib (``sys.stdlib_module_names``) and the project's own top-level
    package/module names. Relative imports are intra-project and ignored.
    """
    root = root.resolve()
    py_files = _project_py_files(root)
    intra = _intra_project_names(root, py_files)
    stdlib = sys.stdlib_module_names
    found: list[str] = []
    seen: set[str] = set()

    def consider(top: str) -> None:
        if top and top not in stdlib and (top not in intra) and (top not in seen):
            seen.add(top)
            found.append(top)
    for rel in py_files:
        try:
            tree = ast.parse((root / rel).read_text(encoding='utf-8'))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    consider(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                if node.module:
                    consider(node.module.split('.')[0])
    return found

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
    root = Path(source_root)
    req_deps, req_files = _from_requirements(root)
    if req_deps:
        return (_dedup(req_deps), req_files)
    for extractor in (_from_pyproject, _from_setup_cfg, _from_setup_py):
        deps = extractor(root)
        if deps:
            return (_dedup(deps), req_files)
    return (_dedup(_from_ast(root)), req_files)

def _references(node: ast.AST, names: set[str]) -> bool:
    """True iff ``node``'s subtree references any name in ``names``.

    A bare ``ast.Name`` use counts; an attribute access ``pkg.attr`` is caught
    via the ``ast.Name`` at the root of the attribute chain, which ``ast.walk``
    visits directly.
    """
    return any((isinstance(sub, ast.Name) and sub.id in names for sub in ast.walk(node)))

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
    if not external_modules:
        return set()
    try:
        tree = ast.parse(module_source)
    except SyntaxError:
        return set()
    ext = set(external_modules)
    bound: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split('.')[0]
                if top in ext:
                    bound.add(alias.asname or top)
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue
            if node.module.split('.')[0] in ext:
                for alias in node.names:
                    bound.add(alias.asname or alias.name)

    def _has_local_external_import(unit: ast.AST) -> bool:
        """True iff ``unit``'s body has a function-local external import."""
        for sub in ast.walk(unit):
            if isinstance(sub, ast.Import):
                for alias in sub.names:
                    if alias.name.split('.')[0] in ext:
                        return True
            elif isinstance(sub, ast.ImportFrom):
                if sub.level or not sub.module:
                    continue
                if sub.module.split('.')[0] in ext:
                    return True
        return False
    units: set[str] = set()

    def _consider(unit: ast.AST) -> None:
        if bound and _references(unit, bound) or _has_local_external_import(unit):
            units.add(unit.name)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _consider(node)
        elif isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    _consider(member)
    return units

def module_has_top_level_external_import(module_source: str, external_modules) -> bool:
    """True iff the module's TOP LEVEL imports an external package.

    Scans only ``ast.parse(module_source).body`` -- never descending into any
    function or class body -- for an ``import pkg`` / ``from pkg import ...``
    whose top-level module name is in ``external_modules``. Relative imports
    (``node.level``) are skipped. Returns False when ``external_modules`` is
    falsy or the source is unparseable.
    """
    if not external_modules:
        return False
    try:
        tree = ast.parse(module_source)
    except SyntaxError:
        return False
    ext = set(external_modules)
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split('.')[0] in ext:
                    return True
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue
            if node.module.split('.')[0] in ext:
                return True
    return False