"""End-to-end (non-vacuous) integration oracle for epic completeness (B1-B8).

This module drives the REAL ``harness.planner.cli._run_epic_pipeline`` end to
end. The ONLY mocked seam is ``harness.planner.blind_draft.run_blind_drafts``
(patched at the module path the pipeline imports it from). Everything else --
``extract_diff``, ``run_reconciliation``, ``_finalize_epic_children``,
``serialize_child_brief_to_markdown``, ``persist_plan``, ``validate_plan`` /
``compute_epic_coverage``, the coverage check, and the dedup / unresolved
logging -- runs for real.

Each test is hermetic: it builds its own ``tmp_path`` repo tree
(``repo_root = tmp_path/'repo'``, ``state_dir = repo_root/'state'`` so
``state_dir.parent == repo_root``), its own mocked drafts, and never reads or
writes the live ``state/`` directory.

The module is RED on HEAD before B1-B8 land -- that is the correct/expected
oracle behavior; it goes GREEN once the epic-completeness contract is in place.
"""
import json
import sys
from types import SimpleNamespace
import pytest

def _setup(tmp_path):
    """Build a hermetic per-case repo tree and return (repo_root, state_dir, output_plan)."""
    repo_root = tmp_path / 'repo'
    state_dir = repo_root / 'state'
    state_dir.mkdir(parents=True)
    output_plan = repo_root / 'merged_plan.json'
    return (repo_root, state_dir, output_plan)

def _child(slug, *, drop=None, extra=None):
    """Build a well-formed child-brief dict.

    Carries the brief-schema required fields (slug/title/scope/non_goals/inputs/
    deliverables) plus working_dir. Deliberately OMITS required_task_ids so that
    the pipeline's inheritance step (Step 2) is what populates them -- making the
    inheritance assertion mutation-sensitive. ``drop`` removes named fields (to
    drive the advisory missing-field case); ``extra`` overrides/augments.
    """
    child = {'slug': slug, 'title': slug + ' title', 'scope': 'scope text for ' + slug, 'non_goals': 'non goals for ' + slug, 'inputs': 'inputs for ' + slug, 'deliverables': 'child deliverable for ' + slug, 'working_dir': '.'}
    if extra:
        child.update(extra)
    if drop:
        for key in drop:
            child.pop(key, None)
    return child

def _make_drafts(claude_children, gemini_children):
    """Return a drafts object exposing .claude_draft and .gemini_draft epic dicts."""
    drafts = SimpleNamespace()
    drafts.claude_draft = {'plan_kind': 'epic', 'child_briefs': list(claude_children)}
    drafts.gemini_draft = {'plan_kind': 'epic', 'child_briefs': list(gemini_children)}
    return drafts

def _patch_drafts(monkeypatch, claude_children, gemini_children):
    """Patch the ONLY mocked seam: run_blind_drafts at its import module path."""

    def _fake_run_blind_drafts(brief_obj, config, state_dir):
        return _make_drafts(claude_children, gemini_children)
    monkeypatch.setattr('harness.planner.blind_draft.run_blind_drafts', _fake_run_blind_drafts)

def _brief(repo_root, *, required_child_slugs, deliverables, required_task_ids, epic_name='myepic'):
    """Build a lightweight brief_obj stub exposing the attributes the pipeline reads."""
    return SimpleNamespace(raw_text='# Epic\n\nDecompose this epic into child briefs.\n', epic=True, working_dir=str(repo_root), required_task_ids=list(required_task_ids), required_child_slugs=list(required_child_slugs), deliverables=deliverables, source_path=str(repo_root / ('brief_hooks_' + epic_name + '.md')), sha256='a' * 64)

def _config(state_dir):
    """Config that enables hierarchical planning and configures fast, hermetic
    stub agents so the REAL run_reconciliation can spawn for a divergent item
    without driving any live agent (each stub exits 0 immediately -> silent ->
    the divergent item becomes an unresolved_item)."""
    return {'state_dir': str(state_dir), 'hierarchical_planning': {'enabled': True}, 'planning_timeout_seconds': 3, 'reconciliation': {'unresolved_policy': 'flag_for_human'}, 'synthesis': {'active_agents': ['stub'], 'antigravity_mode': True, 'timeout_seconds': 3}, 'agents': {'stub': {'command': sys.executable, 'args': ['-c', 'raise SystemExit(0)']}}}

def _run(brief_obj, config, state_dir, output_plan):
    from harness.planner.cli import _run_epic_pipeline
    return _run_epic_pipeline(brief_obj, config, state_dir, output_plan)

def _progress_events(state_dir):
    """Event names from the real planner_progress.jsonl ledger (row-presence only)."""
    return _jsonl_events(state_dir / 'planning' / 'planner_progress.jsonl')

def _dedup_events(state_dir):
    """Event names from the real epic_dedup dropped_children.jsonl ledger."""
    return _jsonl_events(state_dir / 'epic_dedup' / 'dropped_children.jsonl')

