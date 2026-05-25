"""Adversarial regression bar for AW9 — autowork daemon auto-promote pipeline.

Background: ``harness/autowork_daemon.py:_iteration`` only dispatches pre-staged
``state/tasks/*.json``. It does NOT (a) extract tasks from ``plan_hooks_*.json``
into the queue, nor (b) kick off the planner on briefs lacking a plan. The
WebUI Play button consequently shows running 0/4 against an empty queue even
when 90+ briefs and 80+ plans live in the repo.

This test pins three contracts AW9c is required to satisfy:

1. ``_auto_promote`` stages every ``unstaged_task_ids`` task from a brief's plan
   into ``state/tasks/<task_id>.json`` and emits ``event: extract`` ledger rows.
2. ``_auto_promote`` invokes the planner on at most one unplanned brief per
   iteration and emits an ``event: plan_kickoff`` ledger row on success.
3. ``_auto_promote`` discards planner output classified as a Gemini
   hallucination (wall < 10s OR all-gemini-no-reconciled) and emits an
   ``event: planner_hallucination_discarded`` row instead.

Pattern mirrors session #14 G27/G28: META commit lands the test with
``xfail(strict=False, reason=...)``. AW9c's verification_command runs pytest
with ``--runxfail`` so the markers are bypassed at gate time; the post-AW9c
META commit drops the markers and the tests pass naturally.
"""
from __future__ import annotations
import json
import pathlib
import pytest

@pytest.fixture
def repo_state(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Return ``(repo_root, state_dir)`` with the minimum directory shape
    ``compute_brief_status`` + ``_auto_promote`` expect."""
    repo_root = tmp_path / 'repo'
    repo_root.mkdir()
    state_dir = tmp_path / 'state'
    (state_dir / 'tasks').mkdir(parents=True)
    (state_dir / 'tasks' / 'processed').mkdir()
    (state_dir / 'tasks' / 'blocked').mkdir()
    (state_dir / 'control' / 'autowork').mkdir(parents=True)
    return (repo_root, state_dir)

def _ledger_rows(state_dir: pathlib.Path) -> list[dict]:
    p = state_dir / 'impl_progress.jsonl'
    if not p.exists():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out

def test_iteration_extracts_unstaged_task_from_plan(repo_state, monkeypatch) -> None:
    """A brief with a plan whose tasks are NOT yet staged must be auto-staged."""
    repo_root, state_dir = repo_state
    (repo_root / 'brief_hooks_demo_extract.md').write_text('# Demo brief for extract test\n', encoding='utf-8')
    (state_dir / 'control' / 'autowork' / 'auto_promote.allowlist').write_text('demo_extract\n', encoding='utf-8')
    plan_data = {'slug': 'demo_extract', 'brief': 'brief_hooks_demo_extract.md', 'tasks': [{'task_id': 'DEMO_TASK_FOO', 'files_touched': ['foo.py']}]}
    (repo_root / 'plan_hooks_demo_extract.json').write_text(json.dumps(plan_data), encoding='utf-8')
    monkeypatch.chdir(repo_root)
    from harness.autowork_daemon import _auto_promote
    _auto_promote(repo_root, state_dir)
    expected = state_dir / 'tasks' / 'DEMO_TASK_FOO.json'
    assert expected.exists(), f'_auto_promote did not stage DEMO_TASK_FOO at {expected}'
    staged = json.loads(expected.read_text(encoding='utf-8'))
    assert staged.get('task_id') == 'DEMO_TASK_FOO', f'staged payload missing task_id: {staged!r}'
    extract_rows = [r for r in _ledger_rows(state_dir) if r.get('event') == 'extract']
    assert extract_rows, "expected at least one 'extract' ledger row after _auto_promote"

def test_iteration_kicks_off_planner_for_unplanned_brief(repo_state, monkeypatch) -> None:
    """A brief lacking a plan must trigger a planner kickoff and emit
    ``event: plan_kickoff`` when the planner returns clean (well-attributed
    tasks, wall >= 10s)."""
    repo_root, state_dir = repo_state
    (repo_root / 'brief_hooks_demo_kickoff.md').write_text('# Demo brief for kickoff test\n\nintentionally tiny.\n', encoding='utf-8')
    (state_dir / 'control' / 'autowork' / 'auto_promote.allowlist').write_text('demo_kickoff\n', encoding='utf-8')
    from harness import autowork_daemon

    def fake_run_planner(brief_path, output_plan, state_dir_inner, timeout_sec=120.0):
        plan = {'tasks': [{'task_id': 'DEMO_PLAN_TASK', 'files_touched': ['demo.py'], 'attribution_metadata': {'proposed_by': 'claude', 'reconciled': True}}]}
        output_plan.write_text(json.dumps(plan), encoding='utf-8')
        return (0, 35.0, '')
    monkeypatch.setattr(autowork_daemon, '_run_planner_subprocess', fake_run_planner)
    monkeypatch.chdir(repo_root)
    autowork_daemon._auto_promote(repo_root, state_dir)
    plan_path = repo_root / 'plan_hooks_demo_kickoff.json'
    assert plan_path.exists(), f'_auto_promote did not persist plan at {plan_path}'
    kickoff_rows = [r for r in _ledger_rows(state_dir) if r.get('event') == 'plan_kickoff']
    assert kickoff_rows, "expected at least one 'plan_kickoff' ledger row"

def test_iteration_discards_hallucinated_planner_output(repo_state, monkeypatch) -> None:
    """Planner output with sub-10s wall AND all-gemini-no-reconciled
    attribution MUST be discarded, plan file removed, and
    ``event: planner_hallucination_discarded`` emitted."""
    repo_root, state_dir = repo_state
    (repo_root / 'brief_hooks_demo_halluc.md').write_text('# Demo brief for hallucination test\n', encoding='utf-8')
    (state_dir / 'control' / 'autowork' / 'auto_promote.allowlist').write_text('demo_halluc\n', encoding='utf-8')
    from harness import autowork_daemon

    def fake_hallucinated_planner(brief_path, output_plan, state_dir_inner, timeout_sec=120.0):
        plan = {'tasks': [{'task_id': 'BAD_TASK', 'attribution_metadata': {'proposed_by': 'gemini', 'reconciled': False}}]}
        output_plan.write_text(json.dumps(plan), encoding='utf-8')
        return (0, 2.0, '')
    monkeypatch.setattr(autowork_daemon, '_run_planner_subprocess', fake_hallucinated_planner)
    monkeypatch.chdir(repo_root)
    autowork_daemon._auto_promote(repo_root, state_dir)
    plan_path = repo_root / 'plan_hooks_demo_halluc.json'
    assert not plan_path.exists(), f'_auto_promote did not discard hallucinated plan at {plan_path}'
    discarded_rows = [r for r in _ledger_rows(state_dir) if r.get('event') == 'planner_hallucination_discarded']
    assert discarded_rows, "expected at least one 'planner_hallucination_discarded' ledger row"