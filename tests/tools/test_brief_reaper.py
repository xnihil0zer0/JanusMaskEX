"""RED oracle for tools/brief_reaper.py -- the archive-on-integrate reaper.

Contract under test (tools.brief_reaper.reap_for_task):

    reap_for_task(repo_root, task_id, *, stamp, archive=True) -> list[str]

    Archive the brief+plan for ``task_id`` IFF its plan is fully integrated:
      - locate the plan_hooks_<slug>.json at repo_root whose 'tasks' contains a
        task whose task_id == task_id;  none found -> return []
      - if the brief brief_hooks_<slug>.md declares ``epic: true`` -> return []
        (epics are decomposed via children and are NEVER reaped)
      - collect the DISTINCT verification_command across that plan's tasks and run
        each at repo_root; if ALL exit 0 (green) the brief is integrated:
          * archive=True  -> move brief_hooks_<slug>.md + plan_hooks_<slug>.json
                             into repo_root/_autowork_archive/<stamp>/reconciled/
                             and return [slug]
          * archive=False -> classify only (return [slug], move nothing)
        if ANY command is non-zero (red) -> return [] (still building)
      - fail-safe: ANY error (missing repo, malformed plan, bad task) -> return []
        and NEVER raise.

These tests construct a throwaway repo_root under tmp_path with a brief, a plan,
and trivial ``python -c sys.exit(N)`` verification commands so they are fast and
hermetic (no pytest-in-pytest).
"""
import json
import sys
import pathlib

import pytest

# Direct import -- RED until tools/brief_reaper.py lands (collection ImportError
# makes pytest exit non-zero, which is what the gate's oracle_is_red asserts).
import tools.brief_reaper as reaper


def _green(exit_code: int) -> str:
    """A verification_command that exits with the given code."""
    return f'{sys.executable} -c "import sys; sys.exit({exit_code})"'


def _seed(repo, slug, *, exit_code=0, epic=False, n_tasks=1, task_ids=None):
    """Write a brief + plan pair into ``repo`` and return the task ids."""
    fm = '---\nepic: true\n---\n\n' if epic else ''
    (repo / f'brief_hooks_{slug}.md').write_text(
        f'{fm}# Title\n\n{slug}\n', encoding='utf-8')
    ids = task_ids or [f'{slug}-{i}' for i in range(n_tasks)]
    plan = {'tasks': [{'task_id': tid,
                       'verification_command': _green(exit_code)} for tid in ids]}
    (repo / f'plan_hooks_{slug}.json').write_text(json.dumps(plan), encoding='utf-8')
    return ids


def test_green_single_task_brief_is_archived(tmp_path):
    ids = _seed(tmp_path, 'feat-a', exit_code=0)
    out = reaper.reap_for_task(tmp_path, ids[0], stamp='2026-06-08')
    assert out == ['feat-a']
    # source pair is gone from root; landed under reconciled/
    assert not (tmp_path / 'brief_hooks_feat-a.md').exists()
    assert not (tmp_path / 'plan_hooks_feat-a.json').exists()
    dest = tmp_path / '_autowork_archive' / '2026-06-08' / 'reconciled'
    assert (dest / 'brief_hooks_feat-a.md').exists()
    assert (dest / 'plan_hooks_feat-a.json').exists()


def test_red_oracle_is_not_archived(tmp_path):
    ids = _seed(tmp_path, 'feat-b', exit_code=1)
    out = reaper.reap_for_task(tmp_path, ids[0], stamp='2026-06-08')
    assert out == []
    assert (tmp_path / 'brief_hooks_feat-b.md').exists()
    assert (tmp_path / 'plan_hooks_feat-b.json').exists()


def test_epic_brief_is_never_reaped(tmp_path):
    ids = _seed(tmp_path, 'feat-epic', exit_code=0, epic=True)
    out = reaper.reap_for_task(tmp_path, ids[0], stamp='2026-06-08')
    assert out == []
    assert (tmp_path / 'brief_hooks_feat-epic.md').exists()


def test_unknown_task_id_is_a_noop(tmp_path):
    _seed(tmp_path, 'feat-c', exit_code=0)
    out = reaper.reap_for_task(tmp_path, 'no-such-task', stamp='2026-06-08')
    assert out == []
    assert (tmp_path / 'brief_hooks_feat-c.md').exists()


def test_multi_task_plan_archived_only_when_all_green(tmp_path):
    # one plan, two tasks; integrating one of them still reaps the brief because
    # all of the plan's verification commands are green.
    ids = _seed(tmp_path, 'feat-d', exit_code=0, n_tasks=2)
    out = reaper.reap_for_task(tmp_path, ids[1], stamp='2026-06-08')
    assert out == ['feat-d']
    assert not (tmp_path / 'plan_hooks_feat-d.json').exists()


def test_archive_false_classifies_without_moving(tmp_path):
    ids = _seed(tmp_path, 'feat-e', exit_code=0)
    out = reaper.reap_for_task(tmp_path, ids[0], stamp='2026-06-08', archive=False)
    assert out == ['feat-e']
    # nothing moved
    assert (tmp_path / 'brief_hooks_feat-e.md').exists()
    assert (tmp_path / 'plan_hooks_feat-e.json').exists()


def test_failsafe_on_malformed_plan(tmp_path):
    (tmp_path / 'plan_hooks_bad.json').write_text('{not json', encoding='utf-8')
    (tmp_path / 'brief_hooks_bad.md').write_text('# Title\n', encoding='utf-8')
    # must not raise; simply finds no matching task
    assert reaper.reap_for_task(tmp_path, 'anything', stamp='2026-06-08') == []


def test_failsafe_on_missing_repo(tmp_path):
    missing = tmp_path / 'does-not-exist'
    assert reaper.reap_for_task(missing, 'x', stamp='2026-06-08') == []
