"""Adversarial oracle for DAEMON-STAMP-PASS (REV22 §4-2).

Pins the seam3->seam4 connection: ``harness.autowork_daemon._auto_promote``
must read the TRUSTED top-level ``working_dir`` stamp from the plan JSON and
forward it to ``stage_task(..., working_dir=<stamp>)``. ``stage_task`` already
(a) strips any LLM-authored ``working_dir`` from the task dict (staging.py:62)
and (b) re-injects the trusted kw-only value when not None (staging.py:63-64).

Contracts:

1. POSITIVE (RED on HEAD): a plan with a top-level ``working_dir`` stamp ->
   the staged task JSON carries exactly that value. On HEAD the daemon calls
   ``stage_task(plan_path, tid, state_dir, canonical=True)`` with no
   ``working_dir``, so the trusted stamp never reaches the staged task and the
   assertion FAILS.

2. NEGATIVE (passes on HEAD and after fix): a plan whose *task dict* carries an
   LLM-injected ``working_dir`` but with NO top-level stamp -> the staged task
   must NOT carry ``working_dir`` (it is stripped, and nothing trusted replaces
   it).

3. CAPTURE (RED on HEAD): monkeypatch ``stage_task`` to record the kwargs the
   daemon passes, drive ``_auto_promote``, and assert the daemon forwarded
   ``working_dir`` equal to the plan's top-level stamp. On HEAD no such kwarg is
   passed.

The oracle drives the REAL daemon code path (``_auto_promote(repo_root,
state_dir)``) using the same fixture shape as
``tests/adversarial/test_autowork_auto_promote.py``.
"""
from __future__ import annotations
import json
import pathlib
import pytest


@pytest.fixture
def repo_state(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    repo_root = tmp_path / 'repo'
    repo_root.mkdir()
    state_dir = tmp_path / 'state'
    (state_dir / 'tasks').mkdir(parents=True)
    (state_dir / 'tasks' / 'processed').mkdir()
    (state_dir / 'tasks' / 'blocked').mkdir()
    (state_dir / 'control' / 'autowork').mkdir(parents=True)
    return (repo_root, state_dir)


def _write_brief_and_plan(repo_root: pathlib.Path, state_dir: pathlib.Path,
                          slug: str, plan_data: dict) -> None:
    (repo_root / f'brief_hooks_{slug}.md').write_text(
        f'# Demo brief for {slug}\n', encoding='utf-8')
    (state_dir / 'control' / 'autowork' / 'auto_promote.allowlist').write_text(
        f'{slug}\n', encoding='utf-8')
    (repo_root / f'plan_hooks_{slug}.json').write_text(
        json.dumps(plan_data), encoding='utf-8')


def test_daemon_forwards_stamped_working_dir(repo_state, monkeypatch) -> None:
    """POSITIVE: a top-level plan stamp must survive onto the staged task.

    RED on HEAD: the daemon does not pass working_dir, so stage_task strips
    everything and the staged task lacks the trusted value.
    """
    repo_root, state_dir = repo_state
    plan_data = {
        'slug': 'stamp_pos',
        'brief': 'brief_hooks_stamp_pos.md',
        'working_dir': '/trusted/external/target',
        'tasks': [{'task_id': 'STAMP_POS_TASK', 'files_touched': ['x.py']}],
    }
    _write_brief_and_plan(repo_root, state_dir, 'stamp_pos', plan_data)
    monkeypatch.chdir(repo_root)
    from harness.autowork_daemon import _auto_promote
    _auto_promote(repo_root, state_dir)
    staged_path = state_dir / 'tasks' / 'STAMP_POS_TASK.json'
    assert staged_path.exists(), f'task not staged at {staged_path}'
    staged = json.loads(staged_path.read_text(encoding='utf-8'))
    assert staged.get('working_dir') == '/trusted/external/target', (
        'daemon did not forward the trusted top-level working_dir stamp to '
        f'stage_task; staged task working_dir={staged.get("working_dir")!r}'
    )


def test_daemon_strips_llm_task_working_dir_without_stamp(repo_state, monkeypatch) -> None:
    """NEGATIVE: an LLM-injected task-dict working_dir with NO top-level stamp
    must be stripped from the staged task. Holds on HEAD and after fix."""
    repo_root, state_dir = repo_state
    plan_data = {
        'slug': 'stamp_neg',
        'brief': 'brief_hooks_stamp_neg.md',
        'tasks': [{
            'task_id': 'STAMP_NEG_TASK',
            'working_dir': '/evil/llm/injected',
            'files_touched': ['x.py'],
        }],
    }
    _write_brief_and_plan(repo_root, state_dir, 'stamp_neg', plan_data)
    monkeypatch.chdir(repo_root)
    from harness.autowork_daemon import _auto_promote
    _auto_promote(repo_root, state_dir)
    staged_path = state_dir / 'tasks' / 'STAMP_NEG_TASK.json'
    assert staged_path.exists(), f'task not staged at {staged_path}'
    staged = json.loads(staged_path.read_text(encoding='utf-8'))
    assert 'working_dir' not in staged, (
        'LLM-injected task working_dir was NOT stripped (no top-level stamp '
        f'present); staged working_dir={staged.get("working_dir")!r}'
    )


def test_daemon_passes_working_dir_kwarg_to_stage_task(repo_state, monkeypatch) -> None:
    """CAPTURE: the daemon must call stage_task with working_dir == the plan's
    top-level stamp. RED on HEAD (no such kwarg passed)."""
    repo_root, state_dir = repo_state
    plan_data = {
        'slug': 'stamp_cap',
        'brief': 'brief_hooks_stamp_cap.md',
        'working_dir': '/trusted/captured/dir',
        'tasks': [{'task_id': 'STAMP_CAP_TASK', 'files_touched': ['x.py']}],
    }
    _write_brief_and_plan(repo_root, state_dir, 'stamp_cap', plan_data)
    monkeypatch.chdir(repo_root)
    import harness.autowork_daemon as daemon
    captured: dict = {}
    real_stage_task = daemon.stage_task

    def _capturing_stage_task(plan_path, task_id, state_dir, canonical=True,
                              *, working_dir=None):
        captured['working_dir'] = working_dir
        captured['task_id'] = task_id
        return real_stage_task(plan_path, task_id, state_dir,
                               canonical=canonical, working_dir=working_dir)

    monkeypatch.setattr(daemon, 'stage_task', _capturing_stage_task)
    daemon._auto_promote(repo_root, state_dir)
    assert captured.get('task_id') == 'STAMP_CAP_TASK', (
        f'daemon never invoked stage_task for the task; captured={captured!r}'
    )
    assert captured.get('working_dir') == '/trusted/captured/dir', (
        'daemon did not forward the top-level working_dir stamp as the '
        f'stage_task kw-only param; captured working_dir={captured.get("working_dir")!r}'
    )


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q', '-p', 'no:cacheprovider']))