def _jsonl_events(path):
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            ev = row.get('event')
            if ev:
                events.append(ev)
    return events

def _brief_hooks_files(repo_root):
    return sorted(repo_root.glob('brief_hooks_*.md'))

def test_a_required_task_ids_inherited_happy_path(tmp_path, monkeypatch):
    repo_root, state_dir, output_plan = _setup(tmp_path)
    children = [_child('alpha'), _child('beta')]
    _patch_drafts(monkeypatch, children, children)
    brief = _brief(repo_root, required_child_slugs=['alpha', 'beta'], deliverables='- alpha module\n- beta module\n', required_task_ids=['task-alpha-1', 'task-beta-2'])
    rc = _run(brief, _config(state_dir), state_dir, output_plan)
    assert rc == 0
    assert output_plan.is_file()
    alpha_md = repo_root / 'brief_hooks_alpha.md'
    beta_md = repo_root / 'brief_hooks_beta.md'
    assert alpha_md.is_file()
    assert beta_md.is_file()
    for md in (alpha_md, beta_md):
        text = md.read_text(encoding='utf-8')
        assert 'task-alpha-1' in text
        assert 'task-beta-2' in text
    plan = json.loads(output_plan.read_text(encoding='utf-8'))
    persisted_children = plan['child_briefs']
    assert len(persisted_children) == 2
    for child in persisted_children:
        assert child.get('required_task_ids') == ['task-alpha-1', 'task-beta-2']

def test_a_plan_persisted_and_brief_hooks_written(tmp_path, monkeypatch):
    repo_root, state_dir, output_plan = _setup(tmp_path)
    children = [_child('alpha'), _child('beta')]
    _patch_drafts(monkeypatch, children, children)
    brief = _brief(repo_root, required_child_slugs=['alpha', 'beta'], deliverables='- alpha module\n- beta module\n', required_task_ids=['task-x'])
    rc = _run(brief, _config(state_dir), state_dir, output_plan)
    assert rc == 0
    plan = json.loads(output_plan.read_text(encoding='utf-8'))
    assert plan.get('plan_kind') == 'epic'
    assert set(plan.get('child_slugs', [])) == {'alpha', 'beta'}
    assert {p.name for p in _brief_hooks_files(repo_root)} == {'brief_hooks_alpha.md', 'brief_hooks_beta.md'}

def test_b_dropped_required_child_hard_reject(tmp_path, monkeypatch, capsys):
    repo_root, state_dir, output_plan = _setup(tmp_path)
    children = [_child('alpha'), _child('beta')]
    _patch_drafts(monkeypatch, children, children)
    brief = _brief(repo_root, required_child_slugs=['alpha', 'beta', 'gamma'], deliverables='- alpha module\n- beta module\n', required_task_ids=['task-x'])
    rc = _run(brief, _config(state_dir), state_dir, output_plan)
    captured = capsys.readouterr()
    assert rc != 0
    assert 'missing_required_child' in captured.err
    assert not output_plan.exists()
    assert _brief_hooks_files(repo_root) == []

def test_b_no_plan_file_and_stderr_surfaces_missing_required_child(tmp_path, monkeypatch, capsys):
    repo_root, state_dir, output_plan = _setup(tmp_path)
    children = [_child('alpha')]
    _patch_drafts(monkeypatch, children, children)
    brief = _brief(repo_root, required_child_slugs=['alpha', 'missing-one'], deliverables='- alpha module\n', required_task_ids=['task-x'])
    rc = _run(brief, _config(state_dir), state_dir, output_plan)
    captured = capsys.readouterr()
    assert rc == 1
    assert 'missing_required_child' in captured.err
    assert not output_plan.exists()
    assert _brief_hooks_files(repo_root) == []

def test_c_uncovered_deliverable_advisory_gap(tmp_path, monkeypatch):
    repo_root, state_dir, output_plan = _setup(tmp_path)
    children = [_child('alpha'), _child('beta')]
    _patch_drafts(monkeypatch, children, children)
    brief = _brief(repo_root, required_child_slugs=['alpha', 'beta'], deliverables='- alpha module\n- beta module\n- gamma export utility\n', required_task_ids=['task-x'])
    rc = _run(brief, _config(state_dir), state_dir, output_plan)
    assert rc == 0
    plan = json.loads(output_plan.read_text(encoding='utf-8'))
    assert isinstance(plan.get('coverage_check'), dict)
    assert 'epic_coverage_gap' in _progress_events(state_dir)

