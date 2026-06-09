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
LIVE_ROOTS: list[str] = ['harness/orchestrator.py', 'harness/orchestrator_worker.py', 'harness/autowork_daemon.py', 'harness/planner/cli.py', 'harness/hooks/claude_hook.py', 'harness/hooks/gemini_hook.py', 'harness/webui_control.py', 'harness/overseer.py', 'harness/services.py']

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
                text = path.read_text(encoding='utf-8', errors='ignore')
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
            text = path.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        if pattern.search(text):
            try:
                return path.relative_to(repo_root).as_posix()
            except ValueError:
                return path.as_posix()
    return ''

def check_wired(repo_root, new_module_rel: str, *, roots: Sequence[str]=LIVE_ROOTS, exclude: Iterable[str]=()) -> WireResult:
    """Decide whether ``new_module_rel`` is reachable from a live root.

    Builds the intra-project import graph via ``discover`` (never re-parsing
    imports here), then BFS-traverses forward edges from the ``roots`` present
    in the graph. ``new_module_rel`` is WIRED iff at least one of its direct
    importers (minus ``exclude``) is itself reachable from a root -- or it is
    itself a live root, or it is referenced from a config file.
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
            reason = f'{new_module_rel} is reachable from a live root via: {', '.join(live_importers)}.'
        else:
            reason = f'{new_module_rel} is itself a live entrypoint root.'
        return WireResult(wired=True, importers=live_importers, reason=reason, fix_hint='')
    stem = Path(new_module_rel).stem
    config_ref = _grep_config(repo_root, stem)
    if config_ref:
        return WireResult(wired=True, importers=[], reason=f'{new_module_rel} referenced in config (dynamic wiring): {config_ref}.', fix_hint='')
    return WireResult(wired=False, importers=[], reason=f'{new_module_rel} is an orphan: no live root reaches it through the import graph (inbound importers, if any, are themselves unreachable from a root).', fix_hint=f'Wire it in by adding an import or call of `{stem}` from a live module already reachable from one of the live roots (e.g. {', '.join(roots[:1]) or 'a live entrypoint'}).')