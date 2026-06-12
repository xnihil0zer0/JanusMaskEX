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

def test_project_isolation():
    ext = '/home/xnihil0zer0/NobleGreedv2'

    # (i) Two tasks resolving to the SAME isolated external root -> serialize.
    # They share one mutable repo root whose EXTERNAL_DIRTY_GATE reads shared state.
    a = {'task_id': 'A', 'files_touched': ['foo.py'], 'working_dir': ext}
    b = {'task_id': 'B', 'files_touched': ['bar.py'], 'working_dir': ext}
    assert can_run_parallel(a, b) is False

    # (ii) Both working_dir absent => both JM self-tasks => parallelize
    # (self-tasks are fully worktree-isolated already).
    a = {'task_id': 'A', 'files_touched': ['foo.py']}
    b = {'task_id': 'B', 'files_touched': ['bar.py']}
    assert can_run_parallel(a, b) is True

    # (iii) One external + one bare self-task => different projects => parallelize.
    a = {'task_id': 'A', 'files_touched': ['foo.py'], 'working_dir': ext}
    b = {'task_id': 'B', 'files_touched': ['bar.py']}
    assert can_run_parallel(a, b) is True

    # JM self-tasks with an explicit repo-root working_dir are likewise exempt.
    a = {'task_id': 'A', 'files_touched': ['foo.py'], 'working_dir': '/home/xnihil0zer0/JanusMaskJR'}
    b = {'task_id': 'B', 'files_touched': ['bar.py'], 'working_dir': '/home/xnihil0zer0/JanusMaskJR'}
    assert can_run_parallel(a, b) is True

def test_project_isolation_exact_path():
    # Isolation membership is EXACT resolved-path comparison against
    # _ISOLATED_EXTERNAL_DIRS, never a substring test: a path merely
    # CONTAINING "NobleGreedv2" is not isolated.
    fixtures = '/home/xnihil0zer0/JanusMaskJR/fixtures/NobleGreedv2-samples'
    a = {'task_id': 'A', 'files_touched': ['foo.py'], 'working_dir': fixtures}
    b = {'task_id': 'B', 'files_touched': ['bar.py'], 'working_dir': fixtures}
    assert can_run_parallel(a, b) is True

    sibling = '/home/xnihil0zer0/NobleGreedv2-other'
    a = {'task_id': 'A', 'files_touched': ['foo.py'], 'working_dir': sibling}
    b = {'task_id': 'B', 'files_touched': ['bar.py'], 'working_dir': sibling}
    assert can_run_parallel(a, b) is True