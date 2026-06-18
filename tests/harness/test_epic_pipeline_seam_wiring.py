import json
import types
from pathlib import Path
from harness.planner import cli
CONFIG = {'hierarchical_planning': {'enabled': True}}

def _dirs(tmp_path):
    repo_root = tmp_path / 'repo'
    state_dir = repo_root / 'state'
    repo_root.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    assert state_dir.parent == repo_root
    return (repo_root, state_dir)

def _child(slug, **extra):
    data = {'slug': slug, 'title': 'Title for ' + slug, 'scope': 'Scope for ' + slug + ' describing real work to do.', 'non_goals': 'Non-goals for ' + slug + '.', 'inputs': 'Inputs for ' + slug + '.', 'deliverables': 'Deliverables for ' + slug + '.', 'working_dir': 'workdir/' + slug}
    data.update(extra)
    return data

def _brief(repo_root, **attrs):
    base = dict(required_task_ids=(), working_dir=None, raw_text='', deliverables='- a deliverable line\n', source_path=str(repo_root / 'brief_hooks_parentepic.md'), required_child_slugs=(), epic=True, sha256='0' * 64)
    base.update(attrs)
    return types.SimpleNamespace(**base)

def _drafts(children):
    return types.SimpleNamespace(claude_draft={'plan_kind': 'epic', 'child_briefs': [dict(c) for c in children]}, gemini_draft={'plan_kind': 'epic', 'child_briefs': [dict(c) for c in children]})

def _patch_seam(monkeypatch, drafts):
    import harness.planner.blind_draft as bd
    monkeypatch.setattr(bd, 'run_blind_drafts', lambda *a, **k: drafts, raising=False)

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

def _event_present(rows, name):
    return any((isinstance(r, dict) and r.get('event') == name for r in rows))

def _record(output_plan):
    return json.loads(Path(output_plan).read_text(encoding='utf-8'))

def test_uncovered_deliverable_advisory_is_exit_zero(tmp_path, monkeypatch):
    repo_root, state_dir = _dirs(tmp_path)
    children = [_child('alpha-feature')]
    _patch_seam(monkeypatch, _drafts(children))
    brief = _brief(repo_root, required_child_slugs=('alpha-feature',), deliverables='- alpha feature delivery\n- zzz unrelated orphan topic\n')
    output_plan = state_dir / 'planning' / 'merged_plan.json'
    rc = cli._run_epic_pipeline(brief, CONFIG, state_dir, output_plan)
    assert rc == 0
    assert output_plan.exists()
    assert 'coverage_check' in _record(output_plan)

def test_duplicate_child_emits_epic_child_dropped_row(tmp_path, monkeypatch):
    repo_root, state_dir = _dirs(tmp_path)
    children = [_child('dup-child'), _child('dup_child'), _child('keep-this')]
    _patch_seam(monkeypatch, _drafts(children))
    brief = _brief(repo_root, required_child_slugs=('dup-child', 'keep-this'), deliverables='- dup child task delivery\n- keep this task delivery\n')
    output_plan = state_dir / 'planning' / 'merged_plan.json'
    rc = cli._run_epic_pipeline(brief, CONFIG, state_dir, output_plan)
    assert rc == 0
    slugs = _record(output_plan).get('child_slugs') or []
    assert slugs.count('dup-child') == 1
    assert 'keep-this' in slugs
    assert _event_present(_journal_rows(state_dir), 'epic_child_dropped')

def test_oracle_is_hermetic_no_live_state_writes(tmp_path, monkeypatch):
    repo_root, state_dir = _dirs(tmp_path)
    isolated_cwd = tmp_path / 'cwd'
    isolated_cwd.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(isolated_cwd)
    children = [_child('alpha-feature'), _child('beta-feature')]
    _patch_seam(monkeypatch, _drafts(children))
    brief = _brief(repo_root, required_child_slugs=('alpha-feature', 'beta-feature'), deliverables='- alpha feature delivery\n- beta feature delivery\n')
    output_plan = state_dir / 'planning' / 'merged_plan.json'
    rc = cli._run_epic_pipeline(brief, CONFIG, state_dir, output_plan)
    assert rc == 0
    assert output_plan.exists()
    assert state_dir in output_plan.parents
    assert not (isolated_cwd / 'state').exists()