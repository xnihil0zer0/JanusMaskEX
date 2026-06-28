"""Hermetic, offline oracle for the spent-brief catch-up reap.

This is a verification oracle (a pytest TEST file), NOT an implementation.

It drives the REAL :func:`harness.state_reconciler.reap_orphaned_workdirs`
over a synthetic root built entirely under pytest ``tmp_path`` (no real repo,
no network, no git) and proves that the orphaned-workdir sweep ALSO performs a
catch-up reap of every fully-accepted ``brief_hooks_<slug>.md`` +
``plan_hooks_<slug>.json`` pair -- allowlist-independent, a MOVE (never a
delete) into ``<root>/_autowork_archive/<today-iso>/reconciled/`` -- while
leaving partially-accepted and epic pairs untouched and preserving the
list-return / never-raise / idempotent contract.

RED on HEAD: today ``reap_orphaned_workdirs`` does NOT catch-up reap spent
briefs (only ``reap_stale_disk`` does), so the all-accepted (slug=spent) and
de-slugged-but-spent (slug=deslugged) cases FAIL until the catch-up step is
wired into the sweep.

Spent-ness is decided from ``<root>/state/impl_progress.jsonl`` via the
ordered ledger replay in ``tools.brief_reaper`` (a ``phase == "accepted"`` row
counts a task id as integrated); the archive MOVE itself is performed by
``tools.brief_reaper.reap_for_task`` which fail-safe-skips epic and brief-less
plans. Assertions inspect ONLY the filesystem MOVE (``Path.exists()``), never
git index state, because ``reap_for_task``'s ``git rm --cached`` is best-effort
and swallows the not-a-repo error in a synthetic root.
"""
import datetime
import json
from pathlib import Path
import pytest
from harness.state_reconciler import reap_orphaned_workdirs

def _accepted_row(tid):
    """One integration-ledger row marking ``tid`` accepted/auto-committed."""
    return {'phase': 'accepted', 'event': 'auto_commit', 'task_id': tid, 'commit_sha': '0' * 40}

def _ensure_state(root) -> Path:
    """Create and return ``<root>/state/`` (the ledger + lock directory)."""
    state_dir = Path(root) / 'state'
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir

def _write_ledger(root, rows) -> Path:
    """Hand-write ``<root>/state/impl_progress.jsonl`` one JSON object per line."""
    state_dir = _ensure_state(root)
    ledger = state_dir / 'impl_progress.jsonl'
    ledger.write_text(''.join((json.dumps(r) + '\n' for r in rows)), encoding='utf-8')
    return ledger

def _plan(root, slug, tids, epic=False) -> Path:
    """Write ``plan_hooks_<slug>.json`` -> {"tasks": [{"task_id": t}, ...]}.

    When ``epic`` is True the JSON boolean ``"epic": true`` (the literal True,
    not the string "true") is added so ``_plan_is_epic`` (``data.get('epic') is
    True``) fires.
    """
    data = {'tasks': [{'task_id': t} for t in tids]}
    if epic:
        data['epic'] = True
    path = Path(root) / ('plan_hooks_%s.json' % slug)
    path.write_text(json.dumps(data), encoding='utf-8')
    return path

def _brief(root, slug, epic=False) -> Path:
    """Write a minimal ``brief_hooks_<slug>.md``.

    For the epic case a leading ``---\\nepic: true\\n---`` frontmatter block is
    prepended so ``_is_epic`` (``^\\s*epic\\s*:\\s*true\\s*$`` between ``---``
    fences) also matches.
    """
    path = Path(root) / ('brief_hooks_%s.md' % slug)
    body = '# Brief for %s\n\nsynthetic hermetic fixture\n' % slug
    if epic:
        body = '---\nepic: true\n---\n' + body
    path.write_text(body, encoding='utf-8')
    return path

def _reconciled_dir(root) -> Path:
    """The dated archive destination the spent-brief reaper moves pairs into."""
    today = datetime.date.today().isoformat()
    return Path(root) / '_autowork_archive' / today / 'reconciled'

def test_all_accepted_pair_is_archived(tmp_path) -> None:
    """(1) Every plan task accepted -> brief+plan MOVED to the dated archive.

    RED on HEAD: ``reap_orphaned_workdirs`` does not yet catch-up reap, so the
    pair stays at root and these "gone from root / present in archive"
    assertions fail.
    """
    root = tmp_path
    _ensure_state(root)
    tids = ['spent-t1', 'spent-t2']
    _write_ledger(root, [_accepted_row(t) for t in tids])
    brief = _brief(root, 'spent')
    plan = _plan(root, 'spent', tids)
    assert brief.exists() and plan.exists()
    result = reap_orphaned_workdirs(root)
    assert isinstance(result, list)
    assert not (root / 'brief_hooks_spent.md').exists()
    assert not (root / 'plan_hooks_spent.json').exists()
    dest = _reconciled_dir(root)
    assert (dest / 'brief_hooks_spent.md').exists()
    assert (dest / 'plan_hooks_spent.json').exists()

