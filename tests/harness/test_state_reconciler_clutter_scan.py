"""RED oracle for the advisory ``clutter_candidates`` detect-only contract.

This is an ordinary pytest module (NO custom marker) that pins the EXACT
observable behaviour of ``harness.state_reconciler.cleanup_state`` /
``WorkspaceStatus`` once the clutter-scan implementation lands:

* a stale (mtime aged past ``CLUTTER_AGE_SECONDS == 604800``) top-level
  non-KEEP ``*.md`` produces a candidate ``{'path': '<name>.md',
  'reason': 'root_doc_unkept'}``;
* a stale KEEP doc (e.g. ``README.md``) is NOT flagged;
* an idle planning dump (``state/planning/plan_x.json`` when
  ``merged_plan.json`` parses to ``{'tasks': []}``) yields
  ``'planning_dump_idle'`` while ``merged_plan.json`` /
  ``amendment_report.json`` are never flagged, and a non-empty
  ``merged_plan.json`` suppresses it;
* a stale ``_autowork_scratch`` child yields ``'scratch_aged'`` while a
  fresh one is not flagged;
* ``clutter_candidates`` is a list of ``{'path', 'reason'}`` dicts with
  forward-slash relative paths SORTED by path;
* ``ready`` is False whenever ``clutter_candidates`` is non-empty and stays
  True (unchanged) for a clean root;
* detection is ADVISORY ONLY -- ``apply`` populates ``clutter_candidates``
  identically to ``report`` and NEVER moves the clutter off disk.

Every test synthesizes its own ``tmp_path`` root and straddles the
604800s threshold with ``os.utime`` -- no live ``state/``, no network, no
shared fixtures. It is RED on HEAD because ``WorkspaceStatus`` has no
``clutter_candidates`` slot (attribute access raises) and ``cleanup_state``
does not scan for clutter; it goes GREEN once the impl leaf lands.
"""
import json
import os
import time
from harness.state_reconciler import cleanup_state, classify_product, ProductStatus, WorkspaceStatus
CLUTTER_AGE_SECONDS = 604800
AGED = CLUTTER_AGE_SECONDS + 86400
FRESH = 3600

def _write(path, text=''):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path

def _age(path, seconds_old):
    t = time.time() - seconds_old
    os.utime(str(path), (t, t))
    return path

def _paths(status):
    return [c['path'] for c in status.clutter_candidates]

def _reasons_by_path(status):
    return {c['path']: c['reason'] for c in status.clutter_candidates}

def test_stale_root_doc_unkept_flagged(tmp_path):
    _age(_write(tmp_path / 'obsolete_notes.md', 'old'), AGED)
    _age(_write(tmp_path / 'fresh_notes.md', 'new'), FRESH)
    status = cleanup_state(str(tmp_path), mode='report')
    reasons = _reasons_by_path(status)
    assert reasons.get('obsolete_notes.md') == 'root_doc_unkept'
    assert 'fresh_notes.md' not in reasons
    for cand in status.clutter_candidates:
        assert set(cand.keys()) == {'path', 'reason'}

def test_keep_doc_not_flagged(tmp_path):
    _age(_write(tmp_path / 'README.md', '# readme'), AGED)
    status = cleanup_state(str(tmp_path), mode='report')
    assert 'README.md' not in _paths(status)
    assert status.clutter_candidates == []
    assert status.ready is True

def test_planning_dump_idle_when_merged_plan_empty(tmp_path):
    pdir = tmp_path / 'state' / 'planning'
    _age(_write(pdir / 'merged_plan.json', json.dumps({'tasks': []})), AGED)
    _age(_write(pdir / 'plan_x.json', json.dumps({'x': 1})), AGED)
    _age(_write(pdir / 'amendment_report.json', json.dumps({'r': 1})), AGED)
    status = cleanup_state(str(tmp_path), mode='report')
    reasons = _reasons_by_path(status)
    assert reasons.get('state/planning/plan_x.json') == 'planning_dump_idle'
    assert 'state/planning/merged_plan.json' not in reasons
    assert 'state/planning/amendment_report.json' not in reasons

def test_planning_dump_not_flagged_when_merged_plan_nonempty(tmp_path):
    pdir = tmp_path / 'state' / 'planning'
    _age(_write(pdir / 'merged_plan.json', json.dumps({'tasks': [{'id': 't1'}]})), AGED)
    _age(_write(pdir / 'plan_x.json', json.dumps({'x': 1})), AGED)
    status = cleanup_state(str(tmp_path), mode='report')
    assert 'state/planning/plan_x.json' not in _paths(status)

def test_scratch_aged_flagged_fresh_not_flagged(tmp_path):
    sdir = tmp_path / '_autowork_scratch'
    _age(_write(sdir / 'old.md', 'o'), AGED)
    _age(_write(sdir / 'new.md', 'n'), FRESH)
    status = cleanup_state(str(tmp_path), mode='report')
    reasons = _reasons_by_path(status)
    assert reasons.get('_autowork_scratch/old.md') == 'scratch_aged'
    assert '_autowork_scratch/new.md' not in reasons

def test_ready_false_with_clutter_and_sorted_paths(tmp_path):
    _age(_write(tmp_path / 'stale_doc.md', 'd'), AGED)
    _age(_write(tmp_path / '_autowork_scratch' / 'junk.md', 'j'), AGED)
    pdir = tmp_path / 'state' / 'planning'
    _age(_write(pdir / 'merged_plan.json', json.dumps({'tasks': []})), AGED)
    _age(_write(pdir / 'plan_x.json', json.dumps({'a': 1})), AGED)
    status = cleanup_state(str(tmp_path), mode='report')
    paths = _paths(status)
    assert paths, 'expected non-empty clutter_candidates'
    assert paths == sorted(paths)
    assert status.ready is False
    expected = {'stale_doc.md', '_autowork_scratch/junk.md', 'state/planning/plan_x.json'}
    assert expected.issubset(set(paths))

def test_clutter_candidates_sorted_by_path_deterministic(tmp_path):
    for name in ['zeta_doc.md', 'alpha_doc.md', 'mid_doc.md']:
        _age(_write(tmp_path / name, 'x'), AGED)
    first = cleanup_state(str(tmp_path), mode='report')
    second = cleanup_state(str(tmp_path), mode='report')
    p1 = _paths(first)
    p2 = _paths(second)
    assert p1 == sorted(p1)
    assert p1 == p2
    assert {'alpha_doc.md', 'mid_doc.md', 'zeta_doc.md'}.issubset(set(p1))

def test_apply_populates_clutter_without_moving(tmp_path):
    old = _age(_write(tmp_path / '_autowork_scratch' / 'old.md', 'x'), AGED)
    report = cleanup_state(str(tmp_path), mode='report')
    applied = cleanup_state(str(tmp_path), mode='apply')
    assert _paths(report) == _paths(applied)
    assert _reasons_by_path(applied).get('_autowork_scratch/old.md') == 'scratch_aged'
    assert old.exists()

def test_clean_root_report_has_empty_clutter_ready_unchanged(tmp_path):
    status = cleanup_state(str(tmp_path), mode='report')
    assert status.clutter_candidates == []
    assert status.ready is True

def test_clean_root_apply_does_not_move_anything_ready_unchanged(tmp_path):
    keep = _age(_write(tmp_path / 'README.md', 'k'), AGED)
    status = cleanup_state(str(tmp_path), mode='apply')
    assert status.clutter_candidates == []
    assert status.ready is True
    assert keep.exists()