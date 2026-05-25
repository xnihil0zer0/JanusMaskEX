"""W106 adversarial battery for orchestrator atomicity/durability fixes.

Pre-W106 bugs (round-3 H1/G3 audit):

* **F4** -- ``_mark_processed`` (lines 752, 756) called ``shutil.move``
  twice without ``try/except``. An ``OSError`` (dest exists, permission
  denied, cross-device) propagated and the in-flight task was left
  half-claimed in ``tasks/`` while the pickup loop kept retrying.
* **G3-1** -- ``get_next_task`` (line 597) wrapped ``json.load`` on the
  ``.processing`` file without ``JSONDecodeError`` handling. A corrupted
  payload (partial flush from a prior crash) crashed the orchestrator at
  task-claim time and the loop never advanced.
* **G3-2** -- ``run_pipeline`` accept blocks (lines 1018, 1035, 1062)
  set ``phase='accepted'`` BEFORE ``_save_final_output`` /
  ``_auto_commit_accepted`` / ``_mark_processed``. If any of those
  raised, ledger said "accepted" but no output / commit / processed
  marker existed.
* **G3-3** -- ``_save_final_output`` (lines 738-740) used direct
  ``open()`` + ``write()`` without ``fsync`` or ``replace()``. Partial
  write on crash left a corrupted ``.py`` file that downstream
  ``commit_accepted_output`` AST-merged into the worktree.

Fixes (in order):

* F4 wraps each ``shutil.move`` in ``try/except OSError``, logs CRITICAL,
  returns early per the W101 pattern.
* G3-1 wraps ``json.load`` in ``try/except JSONDecodeError``, quarantines
  the corrupted file under ``tasks/corrupted/<name>``, returns ``None``.
* G3-2 reorders all 3 accept blocks to save -> commit -> mark ->
  set_phase (set_phase last).
* G3-3 uses tmp + ``flush`` + ``fsync`` + ``replace`` mirroring
  ``harness/state.py:88-95``.
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from harness import orchestrator  # noqa: E402


# ---------------------------------------------------------------------------
# F4 -- _mark_processed wraps shutil.move
# ---------------------------------------------------------------------------


def _stage_processed_dirs(tmp_path: Path) -> Path:
    state_dir = tmp_path / 'state'
    (state_dir / 'tasks' / 'processed').mkdir(parents=True)
    return state_dir


def test_f4_mark_processed_handles_oserror_on_processing_file(tmp_path, monkeypatch, caplog):
    """A failing shutil.move on the .processing branch logs CRITICAL and
    returns instead of raising."""
    state_dir = _stage_processed_dirs(tmp_path)
    task_id = 'T-w106-f4a'
    proc = state_dir / 'tasks' / f'pre_{task_id}.json.processing'
    proc.write_text('{}')

    def fail_move(src, dst):
        raise OSError('simulated move failure')

    monkeypatch.setattr(orchestrator.shutil, 'move', fail_move)

    caplog.set_level('CRITICAL', logger='janusmask.orchestrator')
    orchestrator._mark_processed(state_dir, task_id)

    assert any(
        'CRITICAL' in r.message and task_id in r.message and 'processing file' in r.message
        for r in caplog.records
    ), [r.message for r in caplog.records]
    # processing file is left in place (move failed) -- recovery is operator-driven
    assert proc.exists()


def test_f4_mark_processed_handles_oserror_on_original_file(tmp_path, monkeypatch, caplog):
    """A failing shutil.move on the original-file (.json) branch also logs
    CRITICAL and returns."""
    state_dir = _stage_processed_dirs(tmp_path)
    task_id = 'T-w106-f4b'
    orig = state_dir / 'tasks' / f'pre_{task_id}.json'
    orig.write_text('{}')

    def fail_move(src, dst):
        raise OSError('simulated move failure')

    monkeypatch.setattr(orchestrator.shutil, 'move', fail_move)

    caplog.set_level('CRITICAL', logger='janusmask.orchestrator')
    orchestrator._mark_processed(state_dir, task_id)

    assert any(
        'CRITICAL' in r.message and task_id in r.message and 'original file' in r.message
        for r in caplog.records
    ), [r.message for r in caplog.records]
    assert orig.exists()


def test_f4_mark_processed_succeeds_when_move_ok(tmp_path):
    """Negative control: with shutil.move working, the file lands in
    processed/ and current_task.json is cleaned up."""
    state_dir = _stage_processed_dirs(tmp_path)
    task_id = 'T-w106-f4c'
    proc = state_dir / 'tasks' / f'pre_{task_id}.json.processing'
    proc.write_text('{}')
    current = state_dir / 'tasks' / f'current_task_{task_id}.json'
    current.write_text('{}')

    orchestrator._mark_processed(state_dir, task_id)

    assert not proc.exists()
    assert (state_dir / 'tasks' / 'processed' / f'{task_id}.json').exists()
    assert not current.exists()


# ---------------------------------------------------------------------------
# G3-1 -- get_next_task quarantines a corrupted .processing payload
# ---------------------------------------------------------------------------


def test_g3_1_get_next_task_quarantines_corrupt_post_rename(tmp_path, monkeypatch, caplog):
    """If the post-rename json.load on the .processing file raises
    JSONDecodeError, the file is quarantined to tasks/corrupted/ and
    get_next_task returns None instead of crashing."""
    state_dir = tmp_path / 'state'
    tasks_dir = state_dir / 'tasks'
    tasks_dir.mkdir(parents=True)
    candidate = tasks_dir / 'pre_T-w106-g31.json'
    candidate.write_text(json.dumps({'task_id': 'T-w106-g31', 'specification': 'x'}))

    real_load = json.load

    def mock_load(fp, *a, **kw):
        name = getattr(fp, 'name', '') or ''
        if str(name).endswith('.json.processing'):
            raise json.JSONDecodeError('boom', '{', 0)
        return real_load(fp, *a, **kw)

    monkeypatch.setattr(orchestrator.json, 'load', mock_load)

    caplog.set_level('ERROR', logger='janusmask.orchestrator')
    result = orchestrator.get_next_task(state_dir)

    assert result is None
    assert any('JSONDecodeError' in r.message and 'Quarantining' in r.message for r in caplog.records), [r.message for r in caplog.records]
    quarantined = tasks_dir / 'corrupted' / 'pre_T-w106-g31.json.processing'
    assert quarantined.exists()
    # original .processing path is gone
    assert not (tasks_dir / 'pre_T-w106-g31.json.processing').exists()


def test_g3_1_get_next_task_well_formed_still_returns_task(tmp_path):
    """Negative control: a well-formed candidate is loaded and returned."""
    state_dir = tmp_path / 'state'
    tasks_dir = state_dir / 'tasks'
    tasks_dir.mkdir(parents=True)
    candidate = tasks_dir / 'pre_T-w106-g31ok.json'
    candidate.write_text(json.dumps({'task_id': 'T-w106-g31ok', 'specification': 'x'}))

    result = orchestrator.get_next_task(state_dir)

    assert result is not None
    assert result['task_id'] == 'T-w106-g31ok'


# ---------------------------------------------------------------------------
# G3-2 -- accept-block reordering: save -> commit -> mark -> set_phase
# ---------------------------------------------------------------------------


def _accept_block_calls(src: str, sentinel: str) -> list[str]:
    """Return the leading-token of each call line between the sentinel
    log message and the closing 'continue' anchor.

    Post-G18bc (commits e66f7f4 + 3333056), the call shape changed from
    bare ``_auto_commit_accepted(...)`` to
    ``auto_commit_ok = _auto_commit_accepted(...)`` (return-value gate)
    and ``set_phase('accepted')`` was moved inside an ``if auto_commit_ok:``
    branch. The scanner now recognizes both the bare and assigned forms,
    and the terminator was loosened from 'continue' or 'logger.info' to
    'continue' alone -- the new logger.info now lives INSIDE the
    if-accepted branch, which is itself within the accept-block region.
    """
    canonical = ('_save_final_output', '_auto_commit_accepted', '_mark_processed', 'set_phase')
    lines = src.splitlines()
    start = next(i for i, line in enumerate(lines) if sentinel in line)
    calls: list[str] = []
    # WUI-1 (HITL keystone) inserts a control_gate.await_decision guard before
    # _auto_commit_accepted: an `if decision in ('reject', 'timeout'):` early-exit
    # branch (its own set_phase('rejected') + _mark_processed + continue) precedes
    # the accept path. Skip that guard branch so the scanner reaches the canonical
    # accept-path ordering rather than stopping at the reject branch's continue.
    skipping = False
    for line in lines[start + 1:]:
        stripped = line.strip()
        if stripped.startswith('if decision in'):
            skipping = True
            continue
        if skipping:
            if stripped.startswith('continue'):
                skipping = False
            continue
        if stripped.startswith('continue'):
            break
        for tok in canonical:
            if stripped.startswith(tok) or (' = ' + tok + '(') in stripped or stripped.startswith(tok + '('):
                calls.append(tok)
                break
    # G18bc's if/else mirrors set_phase across two branches -- collapse to a
    # single entry to preserve the canonical ordering assertion.
    deduped: list[str] = []
    for c in calls:
        if not (c == 'set_phase' and deduped and deduped[-1] == 'set_phase'):
            deduped.append(c)
    return deduped


@pytest.mark.parametrize('sentinel', [
    'Bypassing fuzzing for %s task',
    'EQUIVALENT after round 1 (%d/%d inputs matched)',
    'EQUIVALENT after round 2 (%d/%d inputs matched)',
])
def test_g3_2_accept_block_set_phase_is_last(sentinel):
    """All 3 accept blocks must invoke set_phase('accepted') AFTER
    _save_final_output / _auto_commit_accepted / _mark_processed."""
    src = inspect.getsource(orchestrator)
    calls = _accept_block_calls(src, sentinel)
    assert calls == ['_save_final_output', '_auto_commit_accepted', '_mark_processed', 'set_phase'], calls


def test_g3_2_accept_block_set_phase_uses_accepted_keyword():
    """Defensive: each set_phase call inside an accept block must use
    phase='accepted' (regression guard against accidental phase swap)."""
    src = inspect.getsource(orchestrator)
    sentinels = [
        'Bypassing fuzzing for %s task',
        'EQUIVALENT after round 1 (%d/%d inputs matched)',
        'EQUIVALENT after round 2 (%d/%d inputs matched)',
    ]
    lines = src.splitlines()
    for sentinel in sentinels:
        start = next(i for i, line in enumerate(lines) if sentinel in line)
        # search up to the accept-path 'continue' for the set_phase line, skipping
        # the WUI-1 HITL reject/timeout guard branch (which ends in its own continue).
        slab = []
        skipping = False
        for line in lines[start + 1:]:
            stripped = line.strip()
            if stripped.startswith('if decision in'):
                skipping = True
                continue
            if skipping:
                if stripped.startswith('continue'):
                    skipping = False
                continue
            slab.append(line)
            if stripped.startswith('continue'):
                break
        joined = '\n'.join(slab)
        assert "set_phase(state_dir, phase='accepted')" in joined, (sentinel, joined)


# ---------------------------------------------------------------------------
# G3-3 -- _save_final_output uses tmp + fsync + replace
# ---------------------------------------------------------------------------


def test_g3_3_save_final_output_uses_atomic_pattern():
    """Source must include tmp_path = with_suffix('.py.tmp') + flush +
    fsync + replace pattern (mirror of harness/state.py:88-95)."""
    src = inspect.getsource(orchestrator._save_final_output)
    assert ".with_suffix('.py.tmp')" in src
    assert 'f.flush()' in src
    assert 'os.fsync(f.fileno())' in src
    assert 'tmp_path.replace(out_path)' in src


def test_g3_3_save_final_output_writes_file_and_no_tmp_left(tmp_path):
    """End-to-end: file lands at output/<task>.py with the right content
    and no .tmp residue."""
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    task_id = 'T-w106-g33'
    code = "def f():\n    return 42\n"

    orchestrator._save_final_output(state_dir, task_id, code)

    out_path = state_dir / 'output' / f'{task_id}.py'
    assert out_path.read_text() == code
    assert not (state_dir / 'output' / f'{task_id}.py.tmp').exists()


def test_g3_3_save_final_output_overwrite_atomic(tmp_path):
    """Re-saving over an existing output file replaces it atomically
    (no mid-write partial state visible)."""
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    task_id = 'T-w106-g33b'
    out_path = state_dir / 'output' / f'{task_id}.py'
    out_path.parent.mkdir(parents=True)
    out_path.write_text('OLD')

    orchestrator._save_final_output(state_dir, task_id, 'NEW\n')

    assert out_path.read_text() == 'NEW\n'
    assert not (state_dir / 'output' / f'{task_id}.py.tmp').exists()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
