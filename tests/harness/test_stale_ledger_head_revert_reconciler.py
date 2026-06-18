"""RED oracle for the HEAD-revert pop-row reconciler + brief_reaper un-count.

This oracle pins the desired POST-FIX behaviour of two halves that are both
absent on HEAD, so it is correctly RED on HEAD and turns GREEN after the impl
(``stale-ledger-head-revert-reconciler-impl``) lands:

* ``harness.state_reconciler.cleanup_state(root, mode='apply')`` -- extended
  additively to append a pop-row to ``state/impl_progress.jsonl`` for every
  accepted tid whose recorded ``commit_sha`` is NOT an ancestor of HEAD. The
  pop-row's ``event`` MUST be the literal string ``'task_blocked'`` (a
  ``'reconcile_revert'`` name would be inert because ``compute_brief_status``
  replay consumes only ``event in ('reject_rollback', 'task_blocked')``) and it
  MUST carry a SEPARATE ``reconcile_reason`` provenance field.
* ``tools.brief_reaper._integrated_task_ids(root)`` -- extended to UN-COUNT a
  tid once a later ``reject_rollback``/``task_blocked`` row for it is seen
  during the ordered scan. The un-count assertion is the non-vacuity
  discriminator: it FAILS against the declared brief_reaper mutant that omits
  the un-count handling.

Every test is fully hermetic: its own ``tmp_path`` workspace + git repo, no
live ``state/``, no network.
"""
import json
import subprocess
import pytest
import tools.brief_reaper as brief_reaper
from harness import state_reconciler

def _git(root, *args, check=True):
    """Run ``git -C root *args`` capturing output; skip if git is unavailable."""
    try:
        return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=check)
    except (OSError, FileNotFoundError):
        pytest.skip('git executable not available')

