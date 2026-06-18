"""Hermetic RED-union oracle: an uncovered epic deliverable is an ADVISORY in
``_run_epic_pipeline`` -- the run still exits 0 and persists the plan, the
persisted epic record carries a ``coverage_check``, and an ``epic_coverage_gap``
row is appended to a state_dir-relative journal.

``compute_epic_coverage`` is monkeypatched to report an uncovered deliverable.
The oracle asserts ONLY the existence of the gap row plus ``exit == 0`` and the
presence of ``coverage_check`` -- never an exact uncovered list.

RED on HEAD: HEAD never computes coverage, so the persisted record lacks
``coverage_check`` and no ``epic_coverage_gap`` row exists.
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

def _journal_rows(state_dir):
    rows = []
    for path in Path(state_dir).rglob('*.jsonl'):
        try:
            content = path.read_text(encoding='utf-8')
        except OSError:
            continue
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows

def test_coverage_gap_advisory_row_and_exit_zero(tmp_path, monkeypatch):
    repo_root, state_dir = _dirs(tmp_path)
    coverage = {'covered': [], 'uncovered': ['- an uncovered deliverable line'], 'ambiguous': []}
    _install(monkeypatch, merged=[_child('alpha-feature')], validate=[], coverage=coverage)
    brief = _brief(repo_root, deliverables='- an uncovered deliverable line\n')
    output_plan = state_dir / 'planning' / 'merged_plan.json'
    rc = cli._run_epic_pipeline(brief, CONFIG, state_dir, output_plan)
    assert rc == 0
    assert output_plan.exists()
    record = json.loads(output_plan.read_text(encoding='utf-8'))
    assert 'coverage_check' in record
    texts = [json.dumps(r) for r in _journal_rows(state_dir)]
    assert any(('epic_coverage_gap' in t for t in texts)), 'expected an epic_coverage_gap journal row: %r' % texts

def test_coverage_advisory_persists_coverage_check(tmp_path, monkeypatch):
    repo_root, state_dir = _dirs(tmp_path)
    coverage = {'covered': [], 'uncovered': ['- uncovered line two'], 'ambiguous': []}
    _install(monkeypatch, merged=[_child('beta-feature')], validate=[], coverage=coverage)
    brief = _brief(repo_root, deliverables='- uncovered line two\n')
    output_plan = state_dir / 'planning' / 'merged_plan.json'
    rc = cli._run_epic_pipeline(brief, CONFIG, state_dir, output_plan)
    assert rc == 0
    record = json.loads(output_plan.read_text(encoding='utf-8'))
    assert 'coverage_check' in record