def test_partial_pair_left_untouched(tmp_path) -> None:
    """(2) Only one of two plan tasks accepted -> pair left in place at root."""
    root = tmp_path
    _ensure_state(root)
    tids = ['partial-t1', 'partial-t2']
    _write_ledger(root, [_accepted_row('partial-t1')])
    _brief(root, 'partial')
    _plan(root, 'partial', tids)
    result = reap_orphaned_workdirs(root)
    assert isinstance(result, list)
    assert (root / 'brief_hooks_partial.md').exists()
    assert (root / 'plan_hooks_partial.json').exists()
    archive = root / '_autowork_archive'
    if archive.exists():
        assert list(archive.rglob('*partial*')) == []

def test_deslugged_spent_pair_archived_without_allowlist(tmp_path) -> None:
    """(3) All-accepted pair with NO auto_promote allowlist -> still archived.

    RED on HEAD. Reap must NOT depend on the slug being allowlisted, so no
    ``state/control/autowork/auto_promote.allowlist`` is created at all.
    """
    root = tmp_path
    _ensure_state(root)
    allowlist = root / 'state' / 'control' / 'autowork' / 'auto_promote.allowlist'
    assert not allowlist.exists()
    tids = ['deslugged-t1', 'deslugged-t2']
    _write_ledger(root, [_accepted_row(t) for t in tids])
    _brief(root, 'deslugged')
    _plan(root, 'deslugged', tids)
    result = reap_orphaned_workdirs(root)
    assert isinstance(result, list)
    assert not (root / 'brief_hooks_deslugged.md').exists()
    assert not (root / 'plan_hooks_deslugged.json').exists()
    dest = _reconciled_dir(root)
    assert (dest / 'brief_hooks_deslugged.md').exists()
    assert (dest / 'plan_hooks_deslugged.json').exists()

def test_epic_pair_never_reaped(tmp_path) -> None:
    """(4) All-accepted epic plan -> never reaped (failsafe), pair stays at root.

    The plan carries the JSON boolean ``epic: true`` AND the brief carries an
    ``epic: true`` frontmatter block, so both ``_plan_is_epic`` and ``_is_epic``
    refuse the reap even though every task id is integrated.
    """
    root = tmp_path
    _ensure_state(root)
    tids = ['epicdemo-t1', 'epicdemo-t2']
    _write_ledger(root, [_accepted_row(t) for t in tids])
    _brief(root, 'epicdemo', epic=True)
    _plan(root, 'epicdemo', tids, epic=True)
    result = reap_orphaned_workdirs(root)
    assert isinstance(result, list)
    assert (root / 'brief_hooks_epicdemo.md').exists()
    assert (root / 'plan_hooks_epicdemo.json').exists()
    archive = root / '_autowork_archive'
    if archive.exists():
        assert list(archive.rglob('*epicdemo*')) == []

def test_returns_list_and_missing_ledger_is_safe(tmp_path) -> None:
    """(5) Returns a list and never raises -- with spent pairs present AND with
    the ledger absent (nothing integrated -> nothing reaped, pair left at root).
    """
    root_a = tmp_path / 'with_ledger'
    root_a.mkdir()
    _ensure_state(root_a)
    tids = ['safe-t1', 'safe-t2']
    _write_ledger(root_a, [_accepted_row(t) for t in tids])
    _brief(root_a, 'safe')
    _plan(root_a, 'safe', tids)
    result_a = reap_orphaned_workdirs(root_a)
    assert isinstance(result_a, list)
    root_b = tmp_path / 'no_ledger'
    root_b.mkdir()
    _ensure_state(root_b)
    assert not (root_b / 'state' / 'impl_progress.jsonl').exists()
    _brief(root_b, 'noledger')
    _plan(root_b, 'noledger', ['noledger-t1', 'noledger-t2'])
    result_b = reap_orphaned_workdirs(root_b)
    assert isinstance(result_b, list)
    assert (root_b / 'brief_hooks_noledger.md').exists()
    assert (root_b / 'plan_hooks_noledger.json').exists()
    archive_b = root_b / '_autowork_archive'
    if archive_b.exists():
        assert list(archive_b.rglob('*noledger*')) == []

def test_second_run_is_idempotent(tmp_path) -> None:
    """(6) A second call after the all-accepted reap reaps nothing further and
    does not raise; the archive is not duplicated.

    RED on HEAD (the first call does not archive on HEAD).
    """
    root = tmp_path
    _ensure_state(root)
    tids = ['idem-t1', 'idem-t2']
    _write_ledger(root, [_accepted_row(t) for t in tids])
    _brief(root, 'idem')
    _plan(root, 'idem', tids)
    first = reap_orphaned_workdirs(root)
    assert isinstance(first, list)
    assert not (root / 'brief_hooks_idem.md').exists()
    assert not (root / 'plan_hooks_idem.json').exists()
    dest = _reconciled_dir(root)
    assert (dest / 'brief_hooks_idem.md').exists()
    assert (dest / 'plan_hooks_idem.json').exists()
    second = reap_orphaned_workdirs(root)
    assert isinstance(second, list)
    assert sorted((p.name for p in dest.iterdir())) == ['brief_hooks_idem.md', 'plan_hooks_idem.json']

