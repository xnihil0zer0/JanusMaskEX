from __future__ import annotations

def _files_overlap(a_files: list[str], b_files: list[str]) -> bool:
    raise NotImplementedError

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
    raise NotImplementedError
import pathlib

def _normalize_path(p: str) -> tuple[str, bool]:
    raise NotImplementedError
from collections import deque