"""RED oracle for tools/brief_reaper.py -- the archive-on-integrate reaper (v2).

Contract under test (tools.brief_reaper.reap_for_task):

    reap_for_task(repo_root, task_id, *, stamp, archive=True) -> list[str]

    Archive the brief+plan for ``task_id`` IFF the brief's WHOLE plan is now
    integrated, where "integrated" is GROUND-TRUTH EVIDENCE -- NOT a re-run of
    verification commands. The reaper NEVER executes a plan's
    ``verification_command`` (no ``shell=True``, no subprocess of plan data):
    that was a v1 defect (premature archive on a green-but-unbuilt sibling,
    shell injection, command side-effects re-run on the hot accept path).

    A task is "integrated" iff EITHER:
      * the task being reaped (the ``task_id`` argument) -- it is being reaped
        precisely because it was just accepted, so it counts implicitly; OR
      * the repo's integration ledger ``<repo_root>/state/impl_progress.jsonl``
        carries a terminal row for that task_id with ``phase == 'accepted'``
        (an auto_commit integrate) or ``event == 'no_diff'`` (the brief was
        already satisfied -- genuinely DONE, the class v1 missed).

    Reap rules:
      - locate the plan_hooks_<slug>.json at repo_root whose 'tasks' contains
        task_id AND which has a paired brief_hooks_<slug>.md. If there is not
        EXACTLY ONE such plan (zero, or an ambiguous shared task_id across
        several brief-paired plans) -> return [] (never archive the wrong
        brief).
      - if the brief declares ``epic: true``, OR the plan declares
        ``plan_kind == 'epic'`` / ``epic: true`` (a decomposition record) ->
        return [] (epics and decomposition records are NEVER reaped).
      - a plan with NO paired brief is not reap_for_task's concern -> return []
        (orphan-plan archival lives in the brief_status sweep).
      - reap IFF EVERY task_id in the plan is integrated (per the rule above);
        if any sibling task is not yet integrated -> return [] (no premature
        archive).
          * archive=True  -> move brief_hooks_<slug>.md + plan_hooks_<slug>.json
                             into repo_root/_autowork_archive/<stamp>/reconciled/,
                             REFUSING to overwrite an existing destination file
                             (no silent clobber), and return [slug].
          * archive=False -> classify only (return [slug], move nothing).
      - fail-safe: ANY error (missing repo, malformed plan, bad task) -> return
        [] and NEVER raise.

These tests build a throwaway repo_root under tmp_path and seed the integration
ledger directly, so they are fast, hermetic, and never run pytest-in-pytest or
shell out to a plan command.
"""
import json
import sys
import pathlib

import pytest

# Direct import -- the module exists; these assertions are RED against the v1
# (vcmd-re-running) implementation until the v2 ledger-based impl lands.
import tools.brief_reaper as reaper


def _cmd(exit_code: int = 0) -> str:
    return f'{sys.executable} -c "import sys; sys.exit({exit_code})"'


def _seed(repo, slug, *, epic=False, task_ids=None, n_tasks=1,
          plan_kind=None, command=None, with_brief=True):
    """Seed a brief (optional) + plan pair; return the task ids."""
    if with_brief:
        fm = '---\nepic: true\n---\n\n' if epic else ''
        (repo / f'brief_hooks_{slug}.md').write_text(
            f'{fm}# Title\n\n{slug}\n', encoding='utf-8')
    ids = task_ids or [f'{slug}-{i}' for i in range(n_tasks)]
    cmd = command if command is not None else _cmd(0)
    plan = {'tasks': [{'task_id': tid, 'verification_command': cmd}
                      for tid in ids]}
    if plan_kind is not None:
        plan['plan_kind'] = plan_kind
    (repo / f'plan_hooks_{slug}.json').write_text(json.dumps(plan), encoding='utf-8')
    return ids


def _ledger(repo, *rows):
    """Append integration ledger rows to <repo>/state/impl_progress.jsonl."""
    sd = repo / 'state'
    sd.mkdir(parents=True, exist_ok=True)
    with (sd / 'impl_progress.jsonl').open('a', encoding='utf-8') as fh:
        for row in rows:
            fh.write(json.dumps(row) + '\n')


def _accepted(task_id):
    return {'event': 'auto_commit', 'phase': 'accepted', 'task_id': task_id, 'exit': 0}


def _no_diff(task_id):
    return {'event': 'no_diff', 'task_id': task_id}


def _dest(repo, stamp='2026-06-08'):
    return repo / '_autowork_archive' / stamp / 'reconciled'


# --- single-task: the just-accepted task counts implicitly ------------------

def test_single_task_archived_on_its_own_accept(tmp_path):
    # No ledger row needed: the reaped task is the one that just integrated.
    ids = _seed(tmp_path, 'feat-a', n_tasks=1)
    out = reaper.reap_for_task(tmp_path, ids[0], stamp='2026-06-08')
    assert out == ['feat-a']
    assert not (tmp_path / 'brief_hooks_feat-a.md').exists()
    assert not (tmp_path / 'plan_hooks_feat-a.json').exists()
    assert (_dest(tmp_path) / 'brief_hooks_feat-a.md').exists()
    assert (_dest(tmp_path) / 'plan_hooks_feat-a.json').exists()


# --- per-task evidence: no premature archive on a pending sibling -----------

def test_premature_archive_blocked_when_sibling_unintegrated(tmp_path):
    # Two-task plan; integrate only the first. The sibling has no integration
    # evidence, so the brief MUST NOT be reaped (the core v1 defect).
    ids = _seed(tmp_path, 'feat-b', n_tasks=2)
    out = reaper.reap_for_task(tmp_path, ids[0], stamp='2026-06-08')
    assert out == []
    assert (tmp_path / 'brief_hooks_feat-b.md').exists()
    assert (tmp_path / 'plan_hooks_feat-b.json').exists()


