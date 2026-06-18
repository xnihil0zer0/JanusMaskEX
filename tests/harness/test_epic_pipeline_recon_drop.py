"""Hermetic RED-union oracle: reconciliation ``unresolved_items`` (dropped
children) are journaled by ``_run_epic_pipeline`` as ``epic_child_unresolved``
rows carrying the ``diff_item_id`` and the resolution ``policy``, even while
``merged_tasks`` is non-empty.

``run_reconciliation`` is monkeypatched to return a ``ReconciliationResult`` with
a non-empty ``merged_tasks`` AND one ``DiffItem`` in ``unresolved_items`` plus a
distinctive ``resolution_policy``. The oracle reads the state_dir-relative
journal and asserts a row that names ``epic_child_unresolved`` and carries both
the (real, hash-derived) ``diff_item_id`` and the policy string.

RED on HEAD: HEAD's epic pipeline never inspects ``unresolved_items`` and emits
no such row.
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

def test_recon_drop_logs_epic_child_unresolved(tmp_path, monkeypatch):
    repo_root, state_dir = _dirs(tmp_path)
    item = DiffItem(kind=DiffKind.claude_only, claude_task={'task_id': 'unresolved-task-1'})
    diff_id = item.diff_item_id
    policy = 'flag_for_human'
    recon = ReconciliationResult(merged_tasks=[_child('recon-child')], unresolved_items=[item], per_agent_errors={'claude': [], 'gemini': []}, resolution_policy=policy)
    _install(monkeypatch, merged=[_child('recon-child')], recon=recon)
    brief = _brief(repo_root)
    output_plan = state_dir / 'planning' / 'merged_plan.json'
    rc = cli._run_epic_pipeline(brief, CONFIG, state_dir, output_plan)
    assert rc == 0
    assert recon.merged_tasks
    rows = _journal_rows(state_dir)
    matching = [r for r in rows if 'epic_child_unresolved' in json.dumps(r) and diff_id in json.dumps(r) and (policy in json.dumps(r))]
    assert matching, 'expected an epic_child_unresolved row carrying diff_item_id=%s policy=%s; rows=%r' % (diff_id, policy, rows)

def test_recon_drop_never_touches_live_state_dir(tmp_path, monkeypatch):
    live_state = Path('state')
    existed = live_state.exists()
    before = sorted((p.name for p in live_state.iterdir())) if existed else None
    repo_root, state_dir = _dirs(tmp_path)
    item = DiffItem(kind=DiffKind.claude_only, claude_task={'task_id': 'unresolved-task-2'})
    recon = ReconciliationResult(merged_tasks=[_child('recon-child')], unresolved_items=[item], per_agent_errors={'claude': [], 'gemini': []}, resolution_policy='flag_for_human')
    _install(monkeypatch, merged=[_child('recon-child')], recon=recon)
    brief = _brief(repo_root)
    output_plan = state_dir / 'planning' / 'merged_plan.json'
    cli._run_epic_pipeline(brief, CONFIG, state_dir, output_plan)
    if existed:
        after = sorted((p.name for p in live_state.iterdir()))
        assert after == before
    else:
        assert not live_state.exists()