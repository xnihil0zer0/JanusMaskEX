"""Minimal single-symbol submission for AST-merge into harness/orchestrator.py.

Only _path_b_outbox_fallback is replaced (merge keys by name; all other symbols in
the target survive). Adds a Path() coercion so the PTY backend's str _work_dir does
not raise TypeError on `str / 'outbox'` (the live silent-agy-fallback bug). Path,
json, ast, logger are already module-level in orchestrator.py.
"""
from __future__ import annotations
import ast
import json
from pathlib import Path


def _path_b_outbox_fallback(work_dir: Path, sub_path: Path, task_id: str) -> str | None:
    work_dir = Path(work_dir)
    outbox_path = work_dir / 'outbox' / 'submission.py'
    if not outbox_path.is_file():
        return None
    try:
        content = outbox_path.read_text()
    except (OSError, UnicodeDecodeError):
        return None
    if not content.strip():
        return None
    target_is_py = True
    try:
        state_dir = sub_path.parent.parent
        task_file = state_dir / 'tasks' / f'current_task_{task_id}.json'
        if task_file.is_file():
            with open(task_file, 'r') as _f:
                _task = json.load(_f)
            _ft = _task.get('files_touched') or []
            if _ft and (not str(_ft[0]).endswith('.py')):
                target_is_py = False
    except (OSError, json.JSONDecodeError):
        pass
    if target_is_py:
        try:
            ast.parse(content)
        except SyntaxError:
            return None
    try:
        sub_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = sub_path.with_suffix(sub_path.suffix + '.tmp')
        tmp.write_text(json.dumps({'code': content, 'task_id': task_id}))
        tmp.replace(sub_path)
    except OSError:
        logger.warning('Path-B fallback: outbox promote write failed for %s', sub_path)
    return content