def test_archived_when_all_tasks_integrated(tmp_path):
    ids = _seed(tmp_path, 'feat-c', n_tasks=2)
    _ledger(tmp_path, _accepted(ids[1]))   # sibling integrated via ledger
    out = reaper.reap_for_task(tmp_path, ids[0], stamp='2026-06-08')
    assert out == ['feat-c']
    assert not (tmp_path / 'plan_hooks_feat-c.json').exists()


def test_no_diff_sibling_counts_as_integrated(tmp_path):
    # A no_diff terminal means the brief was already satisfied -- it is DONE.
    ids = _seed(tmp_path, 'feat-d', n_tasks=2)
    _ledger(tmp_path, _no_diff(ids[1]))
    out = reaper.reap_for_task(tmp_path, ids[0], stamp='2026-06-08')
    assert out == ['feat-d']
    assert not (tmp_path / 'plan_hooks_feat-d.json').exists()


# --- epics / decomposition records are never reaped -------------------------

def test_epic_brief_is_never_reaped(tmp_path):
    ids = _seed(tmp_path, 'feat-epic', n_tasks=1, epic=True)
    out = reaper.reap_for_task(tmp_path, ids[0], stamp='2026-06-08')
    assert out == []
    assert (tmp_path / 'brief_hooks_feat-epic.md').exists()


def test_epic_plan_record_is_never_reaped(tmp_path):
    ids = _seed(tmp_path, 'feat-epicplan', n_tasks=1, plan_kind='epic')
    out = reaper.reap_for_task(tmp_path, ids[0], stamp='2026-06-08')
    assert out == []
    assert (tmp_path / 'plan_hooks_feat-epicplan.json').exists()


# --- shared task_id across plans is ambiguous: never archive the wrong brief -

def test_shared_task_id_is_ambiguous_noop(tmp_path):
    _seed(tmp_path, 'aaa', task_ids=['shared'])
    _seed(tmp_path, 'zzz', task_ids=['shared'])
    out = reaper.reap_for_task(tmp_path, 'shared', stamp='2026-06-08')
    assert out == []
    assert (tmp_path / 'brief_hooks_aaa.md').exists()
    assert (tmp_path / 'brief_hooks_zzz.md').exists()


# --- the reaper NEVER runs a plan's verification_command --------------------

def test_no_plan_command_is_ever_executed(tmp_path):
    sentinel = tmp_path / 'SIDE_EFFECT_RAN'
    side_effect = f'{sys.executable} -c "open(r\'{sentinel}\', \'w\').close()"'
    ids = _seed(tmp_path, 'feat-side', n_tasks=1, command=side_effect)
    reaper.reap_for_task(tmp_path, ids[0], stamp='2026-06-08')
    # If the reaper executed the command, the sentinel would exist. It must not.
    assert not sentinel.exists()


# --- safe moves: never silently overwrite an existing archived copy ---------

def test_dest_collision_is_not_overwritten(tmp_path):
    ids = _seed(tmp_path, 'feat-coll', n_tasks=1)
    dest = _dest(tmp_path)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / 'brief_hooks_feat-coll.md').write_text('SENTINEL-DO-NOT-CLOBBER',
                                                   encoding='utf-8')
    reaper.reap_for_task(tmp_path, ids[0], stamp='2026-06-08')
    assert (dest / 'brief_hooks_feat-coll.md').read_text(encoding='utf-8') == \
        'SENTINEL-DO-NOT-CLOBBER'


# --- classify-only mode ------------------------------------------------------

def test_archive_false_classifies_without_moving(tmp_path):
    ids = _seed(tmp_path, 'feat-e', n_tasks=1)
    out = reaper.reap_for_task(tmp_path, ids[0], stamp='2026-06-08', archive=False)
    assert out == ['feat-e']
    assert (tmp_path / 'brief_hooks_feat-e.md').exists()
    assert (tmp_path / 'plan_hooks_feat-e.json').exists()


# --- orphan plan (no brief) is not reap_for_task's job ----------------------

def test_orphan_plan_without_brief_is_not_reaped(tmp_path):
    ids = _seed(tmp_path, 'feat-orphan', n_tasks=1, with_brief=False)
    _ledger(tmp_path, _accepted(ids[0]))
    out = reaper.reap_for_task(tmp_path, ids[0], stamp='2026-06-08')
    assert out == []
    assert (tmp_path / 'plan_hooks_feat-orphan.json').exists()


# --- fail-safe ---------------------------------------------------------------

def test_unknown_task_id_is_a_noop(tmp_path):
    _seed(tmp_path, 'feat-f', n_tasks=1)
    out = reaper.reap_for_task(tmp_path, 'no-such-task', stamp='2026-06-08')
    assert out == []
    assert (tmp_path / 'brief_hooks_feat-f.md').exists()


def test_failsafe_on_malformed_plan(tmp_path):
    (tmp_path / 'plan_hooks_bad.json').write_text('{not json', encoding='utf-8')
    (tmp_path / 'brief_hooks_bad.md').write_text('# Title\n', encoding='utf-8')
    assert reaper.reap_for_task(tmp_path, 'anything', stamp='2026-06-08') == []


def test_failsafe_on_missing_repo(tmp_path):
    missing = tmp_path / 'does-not-exist'
    assert reaper.reap_for_task(missing, 'x', stamp='2026-06-08') == []
