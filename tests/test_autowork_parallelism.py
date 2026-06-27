from __future__ import annotations
from harness.autowork_parallelism import can_run_parallel
from harness.autowork_parallelism import transitive_deps

def test_disjoint_files_returns_true():
    a = {'task_id': 'A', 'files_touched': ['foo.py']}
    b = {'task_id': 'B', 'files_touched': ['bar.py']}
    assert can_run_parallel(a, b) is True

def test_overlapping_files_returns_false():
    a = {'task_id': 'A', 'files_touched': ['foo.py', 'shared.py']}
    b = {'task_id': 'B', 'files_touched': ['shared.py']}
    assert can_run_parallel(a, b) is False

def test_dep_edge_returns_false():
    a = {'task_id': 'A', 'files_touched': ['a.py'], 'dependencies': ['B']}
    b = {'task_id': 'B', 'files_touched': ['b.py'], 'dependencies': []}
    all_tasks = [a, b]
    assert can_run_parallel(a, b, all_tasks=all_tasks) is False

def test_missing_files_touched_returns_false_when_conservative():
    a = {'task_id': 'A', 'files_touched': []}
    b = {'task_id': 'B', 'files_touched': ['b.py']}
    assert can_run_parallel(a, b) is False

def test_missing_files_touched_returns_true_when_non_conservative():
    a = {'task_id': 'A', 'files_touched': []}
    b = {'task_id': 'B', 'files_touched': ['b.py']}
    assert can_run_parallel(a, b, conservative_missing_files=False) is True

def test_transitive_deps_bfs():
    a = {'task_id': 'A', 'dependencies': ['B']}
    b = {'task_id': 'B', 'dependencies': ['C']}
    c = {'task_id': 'C', 'dependencies': []}
    assert transitive_deps('A', [a, b, c]) == {'B', 'C'}

def test_transitive_deps_cycle():
    a = {'task_id': 'A', 'dependencies': ['B']}
    b = {'task_id': 'B', 'dependencies': ['A']}
    result = transitive_deps('A', [a, b])
    assert result == {'B'}

def test_project_isolation():
    ext = '/home/xnihil0zer0/NobleGreedv2'
    a = {'task_id': 'A', 'files_touched': ['foo.py'], 'working_dir': ext}
    b = {'task_id': 'B', 'files_touched': ['bar.py'], 'working_dir': ext}
    assert can_run_parallel(a, b) is False
    a = {'task_id': 'A', 'files_touched': ['foo.py']}
    b = {'task_id': 'B', 'files_touched': ['bar.py']}
    assert can_run_parallel(a, b) is True
    a = {'task_id': 'A', 'files_touched': ['foo.py'], 'working_dir': ext}
    b = {'task_id': 'B', 'files_touched': ['bar.py']}
    assert can_run_parallel(a, b) is True
    a = {'task_id': 'A', 'files_touched': ['foo.py'], 'working_dir': '/home/xnihil0zer0/AI-Data/JanusMaskEX'}
    b = {'task_id': 'B', 'files_touched': ['bar.py'], 'working_dir': '/home/xnihil0zer0/AI-Data/JanusMaskEX'}
    assert can_run_parallel(a, b) is True

def test_project_isolation_exact_path():
    fixtures = '/home/xnihil0zer0/AI-Data/JanusMaskEX/fixtures/NobleGreedv2-samples'
    a = {'task_id': 'A', 'files_touched': ['foo.py'], 'working_dir': fixtures}
    b = {'task_id': 'B', 'files_touched': ['bar.py'], 'working_dir': fixtures}
    assert can_run_parallel(a, b) is True
    sibling = '/home/xnihil0zer0/NobleGreedv2-other'
    a = {'task_id': 'A', 'files_touched': ['foo.py'], 'working_dir': sibling}
    b = {'task_id': 'B', 'files_touched': ['bar.py'], 'working_dir': sibling}
    assert can_run_parallel(a, b) is True

def test_selfheal_pseudo_task_never_conflicts_with_real_task():
    real = {'task_id': 'real-x', 'files_touched': ['harness/orchestrator.py']}
    selfheal = {'task_id': 'selfheal_claude_daemon_inactivity_stuck_42', 'files_touched': []}
    assert can_run_parallel(real, selfheal) is True
    assert can_run_parallel(selfheal, real) is True

def test_same_selfheal_id_still_serializes():
    a = {'task_id': 'selfheal_x', 'files_touched': []}
    b = {'task_id': 'selfheal_x', 'files_touched': []}
    assert can_run_parallel(a, b) is False

def test_non_selfheal_empty_files_still_conservative():
    a = {'task_id': 'a', 'files_touched': []}
    b = {'task_id': 'b', 'files_touched': ['x.py']}
    assert can_run_parallel(a, b) is False