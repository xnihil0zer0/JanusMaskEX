"""Stdlib-only helper that lifts the task-staging body of
``scripts/impl_plan_to_queue.py:main()`` into an importable, side-effect-free
function so ``harness.autowork_daemon._iteration`` can stage plan tasks itself
without shelling out to the script.

The function reads a plan JSON, locates a single task entry by ``task_id``,
and writes it as a standalone task file under ``state_dir``. Behavior mirrors
``scripts/impl_plan_to_queue.py`` exactly: refuse-overwrite, indent=2 +
trailing newline, no schema validation beyond presence/uniqueness of the
matching ``task_id``.
"""
from __future__ import annotations
import json
from pathlib import Path

def stage_task(plan_path: Path, task_id: str, state_dir: Path, canonical: bool=True, *, working_dir: str | None = None) -> Path:
    """Extract a single task from ``plan_path`` and write it under ``state_dir``.

    P2/P3 hardening: before staging, evict stale blocked sidecars for this id
    (``blocked/<id>.json`` / ``<id>.retry.json`` / ``<id>.exhausted``) so a
    re-stage does not deadlock against ``_retry_blocked_tasks``. When the
    canonical output already exists with DIFFERENT content and the task is not
    yet accepted (no ``tasks/processed/<id>.json`` and no ``accepted`` /
    ``auto_commit`` row in ``impl_progress.jsonl`` for the id), overwrite it so
    plan corrections propagate; identical content stays idempotent; an already
    accepted task is still refused (``FileExistsError``).

    Args:
        plan_path: Path to a plan_hooks_*.json file containing a ``tasks`` list.
        task_id: Exact ``task_id`` to extract.
        state_dir: Root state directory; output is written under
            ``state_dir / "tasks"``.
        canonical: When True (default), write to
            ``<state_dir>/tasks/<task_id>.json`` (the path the orchestrator
            scans directly). When False, write to
            ``<state_dir>/tasks/queued/<task_id>.json`` (legacy staging
            location auto-promoted by ``scripts/impl_dispatch_once.sh``).
        working_dir: Trusted working directory injected by the caller. The
            LLM-authored ``working_dir`` (if any) is always stripped from the
            task dict before staging; when this trusted value is not None it
            replaces it.

    Returns:
        The output ``Path`` on success.

    Raises:
        FileNotFoundError: If ``plan_path`` does not exist.
        KeyError: If ``task_id`` is missing from ``plan['tasks']`` or appears
            more than once.
        FileExistsError: If the output path already exists AND the task has
            already been accepted (refuse-clobber).
    """
    plan_path = Path(plan_path)
    state_dir = Path(state_dir)
    # P2: evict stale blocked sidecars for this id (best-effort).
    _blocked_dir = state_dir / 'tasks' / 'blocked'
    for _sc in (f'{task_id}.json', f'{task_id}.retry.json', f'{task_id}.exhausted'):
        try:
            (_blocked_dir / _sc).unlink()
        except OSError:
            pass
    if not plan_path.exists():
        raise FileNotFoundError(f'plan_path does not exist: {plan_path}')
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    tasks = plan.get('tasks') or []
    matches = [t for t in tasks if t.get('task_id') == task_id]
    if not matches:
        raise KeyError(f'task_id {task_id!r} not found in {plan_path} (have: {[t.get('task_id') for t in tasks]})')
    if len(matches) > 1:
        raise KeyError(f'task_id {task_id!r} appears {len(matches)}x in {plan_path}')
    task = matches[0]
    if canonical:
        out = state_dir / 'tasks' / f'{task_id}.json'
    else:
        out = state_dir / 'tasks' / 'queued' / f'{task_id}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    task.pop('working_dir', None)
    if working_dir is not None:
        task['working_dir'] = working_dir
    content = json.dumps(task, indent=2) + '\n'
    if out.exists():
        try:
            existing = out.read_text(encoding='utf-8')
        except OSError:
            existing = None
        if existing == content:
            return out
        # P3: differing content -- overwrite only if not yet accepted.
        accepted = (state_dir / 'tasks' / 'processed' / f'{task_id}.json').exists()
        if not accepted:
            _ledger = state_dir / 'impl_progress.jsonl'
            if _ledger.exists():
                try:
                    for _line in _ledger.read_text(encoding='utf-8').splitlines():
                        _line = _line.strip()
                        if not _line:
                            continue
                        try:
                            _row = json.loads(_line)
                        except (ValueError, TypeError):
                            continue
                        if not isinstance(_row, dict):
                            continue
                        if _row.get('phase') == 'accepted' and _row.get('event') == 'auto_commit' and (_row.get('task_id') or _row.get('id')) == task_id:
                            accepted = True
                            break
                except OSError:
                    pass
        if accepted:
            raise FileExistsError(f'refuse: {out} already exists (accepted)')
    out.write_text(content, encoding='utf-8')
    return out
