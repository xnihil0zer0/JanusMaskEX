from __future__ import annotations

def _files_overlap(a_files: list[str], b_files: list[str]) -> bool:
    a_norm = [_normalize_path(p) for p in a_files]
    b_norm = [_normalize_path(p) for p in b_files]
    for ai, ai_is_dir in a_norm:
        for bj, bj_is_dir in b_norm:
            if ai == bj:
                return True
            if ai_is_dir and bj.startswith(ai):
                return True
            if bj_is_dir and ai.startswith(bj):
                return True
    return False

def transitive_deps(task_id: str, all_tasks: list[dict]) -> set[str]:
    idx = {t['task_id']: t for t in all_tasks if isinstance(t.get('task_id'), str)}
    if task_id not in idx:
        return set()
    visited: set[str] = {task_id}
    result: set[str] = set()
    queue: list[str] = list(idx[task_id].get('dependencies') or [])
    while queue:
        dep = queue.pop(0)
        if dep in visited:
            continue
        visited.add(dep)
        result.add(dep)
        if dep in idx:
            for next_dep in idx[dep].get('dependencies') or []:
                if next_dep not in visited:
                    queue.append(next_dep)
    return result

def can_run_parallel(task_a: dict, task_b: dict, all_tasks: list[dict] | None=None, *, conservative_missing_files: bool=True) -> bool:
    if task_a.get('task_id') == task_b.get('task_id'):
        return False
    a_files = task_a.get('files_touched')
    b_files = task_b.get('files_touched')
    if conservative_missing_files:
        if not isinstance(a_files, list) or not a_files or (not isinstance(b_files, list)) or (not b_files):
            return False
    if isinstance(a_files, list) and isinstance(b_files, list):
        if _files_overlap(a_files, b_files):
            return False
    if all_tasks is not None:
        a_id = task_a.get('task_id')
        b_id = task_b.get('task_id')
        if a_id in transitive_deps(b_id, all_tasks):
            return False
        if b_id in transitive_deps(a_id, all_tasks):
            return False
    return True
import pathlib

def _normalize_path(p: str) -> tuple[str, bool]:
    is_dir = p.endswith('/')
    stripped = p.rstrip('/') if is_dir else p
    canonical = str(pathlib.Path(stripped).resolve())
    return (canonical + '/', True) if is_dir else (canonical, False)