def _build_repo(tmp_path):
    """Build a throwaway git repo under tmp_path and return ancestry context.

    HEAD is advanced to a second commit on the default branch; the returned
    ``ancestor`` sha is a real ancestor of HEAD, while ``non_ancestor`` is a
    commit on a divergent branch that is NOT reachable from HEAD.
    """
    root = tmp_path / 'ws'
    root.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(['git', '-C', str(root), 'init', '-q'], capture_output=True, text=True, check=True)
    except (OSError, FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip('git executable not available')
    _git(root, 'config', 'user.email', 'oracle@test.invalid')
    _git(root, 'config', 'user.name', 'oracle')
    _git(root, 'config', 'commit.gpgsign', 'false')
    (root / 'f.txt').write_text('1', encoding='utf-8')
    _git(root, 'add', '.')
    _git(root, 'commit', '-q', '-m', 'c1')
    base = _git(root, 'rev-parse', 'HEAD').stdout.strip()
    branch = _git(root, 'rev-parse', '--abbrev-ref', 'HEAD').stdout.strip()
    (root / 'f.txt').write_text('2', encoding='utf-8')
    _git(root, 'add', '.')
    _git(root, 'commit', '-q', '-m', 'c2')
    head = _git(root, 'rev-parse', 'HEAD').stdout.strip()
    _git(root, 'checkout', '-q', '-b', 'divergent', base)
    _git(root, 'commit', '-q', '--allow-empty', '-m', 'divergent')
    non_ancestor = _git(root, 'rev-parse', 'HEAD').stdout.strip()
    _git(root, 'checkout', '-q', branch)
    anc_ok = _git(root, 'merge-base', '--is-ancestor', base, head, check=False)
    non_ok = _git(root, 'merge-base', '--is-ancestor', non_ancestor, head, check=False)
    if anc_ok.returncode != 0 or non_ok.returncode == 0:
        pytest.skip('git ancestry fixture could not be established')
    return (root, {'head': head, 'ancestor': base, 'non_ancestor': non_ancestor})

def _ledger_path(root):
    return root / 'state' / 'impl_progress.jsonl'

def _write_ledger(root, rows):
    """Write rows (dicts or raw strings) one-per-line to state/impl_progress.jsonl."""
    sd = root / 'state'
    sd.mkdir(parents=True, exist_ok=True)
    lines = []
    for row in rows:
        if isinstance(row, str):
            lines.append(row)
        else:
            lines.append(json.dumps(row))
    _ledger_path(root).write_text('\n'.join(lines) + '\n', encoding='utf-8')

def _read_rows(root):
    """Read back the ledger as a list of dict rows (malformed lines dropped)."""
    text = _ledger_path(root).read_text(encoding='utf-8')
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out

def _pop_rows(rows, tid):
    """Pop-rows for tid = ledger rows whose event is the literal task_blocked."""
    return [r for r in rows if r.get('task_id') == tid and r.get('event') == 'task_blocked']

def _accepted_row(tid, sha):
    return {'ts': '2026-06-18T00:00:00Z', 'phase': 'accepted', 'task_id': tid, 'event': 'auto_commit', 'commit_sha': sha, 'files': ['f.txt'], 'exit': 0}

def test_pop_row_appended_when_sha_not_ancestor_of_head(tmp_path):
    """An accepted tid whose sha is NOT an ancestor of HEAD gets a pop-row."""
    root, ctx = _build_repo(tmp_path)
    tid = 'stale-task'
    _write_ledger(root, [_accepted_row(tid, ctx['non_ancestor'])])
    state_reconciler.cleanup_state(str(root), mode='apply')
    pops = _pop_rows(_read_rows(root), tid)
    assert len(pops) == 1, 'expected exactly one task_blocked pop-row appended for an accepted tid whose sha is not an ancestor of HEAD, got %d' % len(pops)

def test_pop_row_event_is_literal_task_blocked_with_reconcile_reason(tmp_path):
    """Pop-row event is literally 'task_blocked' + a separate reconcile_reason."""
    root, ctx = _build_repo(tmp_path)
    tid = 'revert-me'
    _write_ledger(root, [_accepted_row(tid, ctx['non_ancestor'])])
    state_reconciler.cleanup_state(str(root), mode='apply')
    pops = _pop_rows(_read_rows(root), tid)
    assert len(pops) == 1
    row = pops[0]
    assert row['event'] == 'task_blocked'
    assert row['event'] != 'reconcile_revert'
    assert 'reconcile_reason' in row, 'pop-row must carry a separate reconcile_reason provenance field'
    assert row['reconcile_reason'], 'reconcile_reason must be non-empty'
    assert row['reconcile_reason'] != row['event'], 'reconcile_reason must be a distinct provenance field, not a copy of the event token'

def test_integrated_task_ids_uncounts_on_later_reject_rollback_or_task_blocked(tmp_path):
    """_integrated_task_ids un-counts a tid on a later reject_rollback OR task_blocked.

    This is the non-vacuity discriminator: against the brief_reaper mutant that
    omits the un-count handling, the un-counted tids remain in the set and these
    assertions FAIL.
    """
    root = tmp_path / 'ws'
    root.mkdir(parents=True, exist_ok=True)
    tid_reject = 'reverted-by-reject'
    tid_blocked = 'reverted-by-blocked'
    tid_kept = 'still-integrated'
    _write_ledger(root, [_accepted_row(tid_kept, 'a' * 40), _accepted_row(tid_reject, 'b' * 40), {'ts': '2026-06-18T00:00:01Z', 'task_id': tid_blocked, 'event': 'no_diff'}, {'ts': '2026-06-18T00:00:02Z', 'phase': 'rejected', 'task_id': tid_reject, 'event': 'reject_rollback', 'reason': 'rolled back'}, {'ts': '2026-06-18T00:00:03Z', 'phase': 'autowork', 'task_id': tid_blocked, 'event': 'task_blocked', 'detail': 'blocked'}])
    counted = brief_reaper._integrated_task_ids(root)
    assert tid_kept in counted, 'a tid accepted with no later pop must remain counted'
    assert tid_reject not in counted, 'a tid must be UN-COUNTED after a later reject_rollback row'
    assert tid_blocked not in counted, 'a tid must be UN-COUNTED after a later task_blocked row'

def test_no_pop_row_when_sha_is_ancestor_of_head(tmp_path):
    """An accepted tid whose sha IS an ancestor of HEAD must NOT get a pop-row."""
    root, ctx = _build_repo(tmp_path)
    tid = 'healthy-task'
    _write_ledger(root, [_accepted_row(tid, ctx['ancestor'])])
    state_reconciler.cleanup_state(str(root), mode='apply')
    pops = _pop_rows(_read_rows(root), tid)
    assert pops == [], 'an accepted tid whose sha is an ancestor of HEAD must not be popped'

def test_reconciler_idempotent_no_duplicate_pop_row(tmp_path):
    """Re-running the reconciler does not append a duplicate pop-row."""
    root, ctx = _build_repo(tmp_path)
    tid = 'stale-task'
    _write_ledger(root, [_accepted_row(tid, ctx['non_ancestor'])])
    state_reconciler.cleanup_state(str(root), mode='apply')
    first = _pop_rows(_read_rows(root), tid)
    assert len(first) == 1
    state_reconciler.cleanup_state(str(root), mode='apply')
    second = _pop_rows(_read_rows(root), tid)
    assert len(second) == 1, 'reconciler must be idempotent: a tid already carrying a task_blocked pop-row must not get a duplicate, got %d pop-rows' % len(second)

def test_ledger_compacted_never_wiped_preexisting_rows_survive(tmp_path):
    """The reconciler COMPACTS the ledger; unrelated rows survive, never wiped."""
    root, ctx = _build_repo(tmp_path)
    stale = 'stale-task'
    healthy = 'healthy-task'
    other = 'unrelated-task'
    _write_ledger(root, [{'ts': '2026-06-18T00:00:00Z', 'task_id': other, 'event': 'no_diff'}, _accepted_row(healthy, ctx['ancestor']), _accepted_row(stale, ctx['non_ancestor'])])
    state_reconciler.cleanup_state(str(root), mode='apply')
    assert _ledger_path(root).exists(), 'ledger must not be deleted'
    assert _ledger_path(root).read_text(encoding='utf-8').strip(), 'ledger must never be wiped to empty'
    rows = _read_rows(root)
    surviving = {r.get('task_id') for r in rows}
    assert other in surviving, 'unrelated preexisting row must survive'
    assert healthy in surviving, 'ancestor accepted row must survive'
    assert len(_pop_rows(rows, stale)) == 1

def test_malformed_ledger_line_skipped_fail_closed(tmp_path):
    """A malformed / non-dict JSON line is skipped without aborting the reconcile."""
    root, ctx = _build_repo(tmp_path)
    stale = 'stale-task'
    _write_ledger(root, ['this is not json at all', '[1, 2, 3]', {'ts': '2026-06-18T00:00:00Z', 'task_id': 'kept', 'event': 'no_diff'}, _accepted_row(stale, ctx['non_ancestor'])])
    state_reconciler.cleanup_state(str(root), mode='apply')
    assert _ledger_path(root).exists()
    assert _ledger_path(root).read_text(encoding='utf-8').strip(), 'ledger must never be wiped even with malformed lines present'
    rows = _read_rows(root)
    assert any((r.get('task_id') == 'kept' for r in rows)), 'valid rows must survive a fail-closed reconcile'
    assert len(_pop_rows(rows, stale)) == 1, 'the non-ancestor tid must still be popped despite malformed lines'