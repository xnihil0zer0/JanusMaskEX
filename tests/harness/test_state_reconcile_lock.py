"""RED oracle for the shared ``state_reconcile.lock`` serialization primitive.

This hermetic pytest file proves the lock-correctness contract of
``harness.state_reconciler.state_reconcile_lock``:

* a single dedicated ``state_reconcile.lock`` serializes concurrent mutators
  (mutual exclusion: two mutators never both enter the destructive section),
* the slow destructive op runs while that shared lock is held for its full
  duration,
* the short-lived ``git_commit.lock`` is NEVER held across the slow section,
* the lock is fail-closed -- released on exception so a crashed mutator does
  not wedge the others.

Everything runs in its own ``tmp_path`` state directory: no live ``state/``,
no daemon, no network.
"""
import threading
import time
from pathlib import Path
import pytest
from harness import state_reconciler
from harness.state_reconciler import state_reconcile_lock

def _run_two_mutators(state_dir, slow=0.2):
    """Drive two concurrent mutators through the shared lock.

    Each mutator acquires ``state_reconcile_lock`` and, inside the held lock,
    enters an instrumented "destructive" section that sleeps ``slow`` seconds.
    Returns the maximum number of mutators observed simultaneously inside the
    destructive section and any errors raised by the threads.
    """
    barrier = threading.Barrier(2)
    instrument = threading.Lock()
    active = {'count': 0, 'max': 0}
    errors = []

    def mutator():
        try:
            barrier.wait(timeout=10)
            with state_reconcile_lock(str(state_dir)):
                with instrument:
                    active['count'] += 1
                    active['max'] = max(active['max'], active['count'])
                time.sleep(slow)
                with instrument:
                    active['count'] -= 1
        except Exception as exc:
            errors.append(exc)
    threads = [threading.Thread(target=mutator) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert not any((t.is_alive() for t in threads)), 'mutator thread hung'
    return (active['max'], errors)

def test_two_mutators_never_overlap_in_destructive_section(tmp_path):
    state_dir = tmp_path / 'state'
    max_concurrent, errors = _run_two_mutators(state_dir)
    assert not errors, f'mutators raised: {errors}'
    assert max_concurrent == 1, 'two mutators overlapped in the destructive section -- the shared state_reconcile.lock did not serialize them'

def test_slow_op_holds_state_reconcile_lock_for_full_duration(tmp_path):
    state_dir = tmp_path / 'state'
    lock_file = state_dir / state_reconciler.LOCK_FILENAME
    observations = []
    with state_reconcile_lock(str(state_dir)) as held:
        assert Path(held) == lock_file
        for _ in range(6):
            observations.append(lock_file.exists())
            time.sleep(0.02)
    assert observations, 'no observations sampled'
    assert all(observations), 'state_reconcile.lock was not held for the full slow-op duration'
    assert not lock_file.exists()

def test_git_commit_lock_not_held_across_slow_section(tmp_path):
    state_dir = tmp_path / 'state'
    git_commit_lock = state_dir / 'git_commit.lock'
    state_lock = state_dir / state_reconciler.LOCK_FILENAME
    git_samples = []
    state_samples = []
    with state_reconcile_lock(str(state_dir)):
        for _ in range(6):
            git_samples.append(git_commit_lock.exists())
            state_samples.append(state_lock.exists())
            time.sleep(0.02)
    assert state_samples and all(state_samples), 'state_reconcile.lock should be held across the slow section'
    assert not any(git_samples), 'git_commit.lock must NOT be held across the slow destructive section'

def test_repeated_concurrent_runs_preserve_mutual_exclusion(tmp_path):
    for i in range(8):
        state_dir = tmp_path / f'state_{i}'
        max_concurrent, errors = _run_two_mutators(state_dir, slow=0.05)
        assert not errors, f'run {i} raised: {errors}'
        assert max_concurrent == 1, f'overlap detected on run {i}'

def test_lock_released_on_exception_fail_closed(tmp_path):
    state_dir = tmp_path / 'state'
    lock_file = state_dir / state_reconciler.LOCK_FILENAME
    with pytest.raises(RuntimeError):
        with state_reconcile_lock(str(state_dir)):
            assert lock_file.exists()
            raise RuntimeError('boom')
    assert not lock_file.exists(), 'lock not released on exception'
    with state_reconcile_lock(str(state_dir), timeout=5.0) as held:
        assert Path(held) == lock_file
        assert lock_file.exists()
    assert not lock_file.exists()

def test_single_dedicated_lock_path_used_by_all_mutators(tmp_path):
    state_dir = tmp_path / 'state'
    assert state_reconciler.LOCK_FILENAME == 'state_reconcile.lock'
    assert state_reconciler.LOCK_FILENAME != 'git_commit.lock'
    seen = []
    seen_lock = threading.Lock()
    barrier = threading.Barrier(2)
    errors = []

    def mutator():
        try:
            barrier.wait(timeout=10)
            with state_reconcile_lock(str(state_dir)) as held:
                with seen_lock:
                    seen.append(Path(held))
                time.sleep(0.05)
        except Exception as exc:
            errors.append(exc)
    threads = [threading.Thread(target=mutator) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert not errors, f'mutators raised: {errors}'
    assert len(seen) == 2
    expected = state_dir / state_reconciler.LOCK_FILENAME
    assert all((p == expected for p in seen)), 'all mutators must serialize on the single dedicated lock path'