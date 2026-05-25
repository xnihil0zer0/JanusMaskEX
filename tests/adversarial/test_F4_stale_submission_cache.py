"""Adversarial coverage for F4 — stale submission cache rejection on task re-dispatch.

W85b observed that re-dispatching the same task_id let the orchestrator reuse
session submission files from a prior dispatch (poll_for_submission has no
mtime/staleness check), so agents were spawned but their submissions were
already on disk and the round completed in ~2 seconds with no synthesis.

The fix: ``get_next_task`` clears ``state/sessions/*_<task_id>_submission.json``
at task-claim time (after the ``.json.processing`` rename succeeds). These
tests pin that contract.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from harness import orchestrator  # noqa: E402


def _setup_task(state_dir: pathlib.Path, task_id: str) -> pathlib.Path:
    tasks_dir = state_dir / 'tasks'
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / 'sessions').mkdir(parents=True, exist_ok=True)
    task_path = tasks_dir / f'{task_id}.json'
    task_path.write_text(json.dumps({
        'task_id': task_id,
        'specification': 'noop',
    }))
    return task_path


def test_stale_submissions_cleared_on_task_claim(tmp_path):
    """get_next_task unlinks prior-round submissions before returning the task."""
    state_dir = tmp_path / 'state'
    _setup_task(state_dir, 'F4-A')
    sessions = state_dir / 'sessions'
    stale1 = sessions / 'claude_round1_F4-A_submission.json'
    stale2 = sessions / 'gemini_round1_F4-A_submission.json'
    stale3 = sessions / 'claude_round2_F4-A_submission.json'
    for s in (stale1, stale2, stale3):
        s.write_text(json.dumps({'code': 'STALE'}))

    task = orchestrator.get_next_task(state_dir)

    assert task is not None and task['task_id'] == 'F4-A'
    assert not stale1.exists()
    assert not stale2.exists()
    assert not stale3.exists()


def test_unrelated_task_submissions_survive(tmp_path):
    """Submissions for OTHER task_ids must not be unlinked."""
    state_dir = tmp_path / 'state'
    _setup_task(state_dir, 'F4-B')
    sessions = state_dir / 'sessions'
    own = sessions / 'claude_round1_F4-B_submission.json'
    other = sessions / 'claude_round1_F4-OTHER_submission.json'
    own.write_text(json.dumps({'code': 'OLD'}))
    other.write_text(json.dumps({'code': 'KEEP'}))

    orchestrator.get_next_task(state_dir)

    assert not own.exists()
    assert other.exists()


def test_feedback_files_survive(tmp_path):
    """Glob must not match the feedback-filename suffix."""
    state_dir = tmp_path / 'state'
    _setup_task(state_dir, 'F4-C')
    sessions = state_dir / 'sessions'
    submission = sessions / 'claude_round1_F4-C_submission.json'
    feedback = sessions / 'F4-C_round1_claude_feedback.json'
    submission.write_text(json.dumps({'code': 'OLD'}))
    feedback.write_text(json.dumps({'verdict': 'reject'}))

    orchestrator.get_next_task(state_dir)

    assert not submission.exists()
    assert feedback.exists()


def test_clear_helper_handles_missing_sessions_dir(tmp_path):
    """No state/sessions/ on disk must not raise."""
    state_dir = tmp_path / 'state'
    (state_dir / 'tasks').mkdir(parents=True)
    orchestrator._clear_stale_submissions(state_dir, 'NOPE')


def test_no_stale_files_is_noop(tmp_path):
    """Empty sessions/ dir is fine; subsequent task fetch still succeeds."""
    state_dir = tmp_path / 'state'
    _setup_task(state_dir, 'F4-D')

    task = orchestrator.get_next_task(state_dir)

    assert task is not None and task['task_id'] == 'F4-D'
