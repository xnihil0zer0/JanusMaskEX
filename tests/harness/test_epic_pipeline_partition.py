"""Hermetic RED-union oracle: ``_run_epic_pipeline`` partitions plan violations
by their ``.path`` (NOT by their ``.code``).

Both scenarios use the SAME violation ``code`` but different ``.path``:

* a ``plan.*`` structural violation HARD-FAILS (exit 1, no plan persisted, no
  child files written), while
* a ``child_briefs[...]`` per-child violation is ADVISORY (exit 0, plan
  persisted, a per-child row appended to a state_dir-relative journal).

Because the code is identical across the two runs, a GREEN result can only come
from a ``.path``-based partition. RED on HEAD: HEAD never validates inside the
epic pipeline, so the structural run returns 0 and the advisory run journals
nothing.
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

def _plan_path_violation(code):
    return PlanViolation(code, 'plan.child_slugs', 'structural violation on plan.child_slugs', 'error')

def _child_path_violation(code):
    return PlanViolation(code, 'child_briefs[0].deliverables', 'advisory per-child issue', 'error')

def _references_child(rows):
    texts = [json.dumps(r) for r in rows]
    return any(('child_briefs[0]' in t or 'samecode' in t or 'advisory per-child issue' in t for t in texts))

def test_partition_plan_path_hardfail_vs_child_path_advisory(tmp_path, monkeypatch):
    repo_a = tmp_path / 'a'
    state_a = repo_a / 'state'
    state_a.mkdir(parents=True, exist_ok=True)
    _install(monkeypatch, merged=[_child('alpha-feature')], validate=[_plan_path_violation('samecode')])
    brief_a = _brief(repo_a)
    plan_a = state_a / 'planning' / 'merged_plan.json'
    rc_a = cli._run_epic_pipeline(brief_a, CONFIG, state_a, plan_a)
    assert rc_a == 1
    assert not plan_a.exists()
    assert sorted(Path(repo_a).glob('brief_hooks_*.md')) == []
    repo_b = tmp_path / 'b'
    state_b = repo_b / 'state'
    state_b.mkdir(parents=True, exist_ok=True)
    _install(monkeypatch, merged=[_child('alpha-feature')], validate=[_child_path_violation('samecode')])
    brief_b = _brief(repo_b)
    plan_b = state_b / 'planning' / 'merged_plan.json'
    rc_b = cli._run_epic_pipeline(brief_b, CONFIG, state_b, plan_b)
    assert rc_b == 0
    assert plan_b.exists()
    assert _references_child(_journal_rows(state_b)), 'expected a per-child advisory journal row'

def test_partition_child_path_advisory_persists_plan(tmp_path, monkeypatch):
    repo_root = tmp_path / 'repo'
    state_dir = repo_root / 'state'
    state_dir.mkdir(parents=True, exist_ok=True)
    assert state_dir.parent == repo_root
    _install(monkeypatch, merged=[_child('alpha-feature')], validate=[_child_path_violation('samecode')])
    brief = _brief(repo_root)
    output_plan = state_dir / 'planning' / 'merged_plan.json'
    rc = cli._run_epic_pipeline(brief, CONFIG, state_dir, output_plan)
    assert rc == 0
    assert output_plan.exists()
    assert _references_child(_journal_rows(state_dir))