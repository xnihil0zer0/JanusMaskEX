"""Reachability primitive: decide whether a module is WIRED.

A module is WIRED iff it is reachable, via the intra-project import graph, from
at least one *live* entrypoint root -- NOT merely if *something* imports it. A
module imported only by another orphan is itself unwired (we traverse forward
from the roots, we never trust mere inbound degree).

This module is pure: stdlib only, plus a read of the import graph that
``harness.rebuild.discover`` already builds. There are no process spawns, no
network/model/API calls, and no un-injected subprocesses -- only stdlib and
filesystem reads.
"""
from __future__ import annotations
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence
from harness.rebuild.discover import discover_modules, module_import_graph

@dataclass
class WireResult:
    """Outcome of a wired-ness check for a single module.

    Attributes:
        wired: True iff the module is reachable from a live root (or is itself
            a live root, or is referenced from config for dynamic wiring).
        importers: The reachable direct importers of the module (minus exclude),
            sorted; empty when the module is an orphan or root.
        reason: Human-readable explanation of the verdict.
        fix_hint: Actionable hint on how to wire the module when it is unwired.
    """
    wired: bool
    importers: list[str] = field(default_factory=list)
    reason: str = ''
    fix_hint: str = ''
LIVE_ROOTS: list[str] = ['harness/orchestrator.py', 'harness/orchestrator_worker.py', 'harness/autowork_daemon.py', 'harness/planner/cli.py']

def _strip_config_comments(text: str) -> str:
    """Strip YAML/TOML ``#`` comments before module-reference scanning.

    A ``#`` at line start or preceded by whitespace begins a comment (the
    YAML/TOML comment forms); everything from it to end-of-line is dropped.
    A comment that merely *mentions* a module path is documentation, not a
    registration -- scanning raw text promoted ``harness/wire_up.py`` to a
    live root off a doc comment in ``config/autocompiler.yaml``. A ``#``
    embedded in a token (e.g. a URL fragment) is NOT whitespace-preceded
    and survives.
    """
    return re.sub('(?m)(^|\\s)#.*$', lambda m: m.group(1), text)
def discover_live_roots(repo_root) -> list[str]:
    """Reconcile the live-root seed set from ground truth.

    Returns a sorted, de-duplicated list of POSIX module rel-paths that is the
    UNION of:

      (a) the shipped ``LIVE_ROOTS`` entries that exist as files under
          ``repo_root``;
      (b) entrypoints registered by name in ``config/**`` -- both ``-m
          <dotted.module>`` tokens and literal ``*.py`` path references --
          restricted to candidates that exist in the discovered module set;
      (c) discovered non-test modules whose source carries a real
          ``if __name__ == '__main__':`` guard at statement position.

    Pure: stdlib only, plus ``discover_modules`` for the authoritative
    non-test module rel-path set. Only filesystem reads under ``repo_root``;
    never raises on a missing/unreadable file.
    """
    from harness.rebuild.discover import discover_modules
    root = Path(repo_root)
    modules, _tests, _seeds = discover_modules(root)
    module_set = set(modules)
    roots: set[str] = set()
    for r in LIVE_ROOTS:
        try:
            if (root / r).is_file():
                roots.add(r)
        except OSError:
            continue
    config_dir = root / 'config'
    if config_dir.is_dir():
        m_pattern = re.compile('-m\\s+([\\w.]+)')
        py_pattern = re.compile('([\\w./${}-]+\\.py)')
        for path in sorted(config_dir.rglob('*')):
            if not path.is_file():
                continue
            try:
                text = _strip_config_comments(path.read_text(encoding='utf-8', errors='ignore'))
            except OSError:
                continue
            for dotted in m_pattern.findall(text):
                rel = dotted.replace('.', '/') + '.py'
                if rel in module_set:
                    roots.add(rel)
            for token in py_pattern.findall(text):
                candidate = token
                best = None
                for seg in ('harness/', 'overseer/'):
                    idx = token.find(seg)
                    if idx != -1 and (best is None or idx < best):
                        best = idx
                if best is not None:
                    candidate = token[best:]
                if candidate in module_set:
                    roots.add(candidate)
    main_guard = re.compile('(?m)^[ \\t]*if[ \\t]+__name__[ \\t]*==[ \\t]*([\'\\"])__main__\\1')
    for m in modules:
        try:
            src = (root / m).read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        if main_guard.search(src):
            roots.add(m)
    return sorted(roots)
