"""Hermetic RED-union oracle: parent ``required_task_ids`` are inherited onto
every written child brief by ``harness.planner.cli._run_epic_pipeline``.

Drives the REAL ``_run_epic_pipeline`` against a per-test tmp ``repo_root`` with a
``state/`` child as ``state_dir`` (``state_dir.parent == repo_root``). Only the
agent draft / reconciliation stubs are mocked (at their source modules so the
function's local imports pick up the patches); the child markdown is serialized
by the real ``serialize_child_brief_to_markdown`` and re-loaded through the real
``harness.planner.brief_loader.load_brief``.

RED on HEAD: HEAD's pipeline never injects the parent ``required_task_ids`` into
the child dicts, so the reloaded children carry an empty tuple and the assertion
fails. GREEN once the inheritance impl lands.
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
RTI_VALUE = 'epic-rti-1'

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

def _child_brief_files(repo_root):
    return sorted(Path(repo_root).glob('brief_hooks_*.md'))

def test_inherit_required_task_ids_onto_children(tmp_path, monkeypatch):
    repo_root, state_dir = _dirs(tmp_path)
    merged = [_child('alpha-feature'), _child('beta-feature')]
    _install(monkeypatch, merged=merged)
    brief = _brief(repo_root, required_task_ids=(RTI_VALUE,))
    output_plan = state_dir / 'planning' / 'merged_plan.json'
    rc = cli._run_epic_pipeline(brief, CONFIG, state_dir, output_plan)
    assert rc == 0
    child_files = _child_brief_files(repo_root)
    assert len(child_files) >= 2
    for cf in child_files:
        loaded = brief_loader.load_brief(cf)
        assert RTI_VALUE in tuple(loaded.required_task_ids), 'child %s did not inherit parent required_task_ids: %r' % (cf.name, loaded.required_task_ids)

def test_inherit_hermetic_tmp_repo_root_and_state_dir(tmp_path, monkeypatch):
    live_state = Path('state')
    existed = live_state.exists()
    before = sorted((p.name for p in live_state.iterdir())) if existed else None
    repo_root, state_dir = _dirs(tmp_path)
    _install(monkeypatch, merged=[_child('alpha-feature')])
    brief = _brief(repo_root, required_task_ids=(RTI_VALUE,))
    output_plan = state_dir / 'planning' / 'merged_plan.json'
    rc = cli._run_epic_pipeline(brief, CONFIG, state_dir, output_plan)
    assert rc == 0
    assert state_dir.parent == repo_root
    assert output_plan.exists()
    assert str(output_plan).startswith(str(tmp_path))
    for cf in _child_brief_files(repo_root):
        assert str(cf).startswith(str(tmp_path))
    if existed:
        after = sorted((p.name for p in live_state.iterdir()))
        assert after == before
    else:
        assert not live_state.exists()