def test_property_reap_orphaned_workdirs_always_returns_list(tmp_path) -> None:
    """Across heterogeneous synthetic roots the return value is ALWAYS a list."""
    roots = []
    r_spent = tmp_path / 'spent'
    r_spent.mkdir()
    _ensure_state(r_spent)
    _write_ledger(r_spent, [_accepted_row('ps-1'), _accepted_row('ps-2')])
    _brief(r_spent, 'ps')
    _plan(r_spent, 'ps', ['ps-1', 'ps-2'])
    roots.append(r_spent)
    r_empty = tmp_path / 'empty'
    r_empty.mkdir()
    _ensure_state(r_empty)
    roots.append(r_empty)
    r_noledger = tmp_path / 'noledger'
    r_noledger.mkdir()
    _ensure_state(r_noledger)
    _brief(r_noledger, 'nl')
    _plan(r_noledger, 'nl', ['nl-1', 'nl-2'])
    roots.append(r_noledger)
    r_epic = tmp_path / 'epic'
    r_epic.mkdir()
    _ensure_state(r_epic)
    _write_ledger(r_epic, [_accepted_row('ep-1'), _accepted_row('ep-2')])
    _brief(r_epic, 'ep', epic=True)
    _plan(r_epic, 'ep', ['ep-1', 'ep-2'], epic=True)
    roots.append(r_epic)
    for r in roots:
        out = reap_orphaned_workdirs(r)
        assert isinstance(out, list)

def test_property_catchup_step_never_raises_out(tmp_path) -> None:
    """The catch-up reap step never raises out -- with spent pairs to reap, with
    an absent ledger, and with malformed ledger/plan bytes.
    """
    r_a = tmp_path / 'spent'
    r_a.mkdir()
    _ensure_state(r_a)
    _write_ledger(r_a, [_accepted_row('a-1'), _accepted_row('a-2')])
    _brief(r_a, 'aa')
    _plan(r_a, 'aa', ['a-1', 'a-2'])
    r_b = tmp_path / 'no_ledger'
    r_b.mkdir()
    _ensure_state(r_b)
    _brief(r_b, 'bb')
    _plan(r_b, 'bb', ['b-1', 'b-2'])
    r_c = tmp_path / 'malformed'
    r_c.mkdir()
    state_c = _ensure_state(r_c)
    (state_c / 'impl_progress.jsonl').write_text('{not valid json\n\n', encoding='utf-8')
    (r_c / 'plan_hooks_cc.json').write_text('{ not valid json', encoding='utf-8')
    (r_c / 'brief_hooks_cc.md').write_text('# stub\n', encoding='utf-8')
    for r in (r_a, r_b, r_c):
        try:
            out = reap_orphaned_workdirs(r)
        except Exception as exc:
            pytest.fail('reap_orphaned_workdirs raised for %s: %r' % (r, exc))
        assert isinstance(out, list)

def test_regression_deslugged_spent_still_reaped_no_allowlist(tmp_path) -> None:
    """De-slugged-but-spent pair is STILL reaped when an allowlist exists that
    deliberately omits the slug -- proving the reap is allowlist-independent.

    RED on HEAD.
    """
    root = tmp_path
    _ensure_state(root)
    allow_dir = root / 'state' / 'control' / 'autowork'
    allow_dir.mkdir(parents=True, exist_ok=True)
    (allow_dir / 'auto_promote.allowlist').write_text('some-other-slug\nyet-another\n', encoding='utf-8')
    tids = ['reg-deslugged-1', 'reg-deslugged-2']
    _write_ledger(root, [_accepted_row(t) for t in tids])
    _brief(root, 'deslugged')
    _plan(root, 'deslugged', tids)
    result = reap_orphaned_workdirs(root)
    assert isinstance(result, list)
    assert not (root / 'brief_hooks_deslugged.md').exists()
    assert not (root / 'plan_hooks_deslugged.json').exists()
    dest = _reconciled_dir(root)
    assert (dest / 'brief_hooks_deslugged.md').exists()
    assert (dest / 'plan_hooks_deslugged.json').exists()

def test_regression_epic_failsafe_holds_via_catchup_path(tmp_path) -> None:
    """The epic failsafe holds through the catch-up path: an all-accepted epic
    pair (plan boolean + brief frontmatter) is never archived.
    """
    root = tmp_path
    _ensure_state(root)
    tids = ['reg-epic-1', 'reg-epic-2']
    _write_ledger(root, [_accepted_row(t) for t in tids])
    _brief(root, 'epicdemo', epic=True)
    _plan(root, 'epicdemo', tids, epic=True)
    result = reap_orphaned_workdirs(root)
    assert isinstance(result, list)
    assert (root / 'brief_hooks_epicdemo.md').exists()
    assert (root / 'plan_hooks_epicdemo.json').exists()
    archive = root / '_autowork_archive'
    if archive.exists():
        assert list(archive.rglob('*epicdemo*')) == []