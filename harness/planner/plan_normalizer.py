"""Deterministic backstop normalizer for auto-planned leaf plans.

This module exposes a single pure, deterministic function
:func:`normalize_plan` that auto-corrects a merged (or single-agent) leaf
plan so the daemon's auto-planned child plans are executable with zero
operator vetting.  It performs two corrections:

1. **Dedupe oracles** -- collapses duplicate ``test_authoring`` tasks that
   share the same ``mutation_target`` down to a single surviving oracle,
   rewiring every dependency that referenced a dropped task.
2. **Enforce module-first ordering** -- ensures each surviving oracle
   depends on the impl task that creates its module (instead of the
   inverted oracle-first ordering), while keeping the dependency graph
   acyclic.

``normalize_plan`` is pure (operates on a deep copy, performs no I/O),
idempotent, and a strict no-op for already-correct plans.  It only ever
touches the ``dependencies`` of affected tasks and removes duplicate
oracle tasks; every other task field is preserved verbatim.
"""
from __future__ import annotations
import copy
from typing import Any, Dict, List, Optional, Set

def _module_path(mutation_target: str) -> str:
    """Return the module file path for a dotted ``mutation_target``."""
    return mutation_target.replace('.', '/') + '.py'

def _task_id(task: Dict[str, Any]) -> str:
    """Return a task's id as a string (empty string when absent)."""
    tid = task.get('task_id')
    return tid if isinstance(tid, str) else '' if tid is None else str(tid)

def _files_touched(task: Dict[str, Any]) -> List[str]:
    files = task.get('files_touched')
    return list(files) if isinstance(files, list) else []

def _dependencies(task: Dict[str, Any]) -> List[str]:
    deps = task.get('dependencies')
    return list(deps) if isinstance(deps, list) else []

def _mutation_target(task: Dict[str, Any]) -> str:
    target = task.get('mutation_target')
    return target if isinstance(target, str) else ''

def _is_test_authoring(task: Dict[str, Any]) -> bool:
    return task.get('meta_task_type') == 'test_authoring'

def _impl_for_module(tasks: List[Dict[str, Any]], module_path: str) -> Optional[Dict[str, Any]]:
    """Find the impl task that creates ``module_path``.

    A candidate is any non-``test_authoring`` task whose ``files_touched``
    contains the module file path.  When several qualify, the first by
    ``task_id`` is chosen so the result is stable across reordered inputs.
    """
    candidates = [t for t in tasks if isinstance(t, dict) and (not _is_test_authoring(t)) and (module_path in _files_touched(t))]
    if not candidates:
        return None
    return min(candidates, key=_task_id)

def _build_graph(tasks: List[Dict[str, Any]]) -> Dict[str, Set[str]]:
    """Build a ``task_id -> set(dependency task_ids)`` adjacency map."""
    ids = {_task_id(t) for t in tasks if isinstance(t, dict)}
    graph: Dict[str, Set[str]] = {}
    for t in tasks:
        if not isinstance(t, dict):
            continue
        tid = _task_id(t)
        graph[tid] = {d for d in _dependencies(t) if d in ids}
    return graph

def _reaches(graph: Dict[str, Set[str]], start: str, target: str) -> bool:
    """Return True if ``target`` is reachable from ``start`` in ``graph``."""
    stack = [start]
    seen: Set[str] = set()
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(graph.get(node, ()))
    return False

