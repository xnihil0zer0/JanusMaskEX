"""Parity oracle for ``harness.state_reconciler.reap_spent_briefs``.

This is a verification oracle (a pytest test file), NOT an implementation. It
exercises the LIVE ``reap_spent_briefs`` against real ``tmp_path`` workspaces and
proves the three divergent reaper cases that MUST be skipped even when every task
they list carries an ``accepted`` ledger row:

* (c) REJECT_ROLLBACK -- a plan whose tasks were accepted but one was later
      ``reject_rollback``'d is no longer spent and must be left in place.
* (d) EPIC            -- a plan/brief declared ``epic: true`` is a long-lived
      container and must never be reaped.
* (e) BRIEF-LESS      -- a plan with no paired ``brief_hooks_<slug>.md`` has no
      pair to archive and must be skipped.

Positive and negative controls anchor the oracle so it is non-vacuous in both
directions: a fully-accepted, non-epic, brief-paired plan IS reaped (moved out of
root into ``_autowork_archive``), while a partially-accepted plan and a plan with
no ledger at all are skipped. Each scenario is built from real files/ledgers under
a pytest-provided ``tmp_path`` and checks both the returned slug list AND the
on-disk effect.
"""
import json
from harness.state_reconciler import reap_spent_briefs

def _accepted_row(task_id):
    """A canonical impl_progress ``accepted`` row for ``task_id``."""
    return {'task_id': task_id, 'phase': 'accepted', 'event': 'auto_commit', 'commit_sha': '1' * 40, 'ts': '2026-06-20T00:00:00Z'}

def _reject_rollback_row(task_id):
    """A later ``reject_rollback`` row that undoes a prior acceptance."""
    return {'task_id': task_id, 'phase': 'rejected', 'event': 'reject_rollback', 'ts': '2026-06-20T01:00:00Z'}

def _write_ledger(root, rows):
    """Write ``<root>/state/impl_progress.jsonl`` from ``rows`` (one JSON/line)."""
    state_dir = root / 'state'
    state_dir.mkdir(parents=True, exist_ok=True)
    ledger = state_dir / 'impl_progress.jsonl'
    ledger.write_text(''.join((json.dumps(r) + '\n' for r in rows)), encoding='utf-8')
    return ledger

def _write_plan(root, slug, task_ids, *, epic=False):
    """Write ``<root>/plan_hooks_<slug>.json`` listing ``task_ids``."""
    plan = root / ('plan_hooks_%s.json' % slug)
    payload = {'source_brief_sha256': '0' * 64, 'epic': epic, 'tasks': [{'task_id': t} for t in task_ids]}
    plan.write_text(json.dumps(payload), encoding='utf-8')
    return plan

def _write_brief(root, slug, *, epic=False):
    """Write the paired ``<root>/brief_hooks_<slug>.md``."""
    brief = root / ('brief_hooks_%s.md' % slug)
    header = '---\nepic: true\n---\n' if epic else ''
    brief.write_text('%s# brief %s\n' % (header, slug), encoding='utf-8')
    return brief

def _archived_names(root):
    """Set of file names that landed anywhere under ``_autowork_archive``."""
    archive = root / '_autowork_archive'
    if not archive.exists():
        return set()
    return {p.name for p in archive.rglob('*') if p.is_file()}

def test_reap_spent_briefs_reject_rollback_skipped(tmp_path):
    slug = 'demo'
    plan = _write_plan(tmp_path, slug, ['t1', 't2'])
    brief = _write_brief(tmp_path, slug)
    _write_ledger(tmp_path, [_accepted_row('t1'), _accepted_row('t2'), _reject_rollback_row('t1')])
    reaped = reap_spent_briefs(tmp_path)
    assert slug not in reaped, "a reject_rollback'd plan must not be reaped"
    assert plan.exists(), 'rolled-back plan must be left in place'
    assert brief.exists(), 'paired brief must be left in place'
    assert 'plan_hooks_demo.json' not in _archived_names(tmp_path)

def test_reap_spent_briefs_epic_skipped(tmp_path):
    slug = 'epicdemo'
    plan = _write_plan(tmp_path, slug, ['t1'], epic=True)
    brief = _write_brief(tmp_path, slug, epic=True)
    _write_ledger(tmp_path, [_accepted_row('t1')])
    reaped = reap_spent_briefs(tmp_path)
    assert slug not in reaped, 'an epic plan must never be reaped'
    assert plan.exists(), 'epic plan must be left in place'
    assert brief.exists(), 'epic brief must be left in place'
    assert 'plan_hooks_epicdemo.json' not in _archived_names(tmp_path)

def test_reap_spent_briefs_briefless_skipped(tmp_path):
    slug = 'demo'
    plan = _write_plan(tmp_path, slug, ['t1'])
    _write_ledger(tmp_path, [_accepted_row('t1')])
    brief = tmp_path / 'brief_hooks_demo.md'
    assert not brief.exists(), 'fixture must leave the plan brief-less'
    reaped = reap_spent_briefs(tmp_path)
    assert slug not in reaped, 'a brief-less plan has no pair to reap'
    assert plan.exists(), 'brief-less plan must be left in place'
    assert 'plan_hooks_demo.json' not in _archived_names(tmp_path)

def test_reap_spent_briefs_fully_accepted_pair_reaped(tmp_path):
    slug = 'spent'
    plan = _write_plan(tmp_path, slug, ['t1', 't2'])
    brief = _write_brief(tmp_path, slug)
    _write_ledger(tmp_path, [_accepted_row('t1'), _accepted_row('t2')])
    reaped = reap_spent_briefs(tmp_path)
    assert slug in reaped, 'a fully-accepted brief-paired plan must be reaped'
    assert not plan.exists(), 'spent plan must be moved out of root'
    assert not brief.exists(), 'spent brief must be moved out of root'
    archived = _archived_names(tmp_path)
    assert 'plan_hooks_spent.json' in archived
    assert 'brief_hooks_spent.md' in archived

def test_reap_spent_briefs_partial_acceptance_skipped(tmp_path):
    slug = 'demo'
    plan = _write_plan(tmp_path, slug, ['t1', 't2'])
    brief = _write_brief(tmp_path, slug)
    _write_ledger(tmp_path, [_accepted_row('t1')])
    reaped = reap_spent_briefs(tmp_path)
    assert slug not in reaped, 'a partially-integrated plan must be left in place'
    assert plan.exists()
    assert brief.exists()

def test_reap_spent_briefs_missing_ledger_skipped(tmp_path):
    slug = 'demo'
    plan = _write_plan(tmp_path, slug, ['t1'])
    brief = _write_brief(tmp_path, slug)
    reaped = reap_spent_briefs(tmp_path)
    assert reaped == [], 'with no ledger nothing is accepted, so nothing is reaped'
    assert plan.exists(), 'plan must survive a missing ledger'
    assert brief.exists(), 'brief must survive a missing ledger'