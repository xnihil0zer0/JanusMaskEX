from __future__ import annotations

def _files_overlap(a_files: list[str], b_files: list[str]) -> bool:
    """Return True if any path in ``a_files`` contends with one in ``b_files``.

    Paths are canonicalized via :func:`_normalize_path` so differently spelled
    but identical paths still collide. Two normalized paths contend when they
    are equal, or when one is a directory that contains the other.
    """
    a_norm = [_normalize_path(p) for p in a_files]
    b_norm = [_normalize_path(p) for p in b_files]
    for a_path, a_is_dir in a_norm:
        for b_path, b_is_dir in b_norm:
            if a_path == b_path:
                return True
            if a_is_dir and b_path.startswith(a_path):
                return True
            if b_is_dir and a_path.startswith(b_path):
                return True
    return False

def transitive_deps(task_id: str, all_tasks: list[dict]) -> set[str]:
    """Return the set of all task ids transitively depended on by ``task_id``.

    Performs a breadth-first walk over the task dependency graph described by
    ``all_tasks`` (a list of ``{"task_id": ..., "dependencies": [...]}`` dicts)
    and returns every task id reachable from ``task_id``, excluding
    ``task_id`` itself. Cycles terminate, dangling dependencies (ids absent
    from the list) are reported but not traversed, missing/``None``
    ``dependencies`` are treated as empty, and entries whose ``task_id`` is not
    a string are ignored entirely. The input is never mutated.
    """
    index: dict[str, list[str]] = {}
    for task in all_tasks:
        tid = task.get('task_id')
        if not isinstance(tid, str):
            continue
        deps = task.get('dependencies') or []
        index[tid] = list(deps)
    result: set[str] = set()
    visited: set[str] = {task_id}
    queue: deque[str] = deque([task_id])
    while queue:
        current = queue.popleft()
        for dep in index.get(current, []):
            if dep in visited:
                continue
            visited.add(dep)
            result.add(dep)
            if dep in index:
                queue.append(dep)
    return result

def can_run_parallel(task_a: dict, task_b: dict, all_tasks: list[dict] | None=None, *, conservative_missing_files: bool=True) -> bool:
    """Return True if ``task_a`` and ``task_b`` may be scheduled concurrently.

    Two tasks are safe to run in parallel only when BOTH hold:

    * **No ordering constraint** -- neither task depends on the other. When
      ``all_tasks`` is supplied the full dependency graph is consulted via
      :func:`transitive_deps`, so an INDIRECT (transitive) dependency in either
      direction also blocks parallelism. Without ``all_tasks`` only each task's
      own directly declared ``"dependencies"`` ids are inspected.
    * **No file contention** -- the tasks' ``"files_touched"`` lists do not
      overlap (compared via :func:`_files_overlap`, which normalises paths so
      that differently spelled but identical paths still collide).

    A task whose ``"files_touched"`` is absent (or ``None``) has an unknown file
    footprint. With ``conservative_missing_files`` true (the default) such a task
    is assumed to potentially touch anything, so the pair cannot run in parallel
    and ``False`` is returned; when false the missing footprint is treated as
    empty (no contention).
    """
    a_id = task_a.get('task_id')
    b_id = task_b.get('task_id')
    if all_tasks is not None:
        if a_id is not None and b_id is not None:
            if b_id in transitive_deps(a_id, all_tasks):
                return False
            if a_id in transitive_deps(b_id, all_tasks):
                return False
    else:
        a_deps = task_a.get('dependencies') or []
        if isinstance(a_deps, (str, bytes)):
            a_deps = [a_deps]
        b_deps = task_b.get('dependencies') or []
        if isinstance(b_deps, (str, bytes)):
            b_deps = [b_deps]
        if b_id is not None and b_id in a_deps:
            return False
        if a_id is not None and a_id in b_deps:
            return False
    a_files = task_a.get('files_touched')
    b_files = task_b.get('files_touched')
    if a_files is None or b_files is None:
        if conservative_missing_files:
            return False
    if _files_overlap(a_files or [], b_files or []):
        return False
    return True
import pathlib

def _normalize_path(p: str) -> tuple[str, bool]:
    """Canonicalize a path string into ``(canonical, is_dir)``.

    A trailing ``/`` marks a directory: every trailing slash is stripped, the
    remainder is resolved to an absolute, ``..``-free path, and a single ``/``
    is re-appended (``is_dir`` is ``True``). Otherwise the path is resolved as
    a file with no trailing slash (``is_dir`` is ``False``). The filesystem
    target need not exist.
    """
    is_dir = p.endswith('/')
    canonical = str(pathlib.Path(p.rstrip('/')).resolve())
    if is_dir:
        return (canonical + '/', True)
    return (canonical, False)
from collections import deque