"""Hermetic RED-union oracle: a ``missing_required_child`` violation makes
``harness.planner.cli._run_epic_pipeline`` validate BEFORE writing anything and
hard-fail.

The brief declares a ``required_child_slugs`` entry that is not among the merged
children; ``validate_plan`` is monkeypatched to surface the corresponding
``PlanViolation(code='missing_required_child')`` so the gate fires. Asserts the
run exits non-zero, stderr names ``code=`` together with the literal
``missing_required_child``, the ``output_plan`` is never persisted, and NO
``brief_hooks_<slug>.md`` child files are written.

RED on HEAD: HEAD writes the child briefs and persists the plan before any
validation and returns 0.
"""
import json
import types
from pathlib import Path
import pytest
from harness.planner import cli
from harness.planner.diff_model import PlanDiff, DiffItem, DiffKind
from harness.planner.plan_validator import PlanViolation
from harness.planner.reconciliation import ReconciliationResult
from harness.planner import brief_loader
CONFIG = {'hierarchical_planning': {'enabled': True}}

def _dirs(tmp_path):
    repo_root = tmp_path / 'repo'
    state_dir = repo_root / 'state'
    repo_root.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    assert state_dir.parent == repo_root
    return (repo_root, state_dir)

def _child(slug, **extra):
    data = {'slug': slug, 'title': 'Title for ' + slug, 'scope': 'Scope for ' + slug + ' describing real work to do.', 'non_goals': 'Non-goals for ' + slug + '.', 'inputs': 'Inputs for ' + slug + '.', 'deliverables': 'Deliverables for ' + slug + '.'}
    data.update(extra)
    return data

def _brief(repo_root, **attrs):
    base = dict(required_task_ids=(), working_dir=None, raw_text='', deliverables='- a deliverable line\n', source_path=str(repo_root / 'brief_hooks_parentepic.md'), required_child_slugs=(), epic=True, sha256='0' * 64)
    base.update(attrs)
    return types.SimpleNamespace(**base)

def _install(monkeypatch, *, merged, recon=None, validate=None, coverage=None):
    import harness.planner.blind_draft as bd
    import harness.planner.diff_extractor as de
    import harness.planner.reconciliation as rc_mod
    import harness.planner.plan_validator as pv
    drafts = types.SimpleNamespace(claude_draft={'plan_kind': 'epic', 'child_briefs': []}, gemini_draft={'plan_kind': 'epic', 'child_briefs': []})
    if recon is None:
        recon = ReconciliationResult(merged_tasks=list(merged), unresolved_items=[], per_agent_errors={'claude': [], 'gemini': []})
    violations = [] if validate is None else list(validate)
    cov = {'covered': [], 'uncovered': [], 'ambiguous': []} if coverage is None else dict(coverage)
    monkeypatch.setattr(bd, 'run_blind_drafts', lambda *a, **k: drafts, raising=False)
    monkeypatch.setattr(de, 'extract_diff', lambda *a, **k: PlanDiff(), raising=False)
    monkeypatch.setattr(rc_mod, 'run_reconciliation', lambda *a, **k: recon, raising=False)
    for _name in ('validate_plan', 'validate_epic_plan', 'validate_child_brief_plan'):
        monkeypatch.setattr(pv, _name, lambda *a, **k: list(violations), raising=False)
        monkeypatch.setattr(cli, _name, lambda *a, **k: list(violations), raising=False)
    monkeypatch.setattr(pv, 'compute_epic_coverage', lambda *a, **k: dict(cov), raising=False)
    monkeypatch.setattr(cli, 'compute_epic_coverage', lambda *a, **k: dict(cov), raising=False)
    return (drafts, recon)

def _child_brief_files(repo_root):
    return sorted(Path(repo_root).glob('brief_hooks_*.md'))

def _missing_required_child_violation():
    return PlanViolation('missing_required_child', 'plan.child_slugs', "required child slug 'missing-child' is declared in required_child_slugs but absent from child_slugs", 'error')

def test_validate_gate_missing_required_child_hardfails(tmp_path, monkeypatch, capsys):
    repo_root, state_dir = _dirs(tmp_path)
    _install(monkeypatch, merged=[_child('present-child')], validate=[_missing_required_child_violation()])
    brief = _brief(repo_root, required_child_slugs=('missing-child',))
    output_plan = state_dir / 'planning' / 'merged_plan.json'
    rc = cli._run_epic_pipeline(brief, CONFIG, state_dir, output_plan)
    err = capsys.readouterr().err
    assert rc != 0
    assert 'code=' in err
    assert 'missing_required_child' in err

def test_validate_gate_no_child_files_written_on_hardfail(tmp_path, monkeypatch):
    repo_root, state_dir = _dirs(tmp_path)
    _install(monkeypatch, merged=[_child('present-child')], validate=[_missing_required_child_violation()])
    brief = _brief(repo_root, required_child_slugs=('missing-child',))
    output_plan = state_dir / 'planning' / 'merged_plan.json'
    rc = cli._run_epic_pipeline(brief, CONFIG, state_dir, output_plan)
    assert rc != 0
    assert _child_brief_files(repo_root) == []

def test_validate_gate_no_plan_persisted_on_hardfail(tmp_path, monkeypatch):
    repo_root, state_dir = _dirs(tmp_path)
    _install(monkeypatch, merged=[_child('present-child')], validate=[_missing_required_child_violation()])
    brief = _brief(repo_root, required_child_slugs=('missing-child',))
    output_plan = state_dir / 'planning' / 'merged_plan.json'
    rc = cli._run_epic_pipeline(brief, CONFIG, state_dir, output_plan)
    assert rc != 0
    assert not output_plan.exists()