def _dedupe_oracles(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse duplicate oracles sharing a mutation_target.

    Returns the surviving task list with every dependency that referenced a
    dropped task rewired to the kept task_id (de-duplicated, no dangling
    references introduced).
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for t in tasks:
        if not isinstance(t, dict) or not _is_test_authoring(t):
            continue
        target = _mutation_target(t)
        if not target:
            continue
        groups.setdefault(target, []).append(t)
    drop_map: Dict[str, str] = {}
    for target, group in groups.items():
        if len(group) <= 1:
            continue
        impl = _impl_for_module(tasks, _module_path(target))
        kept: Optional[Dict[str, Any]] = None
        if impl is not None:
            vc = impl.get('verification_command')
            if isinstance(vc, str) and vc:
                referenced = [o for o in group if any((f and f in vc for f in _files_touched(o)))]
                if referenced:
                    kept = min(referenced, key=_task_id)
        if kept is None:
            kept = min(group, key=_task_id)
        kept_id = _task_id(kept)
        for o in group:
            if o is kept:
                continue
            drop_map[_task_id(o)] = kept_id
    if not drop_map:
        return tasks
    survivors = [t for t in tasks if not (isinstance(t, dict) and _task_id(t) in drop_map)]
    for t in survivors:
        if not isinstance(t, dict):
            continue
        deps = t.get('dependencies')
        if not isinstance(deps, list):
            continue
        if not any((d in drop_map for d in deps)):
            continue
        own_id = _task_id(t)
        rewritten: List[str] = []
        for d in deps:
            new_d = drop_map.get(d, d)
            if new_d == own_id:
                continue
            if new_d not in rewritten:
                rewritten.append(new_d)
        t['dependencies'] = rewritten
    return survivors

def _enforce_module_first(tasks: List[Dict[str, Any]]) -> None:
    """Flip oracle-first inversions to module-first, keeping graph acyclic."""
    oracles = sorted((t for t in tasks if isinstance(t, dict) and _is_test_authoring(t) and _mutation_target(t)), key=_task_id)
    for oracle in oracles:
        target = _mutation_target(oracle)
        impl = _impl_for_module(tasks, _module_path(target))
        if impl is None:
            continue
        oid = _task_id(oracle)
        iid = _task_id(impl)
        if not oid or not iid or oid == iid:
            continue
        oracle_deps = oracle.get('dependencies')
        if not isinstance(oracle_deps, list):
            oracle_deps = []
            oracle['dependencies'] = oracle_deps
        if iid not in oracle_deps:
            oracle_deps.append(iid)
        impl_deps = impl.get('dependencies')
        if isinstance(impl_deps, list) and oid in impl_deps:
            impl['dependencies'] = [d for d in impl_deps if d != oid]
        while True:
            graph = _build_graph(tasks)
            if not _reaches(graph, iid, oid):
                break
            current = impl.get('dependencies')
            if not isinstance(current, list) or not current:
                break
            removed = False
            for d in sorted(current):
                if d == oid or _reaches(graph, d, oid):
                    impl['dependencies'] = [x for x in current if x != d]
                    removed = True
                    break
            if not removed:
                break

def _sanitize_impl_verification_commands(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Rewrite impl verification_commands that reference a sibling oracle's tests.

    ``ORACLE_FILES`` is the union of ``files_touched`` across every
    ``test_authoring`` task.  Each non-``test_authoring`` task whose
    ``verification_command`` is a non-empty string naming any oracle file is
    rewritten to a smoke import (``python -c "import <m1>, <m2>"``) of that
    task's own importable modules -- its ``files_touched`` entries ending in
    ``.py``, not under ``tests/`` and not themselves oracle files, with
    slashes turned into dots and the trailing ``.py`` dropped, in stable
    ``files_touched`` order.  When the task has no importable target the oracle
    tokens are stripped from the command while the rest is preserved; if
    nothing meaningful would remain the command is left unchanged (never a
    bare ``pytest``).

    The pass is pure (operates on a deep copy, no I/O), idempotent, and a
    strict no-op when no impl command references an oracle file.
    """
    import os
    if not isinstance(plan, dict):
        return plan
    result = copy.deepcopy(plan)
    tasks = result.get('tasks')
    if not isinstance(tasks, list):
        return result
    oracle_files: Set[str] = set()
    for t in tasks:
        if isinstance(t, dict) and _is_test_authoring(t):
            for f in _files_touched(t):
                if isinstance(f, str) and f:
                    oracle_files.add(f)
    if not oracle_files:
        return result
    boilerplate = {'python', 'python3', 'pytest'}
    for t in tasks:
        if not isinstance(t, dict) or _is_test_authoring(t):
            continue
        vcmd = t.get('verification_command')
        if not isinstance(vcmd, str) or not vcmd:
            continue
        if not any((of in vcmd for of in oracle_files)):
            continue
        modules: List[str] = []
        for f in _files_touched(t):
            if not isinstance(f, str) or not f.endswith('.py'):
                continue
            if f.startswith('tests/') or '/tests/' in f or '\\tests\\' in f:
                continue
            if f in oracle_files:
                continue
            mod = f[:-len('.py')].replace(os.sep, '.').replace('/', '.')
            if mod and mod not in modules:
                modules.append(mod)
        if modules:
            t['verification_command'] = 'python -c "import ' + ', '.join(modules) + '"'
            continue
        tokens = vcmd.split()
        kept = [tok for tok in tokens if tok not in oracle_files]
        meaningful = [tok for tok in kept if tok not in boilerplate and (not tok.startswith('-'))]
        if meaningful:
            t['verification_command'] = ' '.join(kept)
    return result
def normalize_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Auto-correct a leaf plan: dedupe oracles + enforce module-first order.

    The function is pure: it deep-copies ``plan`` and never mutates the
    input.  It is idempotent and a strict no-op for already-correct plans,
    preserving every top-level key and every task field it does not
    explicitly touch.
    """
    normalized = copy.deepcopy(plan)
    if not isinstance(normalized, dict):
        return normalized
    tasks = normalized.get('tasks')
    if not isinstance(tasks, list):
        return normalized
    tasks = _dedupe_oracles(tasks)
    normalized['tasks'] = tasks
    _enforce_module_first(tasks)
    normalized = _sanitize_impl_verification_commands(normalized)
    return normalized