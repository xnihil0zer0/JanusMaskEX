"""RED oracle — terminal-outcome purge of stale emission sidecars (worker-sidecar-purge).

DEFECT (2026-06-09, autocompiler Phase A): ``commit_accepted_output``
(git_integration.py:610-699) dispatches the accept path on SIDECAR EXISTENCE —
``state/output/<tid>.files.json`` => multi-file path, ``<tid>.patches.json`` =>
patches path. A failed attempt's stale sidecar therefore HIJACKS every later
attempt of the same task (observed: crossover_impl rerouted to the
cannot-create-files patches path; autocompiler-fitness-vector-contract rerouted
to a stale multi-file map naming a sensitive config/** file), making retries
deterministically fail regardless of the fresh submission.

Contract: ``_purge_stale_sidecars_safe(payload: dict, state_dir=None) ->
list[str]`` in harness/orchestrator_worker.py — the ``_reap_spent_briefs_safe``
idiom. On a NON-accept terminal payload (``outcome`` not in
``('accepted', 'no_diff')``) it best-effort unlinks
``state_dir/output/<task_id>.patches.json`` and ``<task_id>.files.json`` and
returns the removed filenames. Accepted/no_diff payloads, missing/invalid
``task_id``, missing dirs, or ANY internal error => purge nothing relevant,
return a list, NEVER raise (it is called from ``_print_json_line`` after the
JSON line is flushed, exactly like ``_reap_spent_briefs_safe``). When
``state_dir`` is None it resolves the repo-standard ``<repo_root>/state``.
"""
import inspect
import json
from pathlib import Path

from harness.orchestrator_worker import _print_json_line, _purge_stale_sidecars_safe


def _seed(tmp_path, tid='t1'):
    out = tmp_path / 'output'
    out.mkdir(parents=True, exist_ok=True)
    (out / f'{tid}.patches.json').write_text(json.dumps([{'qualname': 'f', 'code': 'def f():\n    return 1\n'}]))
    (out / f'{tid}.files.json').write_text(json.dumps({'a.py': 'x = 1\n'}))
    (out / f'{tid}.py').write_text('x = 1\n')
    return out


def test_non_accept_purges_both_sidecars(tmp_path):
    out = _seed(tmp_path)
    removed = _purge_stale_sidecars_safe({'task_id': 't1', 'outcome': 'rejected'}, state_dir=tmp_path)
    assert not (out / 't1.patches.json').exists()
    assert not (out / 't1.files.json').exists()
    assert (out / 't1.py').exists(), 'only the format-dispatch sidecars are purged'
    assert sorted(removed) == ['t1.files.json', 't1.patches.json']


def test_accepted_and_no_diff_leave_sidecars():
    # consumed-on-accept artifacts must not be touched
    for outcome in ('accepted', 'no_diff'):
        assert _purge_stale_sidecars_safe({'task_id': 't1', 'outcome': outcome}, state_dir=Path('/nonexistent')) == []


def test_other_task_sidecars_untouched(tmp_path):
    out = _seed(tmp_path, 'other')
    _purge_stale_sidecars_safe({'task_id': 't1', 'outcome': 'timeout'}, state_dir=tmp_path)
    assert (out / 'other.patches.json').exists()
    assert (out / 'other.files.json').exists()


def test_missing_output_dir_returns_empty_no_raise(tmp_path):
    assert _purge_stale_sidecars_safe({'task_id': 't1', 'outcome': 'rejected'}, state_dir=tmp_path) == []


def test_garbage_payload_never_raises(tmp_path):
    assert _purge_stale_sidecars_safe({}, state_dir=tmp_path) == []
    assert _purge_stale_sidecars_safe({'task_id': None, 'outcome': 'rejected'}, state_dir=tmp_path) == []
    assert _purge_stale_sidecars_safe({'task_id': '../escape', 'outcome': 'rejected'}, state_dir='not-a-dir') == []


def test_wired_into_print_json_line_chokepoint():
    src = inspect.getsource(_print_json_line)
    assert '_purge_stale_sidecars_safe(' in src, (
        '_print_json_line must invoke the purge bridge (wiring-asserting oracle; '
        'mirror of the _reap_spent_briefs_safe call)')
