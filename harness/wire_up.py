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
def _grep_config(repo_root: Path, stem: str) -> str:
    """Search ``repo_root/config/**`` for ``stem`` as a whole word.

    Returns the POSIX rel-path of the first config file that references the
    stem (dynamic/config-string wiring), or "" if none does.
    """
    config_dir = repo_root / 'config'
    if not config_dir.is_dir():
        return ''
    pattern = re.compile('\\b' + re.escape(stem) + '\\b')
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
    graph = module_import_graph(repo_root, modules)
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