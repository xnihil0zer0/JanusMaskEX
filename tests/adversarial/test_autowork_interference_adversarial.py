"""Adversarial tests for harness.autowork_daemon parallelism gate (AW7b).

Each test spawns the daemon as a subprocess with --once --dry-run against
an isolated tmp state directory, then parses the final non-empty JSON
line from stdout and asserts on the daemon's dispatch decision.

These tests confirm that the daemon correctly suppresses concurrent
dispatch when (a) two tasks share at least one entry in
``files_touched`` and (b) one task has missing/empty ``files_touched``
under the default ``conservative_missing_files=True`` policy, which
turns such a task into a global lock against every other candidate.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

def _write_task(tasks_dir: Path, task_id: str, files_touched, dependencies=None, priority: str='medium') -> Path:
    """Write a task json file in the schema collect_dispatchable_tasks expects.

    ``files_touched=None`` means the key is omitted entirely; an empty
    list writes ``files_touched: []``. Returns the path that was written
    so callers can adjust mtime for tie-breaking.
    """
    tasks_dir.mkdir(parents=True, exist_ok=True)
    data: dict = {'task_id': task_id, 'dependencies': dependencies or [], 'priority': priority}
    if files_touched is not None:
        data['files_touched'] = list(files_touched)
    path = tasks_dir / f'{task_id}.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    return path

def _run_daemon(state_dir: Path, cwd: Path, config: Path | None=None) -> dict:
    cmd = [sys.executable, '-m', 'harness.autowork_daemon', '--state-dir', str(state_dir), '--once', '--dry-run']
    if config is not None:
        cmd.extend(['--config', str(config)])
    env = os.environ.copy()
    env['PYTHONPATH'] = str(REPO_ROOT) + os.pathsep + env.get('PYTHONPATH', '')
    proc = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f'daemon exited rc={proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}'
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f'daemon emitted no stdout lines; stderr={proc.stderr!r}'
    return json.loads(lines[-1])

def test_two_overlapping_tasks_only_one_in_would_launch(tmp_path):
    """Two tasks sharing a file -> only one of them is admitted.

    Both ``aw7b_overlap_alpha`` and ``aw7b_overlap_beta`` list
    ``shared.py`` in ``files_touched``. Under the daemon's parallelism
    gate, at most one of them may appear in ``would_launch``; the other
    is dropped due to in-iteration conflict.
    """
    state_dir = tmp_path / 'state'
    tasks_dir = state_dir / 'tasks'
    _write_task(tasks_dir, 'aw7b_overlap_alpha', ['shared.py', 'alpha_only.py'], priority='high')
    _write_task(tasks_dir, 'aw7b_overlap_beta', ['shared.py', 'beta_only.py'], priority='medium')
    result = _run_daemon(state_dir, cwd=tmp_path)
    would_launch = result.get('would_launch') or []
    overlapping = [tid for tid in ('aw7b_overlap_alpha', 'aw7b_overlap_beta') if tid in would_launch]
    assert len(overlapping) == 1, f'expected exactly one of the two overlapping tasks in would_launch; got {overlapping!r} (full result={result!r})'
    assert 'aw7b_overlap_alpha' in would_launch, f'higher-priority task alpha should be admitted; would_launch={would_launch!r}'
    assert 'aw7b_overlap_beta' not in would_launch, f'lower-priority overlapping task beta should be suppressed; would_launch={would_launch!r}'

def test_missing_files_touched_blocks_concurrency(tmp_path):
    """A task with missing/empty files_touched acts as a global lock.

    Task A omits ``files_touched`` entirely (or sets it to []). Task B
    lists an unrelated file. Because the daemon delegates to
    ``can_run_parallel(..., conservative_missing_files=True)``, A's
    missing files_touched conflicts with every other candidate. At most
    one of {A, B} may be admitted in the same iteration.
    """
    state_dir = tmp_path / 'state'
    tasks_dir = state_dir / 'tasks'
    _write_task(tasks_dir, 'aw7b_missing_a', None, priority='medium')
    _write_task(tasks_dir, 'aw7b_missing_b', ['unrelated.py'], priority='medium')
    result = _run_daemon(state_dir, cwd=tmp_path)
    would_launch = result.get('would_launch') or []
    admitted = [tid for tid in ('aw7b_missing_a', 'aw7b_missing_b') if tid in would_launch]
    assert len(admitted) <= 1, f'task with missing files_touched must act as a global lock under conservative_missing_files=True; both tasks were admitted: {admitted!r} (full result={result!r})'
    assert len(admitted) == 1, f'expected exactly one of A or B to be admitted (the other gated by missing-files conflict); got {admitted!r} (full result={result!r})'