@dataclass
class SweepReport:
    """Tree-wide partition of source modules into wiredness classes.

    Each field is a sorted list of POSIX module rel-paths. ``roots`` holds the
    sorted seeded live roots used to compute reachability. A source module
    appears in exactly one of the four class lists:

      * ``wired`` -- reachable (forward, via the import graph) from a live root.
      * ``config_wired`` -- not reachable, but referenced by stem in config/**.
      * ``orphan_cluster`` -- inbound importers exist but none is reachable.
      * ``orphan`` -- no inbound importers and no config reference.
    """
    wired: list[str] = field(default_factory=list)
    config_wired: list[str] = field(default_factory=list)
    orphan_cluster: list[str] = field(default_factory=list)
    orphan: list[str] = field(default_factory=list)
    roots: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Return the four class lists keyed by class name."""
        return {'wired': self.wired, 'config_wired': self.config_wired, 'orphan_cluster': self.orphan_cluster, 'orphan': self.orphan}

    def to_markdown(self) -> str:
        """Render a deterministic markdown report of the sweep classes."""
        lines = ['# Wire-Up Sweep Report', '', 'Source-set filter: excludes _archive/**, _autowork_archive/**, samples/**, scripts/**, tests/**, venv/**.', '']
        sections = [('WIRED', self.wired), ('CONFIG_WIRED', self.config_wired), ('ORPHAN_CLUSTER', self.orphan_cluster), ('ORPHAN', self.orphan)]
        for name, members in sections:
            members = sorted(members)
            lines.append(f'## {name} ({len(members)})')
            for m in members:
                lines.append(f'- {m}')
            lines.append('')
        return '\n'.join(lines)

def sweep_modules(repo_root, *, roots) -> SweepReport:
    """Partition every source module into exactly one wiredness class.

    Builds the intra-project import graph ONCE via ``module_import_graph`` over
    the full discovered non-test module list, then BFS-reaches forward from the
    ``roots`` present in the module set. Classifies each source-set module (the
    non-test modules minus the excluded directories) in priority order:
    WIRED, then CONFIG_WIRED, then ORPHAN_CLUSTER, then ORPHAN.

    Pure: stdlib only, plus ``discover`` and ``_grep_config`` filesystem reads.
    Deterministic: identical inputs yield an identical ``SweepReport``. Writes
    no files.
    """
    root = Path(repo_root)
    modules, _tests, _seeds = discover_modules(root)
    modules = list(modules)
    module_set = set(modules)
    EXCLUDE = ('_archive/', '_autowork_archive/', 'samples/', 'scripts/', 'tests/', 'venv/')
    source = [m for m in modules if not any((m.startswith(p) for p in EXCLUDE))]
    graph = _resolved_graph(root, modules)
    importers: dict[str, set[str]] = defaultdict(set)
    for m, deps in graph.items():
        for d in deps:
            importers[d].add(m)
    seeded = sorted((r for r in roots if r in module_set))
    reachable: set[str] = set()
    queue: deque[str] = deque()
    for r in seeded:
        if r not in reachable:
            reachable.add(r)
            queue.append(r)
    while queue:
        cur = queue.popleft()
        for d in graph.get(cur, ()):
            if d not in reachable:
                reachable.add(d)
                queue.append(d)
    wired: list[str] = []
    config_wired: list[str] = []
    orphan_cluster: list[str] = []
    orphan: list[str] = []
    for m in source:
        if m in reachable:
            wired.append(m)
        elif _grep_config(root, Path(m).stem):
            config_wired.append(m)
        elif importers.get(m):
            orphan_cluster.append(m)
        else:
            orphan.append(m)
    return SweepReport(wired=sorted(wired), config_wired=sorted(config_wired), orphan_cluster=sorted(orphan_cluster), orphan=sorted(orphan), roots=seeded)
def mcp_crosscheck(report: SweepReport, mcp_query) -> list[str]:
    """Advisory MCP cross-check over a SweepReport's orphan candidates.

    For each static ORPHAN / ORPHAN_CLUSTER candidate, consult the INJECTED
    ``mcp_query`` callable -- a function taking a module rel-path str and
    returning an int count of inbound usages the MCP graph knows about
    (CALLS/IMPORTS/USAGE edges). When the MCP reports inbound usages for a
    candidate the static sweep flagged as unused, raise a human-triage
    disagreement note.

    This is ADVISORY ONLY: it never flips a verdict, never gates a build, and
    never mutates ``report`` (its four class lists are untouched). Only the
    orphan/orphan_cluster candidates are queried -- WIRED and CONFIG_WIRED
    modules are never passed to ``mcp_query``. If ``mcp_query`` raises for a
    candidate, that candidate is skipped (best-effort; the error never
    propagates) and yields no note.

    Pure: stdlib only; no process spawn, model/API/network call, or
    un-injected subprocess. The only external touch is ``mcp_query``. Writes
    no files. Deterministic: the same report and ``mcp_query`` behaviour yield
    an identical note list.
    """
    notes: list[str] = []
    for m in list(report.orphan) + list(report.orphan_cluster):
        try:
            count = mcp_query(m)
        except Exception:
            continue
        if count:
            notes.append(f'{m}: static says orphan, MCP shows {count} inbound usages -> likely dynamic wiring, do not auto-remove')
    return notes
def _resolved_graph(repo_root, modules):
    """Augmented intra-project import graph that resolves wiring forms the base
    discover graph misses: ``from PACKAGE import SUBMODULE``, dotted ``import
    a.b.c``, and imports performed by a package ``__init__`` seed. Returns a
    {node -> set(intra-project modules/seeds it imports)} dict over the non-test
    modules PLUS the seed (__init__/conftest) nodes, so reachability can flow
    through package __init__ files. No new wiring is invented -- only edges that
    already exist in the source are made visible."""
    import ast as _ast
    root = Path(repo_root)
    modules = list(modules)
    _m, _t, seeds = discover_modules(root)
    seeds = list(seeds)
    base = module_import_graph(root, modules)
    nodes = modules + seeds
    mod_by_dotted = {m[:-3].replace('/', '.'): m for m in modules}
    pkg_init = {}
    for s in seeds:
        if s.endswith('__init__.py'):
            pkg_init[s[:-len('/__init__.py')].replace('/', '.')] = s
    graph = {n: set(base.get(n, ())) for n in nodes}
    for f in nodes:
        try:
            tree = _ast.parse((root / f).read_text(encoding='utf-8', errors='ignore'))
        except (OSError, SyntaxError):
            continue
        pkg = f.rsplit('/', 1)[0].replace('/', '.') if '/' in f else ''
        deps = graph[f]
        for node in _ast.walk(tree):
            if isinstance(node, _ast.ImportFrom):
                if node.level == 0 and node.module:
                    base_m = node.module
                else:
                    parts = pkg.split('.') if pkg else []
                    if node.level > 1:
                        parts = parts[:-(node.level - 1)]
                    base_m = '.'.join([p for p in parts if p] + ([node.module] if node.module else []))
                for a in node.names:
                    c = base_m + '.' + a.name if base_m else a.name
                    if c in mod_by_dotted:
                        deps.add(mod_by_dotted[c])
                    if c in pkg_init:
                        deps.add(pkg_init[c])
                if base_m in mod_by_dotted:
                    deps.add(mod_by_dotted[base_m])
                if base_m in pkg_init:
                    deps.add(pkg_init[base_m])
            elif isinstance(node, _ast.Import):
                for a in node.names:
                    if a.name in mod_by_dotted:
                        deps.add(mod_by_dotted[a.name])
                    if a.name in pkg_init:
                        deps.add(pkg_init[a.name])
    return graph
def new_top_level_callables(parent_src: str | None, child_src: str) -> list[str]:
    """Return the SORTED names that are top-level callables in ``child_src`` but
    NOT in ``parent_src`` -- an AST diff of newly-added module-scope callables.

    A *top-level callable* on each side is one of:

      * a module-scope ``def`` / ``async def`` (``ast.FunctionDef`` /
        ``ast.AsyncFunctionDef``);
      * a module-scope assignment ``name = <lambda>`` with a single
        ``ast.Name`` target;
      * a ``def`` / ``async def`` found by recursing into module-scope ``If``
        (body + orelse), ``Try`` (body + each handler body + orelse +
        finalbody), and ``With`` (body). Those constructs do NOT introduce a
        new scope, so a ``def`` nested inside an ``If`` inside a ``Try`` is
        still module-scope and IS enumerated (mirrors the live
        ``harness/planner/blind_draft.py:_validate_plan`` def-inside-try).

    The recursion never crosses a ``def`` / ``class`` boundary, so defs nested
    inside another function or class (methods) are NOT enumerated; non-lambda
    top-level assignments (plain aliases, ``functools.partial`` bindings) are
    NOT enumerated either.

    Fail-soft and pure: an unparseable ``child_src`` yields ``[]`` (never
    raises); an empty / ``None`` / unparseable ``parent_src`` is treated as
    having no callables, so every child callable reads as new. AST-only, no
    I/O, deterministic.
    """
    import ast

    def _collect_block(stmts, names):
        for node in stmts:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(node.name)
            elif isinstance(node, ast.If):
                _collect_block(node.body, names)
                _collect_block(node.orelse, names)
            elif isinstance(node, ast.Try):
                _collect_block(node.body, names)
                for handler in node.handlers:
                    _collect_block(handler.body, names)
                _collect_block(node.orelse, names)
                _collect_block(node.finalbody, names)
            elif isinstance(node, ast.With):
                _collect_block(node.body, names)

    def _collect(src):
        if not isinstance(src, str) or not src.strip():
            return set()
        try:
            tree = ast.parse(src)
        except (SyntaxError, ValueError, TypeError):
            return set()
        names: set = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                if isinstance(node.value, ast.Lambda) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    names.add(node.targets[0].id)
            elif isinstance(node, ast.If):
                _collect_block(node.body, names)
                _collect_block(node.orelse, names)
            elif isinstance(node, ast.Try):
                _collect_block(node.body, names)
                for handler in node.handlers:
                    _collect_block(handler.body, names)
                _collect_block(node.orelse, names)
                _collect_block(node.finalbody, names)
            elif isinstance(node, ast.With):
                _collect_block(node.body, names)
        return names
    child_names = _collect(child_src)
    parent_names = _collect(parent_src)
    return sorted(child_names - parent_names)

class observe_symbol_execution:
    """Runtime observer of which WATCHED module-top-level functions actually
    execute, plus each watched call's IMMEDIATE caller source file.

    Used as a context manager. On ``__enter__`` it saves the prior
    ``sys.gettrace()`` and the prior ``threading`` trace hook, then installs its
    own callback as the SOLE tracer via both ``sys.settrace`` and
    ``threading.settrace`` -- CLOBBERING any prior tracer rather than chaining
    to it. Clobber-then-exact-restore is the only strategy that both observes
    the symbol and lets the rest of the suite's tracer (e.g. coverage.py's
    CTracer) be restored byte-for-byte afterwards.

    The trace callback, on every ``'call'`` event, marks a watched name executed
    when the called code object is module-top-level (``co_qualname`` equals the
    bare ``co_name`` on 3.11+, else the ``co_name`` fallback) and its bare name
    is in the watched set, recording that call's immediate caller filename
    (``frame.f_back.f_code.co_filename`` -- ``None`` when there is no caller
    frame). It returns the callback itself and NEVER raises, so a probe bug can
    never crash a driven entrypoint.

    Observation is NOT a wiring proof: ``executed`` reports only that the symbol
    ran during the observed window; ``executed_from_live_root`` adds sound
    provenance by additionally requiring the immediate caller to resolve into a
    live-root file. GENERAL behaviour only -- no special-casing of any path,
    symbol, fixture, or task field.
    """

    def __init__(self, qualnames) -> None:
        self._watched: set = set(qualnames)
        self._executed: set = set()
        self._callers: dict = {}
        self._prior = None
        self._prior_thread = None
        observer = self

        def _trace(frame, event, arg):
            try:
                if event == 'call':
                    code = frame.f_code
                    name = code.co_name
                    qualname = getattr(code, 'co_qualname', None)
                    if (qualname is None or qualname == name) and name in observer._watched:
                        observer._executed.add(name)
                        if name not in observer._callers:
                            back = frame.f_back
                            observer._callers[name] = back.f_code.co_filename if back is not None else None
            except Exception:
                pass
            return _trace
        self._trace = _trace

    def __enter__(self) -> 'observe_symbol_execution':
        import sys
        import threading
        self._prior = sys.gettrace()
        try:
            self._prior_thread = threading.gettrace()
        except AttributeError:
            self._prior_thread = getattr(threading, '_trace_hook', None)
        sys.settrace(self._trace)
        threading.settrace(self._trace)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        import sys
        import threading
        try:
            sys.settrace(self._prior)
        finally:
            threading.settrace(self._prior_thread)
        return False

    def executed(self, name: str) -> bool:
        """Return True iff ``name`` is a watched symbol observed to have run.

        OBSERVATION-ONLY: a True result proves the symbol executed during the
        observed window, not that it is correctly wired. An un-watched name is
        always False.
        """
        return name in self._watched and name in self._executed

    def reached_from(self, name: str) -> str | None:
        """Return the FIRST observed immediate-caller ``co_filename`` for a
        watched ``name`` (deterministic), or ``None`` when ``name`` was never
        observed or the watched call had no caller frame."""
        return self._callers.get(name)

    def executed_from_live_root(self, name: str, live_root_files) -> bool:
        """Return True iff ``name`` executed AND its first observed immediate
        caller resolves into one of ``live_root_files``.

        ``live_root_files`` is a set of POSIX rel-path seeds (e.g. the
        ``LIVE_ROOTS`` constant). Each seed is matched robustly against the
        absolute captured caller filename via realpath / normalized
        path-suffix / basename comparison, so a rel-path seed correctly resolves
        against an absolute ``co_filename``.
        """
        if name not in self._watched or name not in self._executed:
            return False
        caller = self._callers.get(name)
        if not caller:
            return False
        for seed in live_root_files:
            if self._path_matches(caller, seed):
                return True
        return False

    @property
    def reached(self) -> set:
        """The set of watched names observed to have executed."""
        return set(self._executed)

    @staticmethod
    def _path_matches(caller: str, seed: str) -> bool:
        import os
        try:
            if not caller or not seed:
                return False
            seed_norm = str(seed).replace(os.sep, '/').strip()
            while seed_norm.startswith('./'):
                seed_norm = seed_norm[2:]
            seed_norm = seed_norm.strip('/')
            if not seed_norm:
                return False
            variants: set = set()
            variants.add(str(caller).replace(os.sep, '/'))
            try:
                variants.add(os.path.realpath(caller).replace(os.sep, '/'))
            except Exception:
                pass
            try:
                variants.add(os.path.normpath(caller).replace(os.sep, '/'))
            except Exception:
                pass
            for cv in variants:
                if cv == seed_norm or cv.endswith('/' + seed_norm):
                    return True
            seed_base = seed_norm.rsplit('/', 1)[-1]
            if seed_base:
                for cv in variants:
                    if cv.rsplit('/', 1)[-1] == seed_base:
                        return True
            return False
        except Exception:
            return False
def _grep_config(repo_root: Path, stem: str) -> str:
    """Search ``repo_root/config/**`` for ``stem`` used as a MODULE reference.

    A reference counts only when ``stem`` looks like a module path / ``-m``
    target -- a ``stem.py`` file path, a dotted-path segment (``pkg.stem`` or
    ``stem.sub``), or a bare ``-m <stem>`` target -- NOT when it is merely a
    bare identifier or JSON object key (which previously produced false
    CONFIG_WIRED verdicts that masked real orphans).

    Returns the POSIX rel-path of the first config file that references the
    stem (dynamic/config-string wiring), or "" if none does.
    """
    config_dir = repo_root / 'config'
    if not config_dir.is_dir():
        return ''
    s = re.escape(stem)
    pattern = re.compile('(?<![\\w.])' + s + '\\.py\\b' + '|(?<=\\.)' + s + '\\b' + '|(?<![\\w.])' + s + '(?=\\.\\w)' + '|-m\\s+' + s + '\\b')
    for path in sorted(config_dir.rglob('*')):
        if not path.is_file():
            continue
        try:
            text = _strip_config_comments(path.read_text(encoding='utf-8', errors='ignore'))
        except OSError:
            continue
        if pattern.search(text):
            try:
                return path.relative_to(repo_root).as_posix()
            except ValueError:
                return path.as_posix()
    return ''

def symbol_reachable_from_live_root(repo_root, module_rel: str, symbol: str, *, roots: Sequence[str]=LIVE_ROOTS) -> bool:
    """Static-reachability FLOOR: is the top-level ``symbol`` defined in
    ``module_rel`` reachable, via a STATIC import/reference path, from a live
    entrypoint root? Returns a plain ``bool``.

    This is the static floor for the wire-up detonation program: SOUND in the
    no-false-orphan direction (a true zero-caller orphan MUST return ``False``)
    while it MAY under-approximate. No special-casing of any subject, slug, or
    fixture -- purely GENERAL symbol-level reachability over the real import
    graph (the symbol-level vs module-level discriminator: the host module may
    be reachable while the symbol itself is not).

    Step 1 (module reachability): build the module set with
    ``discover_modules(repo_root)`` and the augmented edge graph with
    ``_resolved_graph(repo_root, modules)`` (import resolution is NOT
    re-implemented here), then BFS forward from the roots present in the module
    set -- the identical BFS shape to ``check_wired`` -- to obtain
    ``reachable_modules``. If ``module_rel`` is not in ``reachable_modules`` the
    symbol cannot be reached, so return ``False`` immediately (short-circuit, no
    symbol scan at all).

    Step 2 (symbol reference): for each reachable module ``M'`` parsed with
    ``ast`` -- ``ast.walk`` DESCENDS into class/method bodies, REQUIRED so a
    symbol like ``_jailed_popen`` referenced only inside ``Sandbox.execute`` is
    still found -- collect every ``ast.Name.id`` and ``ast.Attribute.attr`` so
    bare-name calls and ``mod.symbol(...)`` attribute calls both count (the
    ``def``/``class`` name itself is NOT counted as a reference, so a defined-
    but-never-referenced symbol reads as an orphan). Return ``True`` iff either:

      (a) intra-module: ``M' == module_rel``, ``symbol`` is a top-level
          ``def``/``async def`` of ``module_rel``, and ``symbol`` is referenced
          somewhere in ``M'`` (module top level, a top-level def/async-def body,
          or a class method body); or
      (b) cross-module: ``M'`` carries ``from <dotted module_rel> import
          <symbol>`` at ``level == 0`` (honouring an ``as`` alias for the bound
          local name) and then references that local name anywhere in ``M'``.

    KNOWN LIMITATION: static analysis misses purely-dynamic edges: getattr/string-dispatch/registry callbacks, so a dynamically-wired symbol may be a static false-negative; acceptable because rescued by the later detonation bar; sound in the no-false-orphan direction.

    Pure and fail-soft: stdlib ``ast``/``collections`` plus the existing graph
    helpers only; unparseable or missing files under a reachable module are
    skipped (an ``OSError``/``SyntaxError`` on one file never aborts the scan or
    raises); only filesystem reads under ``repo_root`` -- no spawn, network,
    model, subprocess, or oracle execution. Deterministic over a fixed tree.
    """
    import ast
    root = Path(repo_root)
    modules, _tests, _seeds = discover_modules(root)
    modules = list(modules)
    module_set = set(modules)
    graph = _resolved_graph(root, modules)
    seeded_roots = {r for r in roots if r in module_set}
    reachable_modules: set[str] = set()
    queue: deque[str] = deque()
    for r in seeded_roots:
        if r not in reachable_modules:
            reachable_modules.add(r)
            queue.append(r)
    while queue:
        cur = queue.popleft()
        for dep in graph.get(cur, ()):
            if dep not in reachable_modules:
                reachable_modules.add(dep)
                queue.append(dep)
    if module_rel not in reachable_modules:
        return False
    dotted = module_rel[:-3] if module_rel.endswith('.py') else module_rel
    dotted = dotted.replace('/', '.')
    for mprime in sorted(reachable_modules):
        try:
            tree = ast.parse((root / mprime).read_text(encoding='utf-8', errors='ignore'))
        except (OSError, SyntaxError):
            continue
        referenced: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                referenced.add(node.id)
            elif isinstance(node, ast.Attribute):
                referenced.add(node.attr)
        if mprime == module_rel:
            top_defs = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            if symbol in top_defs and symbol in referenced:
                return True
        else:
            bound: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module == dotted):
                    for alias in node.names:
                        if alias.name == symbol:
                            bound.add(alias.asname or alias.name)
            if bound & referenced:
                return True
    return False
def check_wired(repo_root, new_module_rel: str, *, roots: Sequence[str]=LIVE_ROOTS, exclude: Iterable[str]=()) -> WireResult:
    """Decide whether ``new_module_rel`` is reachable from a live root.

    Builds the intra-project import graph via ``discover`` (never re-parsing
    imports here), then BFS-traverses forward edges from the ``roots`` present
    in the graph. ``new_module_rel`` is WIRED iff at least one of its direct
    importers (minus ``exclude``) is itself reachable from a root -- or it is
    itself a live root, or it is referenced from a config file.

    WIRE_UP_EXTERNAL_ROOTLESS: the default ``roots`` are the JM-specific
    ``LIVE_ROOTS``. For a FOREIGN / clean-room target tree none of those exist,
    so ``seeded_roots`` would be empty and every module a false-positive orphan.
    When none of the passed roots exist in the tree, the live-root seed is
    reconciled from ground truth via ``discover_live_roots(repo_root)``; and for
    a genuinely ROOTLESS toolkit (no entrypoint root at all) the reachability
    model is inapplicable, so the gate no-ops (``wired=True``) rather than
    false-positiving an orphan. SELF builds (JM ``LIVE_ROOTS`` present) never
    take this branch and stay byte-identical.
    """
    repo_root = Path(repo_root)
    modules, _tests, _seeds = discover_modules(repo_root)
    modules = list(modules)
    module_set = set(modules)
    if new_module_rel not in module_set:
        return WireResult(wired=False, importers=[], reason=f'{new_module_rel} is not in the discovered module set; it is not a non-test project module known to discover.', fix_hint=f'Ensure {new_module_rel} exists as a real (non-test, non-seed) module under the source root so discover picks it up.')
    graph = _resolved_graph(repo_root, modules)
    importers_map: dict[str, set[str]] = defaultdict(set)
    for m, deps in graph.items():
        for d in deps:
            importers_map[d].add(m)
    seeded_roots = {r for r in roots if r in module_set}
    external_reconciled = False
    if not seeded_roots:
        external_reconciled = True
        seeded_roots = {r for r in discover_live_roots(repo_root) if r in module_set}
    reachable: set[str] = set()
    queue: deque[str] = deque()
    for r in seeded_roots:
        if r not in reachable:
            reachable.add(r)
            queue.append(r)
    while queue:
        cur = queue.popleft()
        for dep in graph.get(cur, ()):
            if dep not in reachable:
                reachable.add(dep)
                queue.append(dep)
    exclude_set = set(exclude)
    direct_importers = importers_map.get(new_module_rel, set()) - exclude_set
    live_importers = sorted(direct_importers & reachable)
    is_root = new_module_rel in seeded_roots
    if live_importers or is_root:
        if live_importers:
            reason = f'{new_module_rel} is reachable from a live root via: {", ".join(live_importers)}.'
        else:
            reason = f'{new_module_rel} is itself a live entrypoint root.'
        return WireResult(wired=True, importers=live_importers, reason=reason, fix_hint='')
    stem = Path(new_module_rel).stem
    config_ref = _grep_config(repo_root, stem)
    if config_ref:
        return WireResult(wired=True, importers=[], reason=f'{new_module_rel} referenced in config (dynamic wiring): {config_ref}.', fix_hint='')
    if external_reconciled:
        return WireResult(wired=True, importers=[], reason=f'{new_module_rel}: external/rootless target -- no live entrypoint root exists in the tree to define reachability, so the wire-up reachability model is inapplicable and the gate no-ops (toolkit module accepted).', fix_hint='')
    return WireResult(wired=False, importers=[], reason=f'{new_module_rel} is an orphan: no live root reaches it through the import graph (inbound importers, if any, are themselves unreachable from a root).', fix_hint=f'Wire it in by adding an import or call of `{stem}` from a live module already reachable from one of the live roots (e.g. {", ".join(roots[:1]) or "a live entrypoint"}).')