def test_d_deduped_duplicate_drop_row(tmp_path, monkeypatch):
    repo_root, state_dir, output_plan = _setup(tmp_path)
    children = [_child('data_loader'), _child('data-loader')]
    _patch_drafts(monkeypatch, children, children)
    brief = _brief(repo_root, required_child_slugs=['data-loader'], deliverables='- data loader module\n', required_task_ids=['task-x'])
    rc = _run(brief, _config(state_dir), state_dir, output_plan)
    assert rc == 0
    assert 'epic_child_dropped' in _dedup_events(state_dir)
    plan = json.loads(output_plan.read_text(encoding='utf-8'))
    slugs = [c.get('slug') for c in plan['child_briefs']]
    assert slugs.count('data-loader') == 1
    assert plan.get('child_slugs', []).count('data-loader') == 1

def test_e_missing_required_field_advisory_not_refusal(tmp_path, monkeypatch):
    repo_root, state_dir, output_plan = _setup(tmp_path)
    children = [_child('alpha'), _child('beta', drop=['inputs'])]
    _patch_drafts(monkeypatch, children, children)
    brief = _brief(repo_root, required_child_slugs=['alpha', 'beta'], deliverables='- alpha module\n- beta module\n', required_task_ids=['task-x'])
    rc = _run(brief, _config(state_dir), state_dir, output_plan)
    assert rc == 0
    assert 'epic_child_advisory' in _progress_events(state_dir)
    assert output_plan.is_file()
    assert {p.name for p in _brief_hooks_files(repo_root)} == {'brief_hooks_alpha.md', 'brief_hooks_beta.md'}

def test_f_reconciliation_unresolved_items_row(tmp_path, monkeypatch):
    repo_root, state_dir, output_plan = _setup(tmp_path)
    keeper = _child('keeper')
    claude_children = [_child('keeper'), _child('twin', extra={'scope': 'scope variant X'})]
    gemini_children = [_child('keeper'), _child('twin', extra={'scope': 'scope variant Y'})]
    _patch_drafts(monkeypatch, claude_children, gemini_children)
    brief = _brief(repo_root, required_child_slugs=['keeper'], deliverables='- keeper module\n', required_task_ids=['task-x'])
    rc = _run(brief, _config(state_dir), state_dir, output_plan)
    assert rc == 0
    assert 'epic_child_unresolved' in _progress_events(state_dir)

def test_regress_dropped_required_child_writes_no_plan_or_child_files(tmp_path, monkeypatch, capsys):
    repo_root, state_dir, output_plan = _setup(tmp_path)
    children = [_child('alpha'), _child('beta')]
    _patch_drafts(monkeypatch, children, children)
    brief = _brief(repo_root, required_child_slugs=['alpha', 'beta', 'never-merged'], deliverables='- alpha module\n- beta module\n', required_task_ids=['task-x'])
    rc = _run(brief, _config(state_dir), state_dir, output_plan)
    capsys.readouterr()
    assert rc != 0
    assert not output_plan.exists()
    assert _brief_hooks_files(repo_root) == []

def test_regress_required_task_ids_inherited_into_serialized_children(tmp_path, monkeypatch):
    repo_root, state_dir, output_plan = _setup(tmp_path)
    children = [_child('alpha')]
    _patch_drafts(monkeypatch, children, children)
    brief = _brief(repo_root, required_child_slugs=['alpha'], deliverables='- alpha module\n', required_task_ids=['inherit-me-1', 'inherit-me-2'])
    rc = _run(brief, _config(state_dir), state_dir, output_plan)
    assert rc == 0
    text = (repo_root / 'brief_hooks_alpha.md').read_text(encoding='utf-8')
    assert 'inherit-me-1' in text
    assert 'inherit-me-2' in text

def test_regress_dedup_persists_slug_exactly_once(tmp_path, monkeypatch):
    repo_root, state_dir, output_plan = _setup(tmp_path)
    children = [_child('io_layer'), _child('io-layer')]
    _patch_drafts(monkeypatch, children, children)
    brief = _brief(repo_root, required_child_slugs=['io-layer'], deliverables='- io layer module\n', required_task_ids=['task-x'])
    rc = _run(brief, _config(state_dir), state_dir, output_plan)
    assert rc == 0
    assert 'epic_child_dropped' in _dedup_events(state_dir)
    plan = json.loads(output_plan.read_text(encoding='utf-8'))
    slugs = [c.get('slug') for c in plan['child_briefs']]
    assert slugs.count('io-layer') == 1

def test_regress_unresolved_item_emits_epic_child_unresolved_row(tmp_path, monkeypatch):
    repo_root, state_dir, output_plan = _setup(tmp_path)
    claude_children = [_child('keeper'), _child('split', extra={'scope': 'variant A'})]
    gemini_children = [_child('keeper'), _child('split', extra={'scope': 'variant B'})]
    _patch_drafts(monkeypatch, claude_children, gemini_children)
    brief = _brief(repo_root, required_child_slugs=['keeper'], deliverables='- keeper module\n', required_task_ids=['task-x'])
    rc = _run(brief, _config(state_dir), state_dir, output_plan)
    assert rc == 0
    assert 'epic_child_unresolved' in _progress_events(state_dir)