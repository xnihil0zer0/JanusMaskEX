"""End-to-end tests for harness.autowork_daemon (AW7a).

Each test spawns the daemon as a subprocess with --once --dry-run against
an isolated tmp state directory, then parses the final non-empty JSON
line from stdout and asserts on the daemon's dispatch decision.

The daemon's --dry-run output schema (per AW4a) is a JSON object with
at least: would_launch (list[str]), free_slots (int), cap (int),
paused (bool).
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parent.parent

def _write_task(tasks_dir: Path, task_id: str, files_touched: list, dependencies: list | None=None, priority: str='medium') -> None:
    tasks_dir.mkdir(parents=True, exist_ok=True)
    data = {'task_id': task_id, 'files_touched': files_touched, 'dependencies': dependencies or [], 'priority': priority}
    (tasks_dir / f'{task_id}.json').write_text(json.dumps(data), encoding='utf-8')

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

def test_two_disjoint_tasks_both_in_would_launch(tmp_path):
    state_dir = tmp_path / 'state'
    tasks_dir = state_dir / 'tasks'
    _write_task(tasks_dir, 'aw7a_disjoint_alpha', ['foo.py'])
    _write_task(tasks_dir, 'aw7a_disjoint_beta', ['bar.py'])
    result = _run_daemon(state_dir, cwd=tmp_path)
    would_launch = result.get('would_launch') or []
    assert 'aw7a_disjoint_alpha' in would_launch, f'alpha missing from would_launch: {result!r}'
    assert 'aw7a_disjoint_beta' in would_launch, f'beta missing from would_launch: {result!r}'

def test_dependency_gated_task_not_in_would_launch(tmp_path):
    state_dir = tmp_path / 'state'
    tasks_dir = state_dir / 'tasks'
    _write_task(tasks_dir, 'aw7a_dep_a', ['depA.py'])
    _write_task(tasks_dir, 'aw7a_dep_b', ['depB.py'], dependencies=['aw7a_dep_a'])
    result = _run_daemon(state_dir, cwd=tmp_path)
    would_launch = result.get('would_launch') or []
    assert 'aw7a_dep_a' in would_launch, f'A (no deps) missing from would_launch: {result!r}'
    assert 'aw7a_dep_b' not in would_launch, f'B should be dep-gated but appeared in would_launch: {result!r}'

def test_cap_enforcement_limits_launches(tmp_path):
    state_dir = tmp_path / 'state'
    tasks_dir = state_dir / 'tasks'
    for i in range(6):
        _write_task(tasks_dir, f'aw7a_cap_{i}', [f'cap_file_{i}.py'])
    config_dir = tmp_path / 'harness'
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / 'config.yaml'
    config_path.write_text('autowork:\n  parallel_cap: 4\n', encoding='utf-8')
    result = _run_daemon(state_dir, cwd=tmp_path, config=config_path)
    would_launch = result.get('would_launch') or []
    assert len(would_launch) == 4, f'expected exactly 4 launches under cap=4; got {len(would_launch)}: {result!r}'