"""RED oracle for the stale-discriminator predicate library.

These hermetic unit tests pin the *observable* behaviour of the discriminator
helper predicates that live in ``harness/state_reconciler.py``:

* ``pid_is_live(pid)`` -- process liveness probe.
* ``task_id_has_live_pidfile(running_dir, task_id)`` -- exact, substring-proof
  match of a task id against regular and self-heal pidfile stems.
* a ledger cross-reference predicate -- has this exact task id been recorded?
* a worktree reachability predicate -- is the workdir still a registered
  Git worktree?
* a session-slug parser -- extract the *exact* task id out of
  ``<agent>-r<n>-<task_id>-<uuid8>``.

The dominant invariant under test is **exact equality, never substring**: a task
id ``'t1'`` must never be confused with ``'t12'`` (whether the latter appears as
a plain ``t12.pid`` stem, inside a ``selfheal_agent_t12_999.pid`` stem, in the
ledger, or inside a session slug). The suite is RED on HEAD (the predicates do
not yet exist) and turns GREEN once they are implemented; a mutant that drops the
exact-equality guard or the liveness check fails at least one assertion.
"""
import errno
import json
import os
import pytest
import harness.state_reconciler as sr

def _resolve(*candidate_names):
    """Return the first predicate present on the module under test.

    Accessing a missing predicate raises (rather than skipping) so the oracle is
    RED on HEAD where these helpers are not implemented yet.
    """
    for name in candidate_names:
        fn = getattr(sr, name, None)
        if callable(fn):
            return fn
    raise AttributeError('harness.state_reconciler is missing all of: ' + ', '.join(candidate_names))

def _find_dead_pid():
    """A pid that is guaranteed not to name a live, signalable process."""
    for cand in range(2 ** 31 - 1, 2 ** 31 - 4096, -1):
        try:
            os.kill(cand, 0)
        except OSError as exc:
            if getattr(exc, 'errno', None) == errno.ESRCH:
                return cand
        else:
            continue
    return 2 ** 31 - 1

def _write_pidfile(running_dir, stem, pid):
    running_dir.mkdir(parents=True, exist_ok=True)
    path = running_dir / (stem + '.pid')
    path.write_text(str(pid), encoding='utf-8')
    return path

def _task_id_of(result):
    """Normalise a slug-parse result down to its task id string."""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return result.get('task_id')
    return getattr(result, 'task_id', result)

def test_pid_is_live_basic():
    pid_is_live = _resolve('pid_is_live')
    assert pid_is_live(os.getpid())
    assert not pid_is_live(_find_dead_pid())

def test_pid_is_live_rejects_invalid():
    pid_is_live = _resolve('pid_is_live')
    assert not pid_is_live(0)
    assert not pid_is_live(-1)

def test_task_id_has_live_pidfile_exact_match(tmp_path):
    has_live = _resolve('task_id_has_live_pidfile')
    running = tmp_path / 'running'
    _write_pidfile(running, 't12', os.getpid())
    assert has_live(str(running), 't12')

def test_task_id_has_live_pidfile_rejects_substring(tmp_path):
    has_live = _resolve('task_id_has_live_pidfile')
    running = tmp_path / 'running'
    _write_pidfile(running, 't12', os.getpid())
    assert not has_live(str(running), 't1')
    assert not has_live(str(running), 't120')

def test_task_id_has_live_pidfile_selfheal_stem(tmp_path):
    has_live = _resolve('task_id_has_live_pidfile')
    running = tmp_path / 'running'
    _write_pidfile(running, 'selfheal_agent_t12_999', os.getpid())
    assert has_live(str(running), 't12')
    assert not has_live(str(running), 't1')
    assert not has_live(str(running), 'agent')
    assert not has_live(str(running), 't12_999')

def test_task_id_has_live_pidfile_dead_pid(tmp_path):
    has_live = _resolve('task_id_has_live_pidfile')
    running = tmp_path / 'running'
    _write_pidfile(running, 't77', _find_dead_pid())
    assert not has_live(str(running), 't77')

def test_ledger_cross_ref_basic(tmp_path):
    in_ledger = _resolve('task_id_in_ledger', 'ledger_has_task_id', 'is_task_id_in_ledger')
    ledger = tmp_path / 'ledger.jsonl'
    ledger.write_text('\n'.join((json.dumps({'task_id': tid, 'event': 'accepted'}) for tid in ('t12', 't34'))) + '\n', encoding='utf-8')
    assert in_ledger(str(ledger), 't12')
    assert not in_ledger(str(ledger), 't1')
    assert not in_ledger(str(ledger), 't99')

def test_worktree_reachability_basic(tmp_path):
    reachable = _resolve('worktree_is_reachable', 'workdir_is_reachable', 'is_worktree_reachable', 'workdir_has_worktree')
    wt_a = tmp_path / 'wt-t12'
    wt_b = tmp_path / 'wt-t34'
    wt_missing = tmp_path / 'wt-gone'
    for d in (wt_a, wt_b):
        d.mkdir()
    registered = [str(wt_a), str(wt_b)]
    assert reachable(str(wt_a), registered)
    assert not reachable(str(wt_missing), registered)

def test_session_slug_parser_format():
    parse = _resolve('parse_session_slug', 'session_slug_task_id', 'parse_slug')
    assert _task_id_of(parse('agent-r1-t12-abcd1234')) == 't12'
    assert _task_id_of(parse('gemini-r2-t34-deadbeef')) == 't34'

def test_session_slug_parser_rejects_substring():
    parse = _resolve('parse_session_slug', 'session_slug_task_id', 'parse_slug')
    parsed = _task_id_of(parse('agent-r1-t12-abcd1234'))
    assert parsed == 't12'
    assert parsed != 't1'