from __future__ import annotations

def _files_overlap(a_files: list[str], b_files: list[str]) -> bool:
    raise NotImplementedError

def transitive_deps(task_id: str, all_tasks: list[dict]) -> set[str]:
    raise NotImplementedError

def can_run_parallel(task_a: dict, task_b: dict, all_tasks: list[dict] | None=None, *, conservative_missing_files: bool=True) -> bool:
    raise NotImplementedError
import pathlib

def _normalize_path(p: str) -> tuple[str, bool]:
    raise NotImplementedError