from __future__ import annotations
from harness.autowork_parallelism import can_run_parallel, transitive_deps

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