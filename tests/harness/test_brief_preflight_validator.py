import pytest
from pathlib import Path
import sys
from harness.planner.cli import main

class ReachedBlindDrafts(BaseException):
    pass

@pytest.fixture(autouse=True)
def hermetic_setup(monkeypatch):
    monkeypatch.setattr('harness.orchestrator.load_config', lambda *a, **k: {})
    monkeypatch.setattr('harness.depth_validator.check_brief_depth', lambda *a, **k: True)

def create_brief(tmp_path, filename='brief.md', required_task_ids=None, omit_sections=None, empty_sections=None, tasks=None):
    if required_task_ids is None:
        required_task_ids = ['task-1']
    frontmatter = '---\n'
    if required_task_ids is not None:
        frontmatter += 'required_task_ids:\n'
        for rti in required_task_ids:
            frontmatter += f'  - {rti}\n'
    frontmatter += '---\n'
    sections = {'title': '# Title\nMy Synthetic Title\n', 'scope': '# Scope\nMy Synthetic Scope\n', 'non_goals': '# Non-Goals\nMy Non-Goals, integration is out of scope.\n', 'inputs': '# Inputs\nMy Inputs\n', 'deliverables': '# Deliverables\nMy Deliverables\n'}
    if omit_sections:
        for sec in omit_sections:
            sections.pop(sec, None)
    if empty_sections:
        for sec in empty_sections:
            if sec in sections:
                sections[sec] = f'# {sec.replace('_', ' ').title()}\n'
    content = frontmatter
    for sec_content in sections.values():
        content += sec_content
    if tasks is None:
        tasks = [{'id': 'task-1', 'heading': '## TASK 1 — task-1', 'body': 'This handles integration testing and edge_case details.\n- `task_id: task-1`'}]
    for task in tasks:
        content += f'\n{task['heading']}\n{task['body']}\n'
    brief_path = tmp_path / filename
    brief_path.write_text(content, encoding='utf-8')
    return brief_path

def test_malformed_brief_missing_title_short_circuits(tmp_path, monkeypatch, capsys):
    drafts_called = []

    def mock_blind_drafts(*args, **kwargs):
        drafts_called.append(True)
    monkeypatch.setattr('harness.planner.cli.blind_drafts', mock_blind_drafts)
    brief_path = create_brief(tmp_path, omit_sections={'title'})
    with pytest.raises(SystemExit) as exc_info:
        main([str(brief_path)])
    assert exc_info.value.code == 2
    assert not drafts_called
    captured = capsys.readouterr()
    assert 'validation failed' in captured.err.lower()
    assert 'title' in captured.err.lower()

def test_malformed_brief_missing_integration_short_circuits(tmp_path, monkeypatch, capsys):
    drafts_called = []

    def mock_blind_drafts(*args, **kwargs):
        drafts_called.append(True)
    monkeypatch.setattr('harness.planner.cli.blind_drafts', mock_blind_drafts)
    tasks = [{'id': 'my-custom-task-id', 'heading': '## TASK 1 — my-custom-task-id', 'body': 'This lacks the special i-word, but mentions edge_case.\n- `task_id: my-custom-task-id`'}]
    brief_path = create_brief(tmp_path, required_task_ids=['my-custom-task-id'], tasks=tasks)
    with pytest.raises(SystemExit) as exc_info:
        main([str(brief_path)])
    assert exc_info.value.code == 2
    assert not drafts_called
    captured = capsys.readouterr()
    assert 'validation failed' in captured.err.lower()
    assert 'my-custom-task-id' in captured.err.lower()

def test_malformed_brief_missing_edge_case_short_circuits(tmp_path, monkeypatch, capsys):
    drafts_called = []

    def mock_blind_drafts(*args, **kwargs):
        drafts_called.append(True)
    monkeypatch.setattr('harness.planner.cli.blind_drafts', mock_blind_drafts)
    tasks = [{'id': 'my-edge-task', 'heading': '## TASK 1 — my-edge-task', 'body': 'This has integration, but absolutely no special test guidance.\n- `task_id: my-edge-task`'}]
    brief_path = create_brief(tmp_path, required_task_ids=['my-edge-task'], tasks=tasks)
    with pytest.raises(SystemExit) as exc_info:
        main([str(brief_path)])
    assert exc_info.value.code == 2
    assert not drafts_called
    captured = capsys.readouterr()
    assert 'validation failed' in captured.err.lower()

def test_well_formed_brief_proceeds_past_preflight(tmp_path, monkeypatch):

    def mock_blind_drafts(*args, **kwargs):
        raise ReachedBlindDrafts('Reached blind drafts!')
    monkeypatch.setattr('harness.planner.cli.blind_drafts', mock_blind_drafts)
    brief_path = create_brief(tmp_path)
    with pytest.raises(ReachedBlindDrafts):
        main([str(brief_path)])

def test_preflight_validation_determinism(tmp_path, monkeypatch, capsys):
    drafts_called = []

    def mock_blind_drafts(*args, **kwargs):
        drafts_called.append(True)
    monkeypatch.setattr('harness.planner.cli.blind_drafts', mock_blind_drafts)
    brief_path = create_brief(tmp_path, omit_sections={'title'})
    with pytest.raises(SystemExit) as exc_info1:
        main([str(brief_path)])
    with pytest.raises(SystemExit) as exc_info2:
        main([str(brief_path)])
    assert exc_info1.value.code == 2
    assert exc_info2.value.code == 2
    assert not drafts_called

def test_malformed_brief_empty_title_short_circuits(tmp_path, monkeypatch, capsys):
    drafts_called = []

    def mock_blind_drafts(*args, **kwargs):
        drafts_called.append(True)
    monkeypatch.setattr('harness.planner.cli.blind_drafts', mock_blind_drafts)
    brief_path = create_brief(tmp_path, empty_sections={'title'})
    with pytest.raises(SystemExit) as exc_info:
        main([str(brief_path)])
    assert exc_info.value.code == 2
    assert not drafts_called
    captured = capsys.readouterr()
    assert 'validation failed' in captured.err.lower()
    assert 'title' in captured.err.lower()

def test_malformed_brief_missing_scope_short_circuits(tmp_path, monkeypatch, capsys):
    drafts_called = []

    def mock_blind_drafts(*args, **kwargs):
        drafts_called.append(True)
    monkeypatch.setattr('harness.planner.cli.blind_drafts', mock_blind_drafts)
    brief_path = create_brief(tmp_path, omit_sections={'scope'})
    with pytest.raises(SystemExit) as exc_info:
        main([str(brief_path)])
    assert exc_info.value.code == 2
    assert not drafts_called
    captured = capsys.readouterr()
    assert 'validation failed' in captured.err.lower()
    assert 'scope' in captured.err.lower()

def test_malformed_brief_required_task_id_mismatch_short_circuits(tmp_path, monkeypatch, capsys):
    drafts_called = []

    def mock_blind_drafts(*args, **kwargs):
        drafts_called.append(True)
    monkeypatch.setattr('harness.planner.cli.blind_drafts', mock_blind_drafts)
    brief_path = create_brief(tmp_path, required_task_ids=['task-1', 'task-2'])
    with pytest.raises(SystemExit) as exc_info:
        main([str(brief_path)])
    assert exc_info.value.code == 2
    assert not drafts_called
    captured = capsys.readouterr()
    assert 'validation failed' in captured.err.lower()
    assert 'task-2' in captured.err.lower()

def test_malformed_brief_extra_task_id_mismatch_short_circuits(tmp_path, monkeypatch, capsys):
    drafts_called = []

    def mock_blind_drafts(*args, **kwargs):
        drafts_called.append(True)
    monkeypatch.setattr('harness.planner.cli.blind_drafts', mock_blind_drafts)
    tasks = [{'id': 'task-1', 'heading': '## TASK 1 — task-1', 'body': 'This has integration and edge_case.\n- `task_id: task-1`'}, {'id': 'task-2', 'heading': '## TASK 2 — task-2', 'body': 'This has integration and edge_case.\n- `task_id: task-2`'}]
    brief_path = create_brief(tmp_path, required_task_ids=['task-1'], tasks=tasks)
    with pytest.raises(SystemExit) as exc_info:
        main([str(brief_path)])
    assert exc_info.value.code == 2
    assert not drafts_called
    captured = capsys.readouterr()
    assert 'validation failed' in captured.err.lower()
    assert 'task-2' in captured.err.lower()

def test_well_formed_brief_decoy_task_id_proceeds(tmp_path, monkeypatch):

    def mock_blind_drafts(*args, **kwargs):
        raise ReachedBlindDrafts('Reached blind drafts!')
    monkeypatch.setattr('harness.planner.cli.blind_drafts', mock_blind_drafts)
    tasks = [{'id': 'task-1', 'heading': '## TASK 1 — task-1', 'body': 'Decoy text: task_id: decoy-1 in prose. Also integration and edge_case.\n- `task_id: task-1`'}]
    brief_path = create_brief(tmp_path, required_task_ids=['task-1'], tasks=tasks)
    with pytest.raises(ReachedBlindDrafts):
        main([str(brief_path)])

def test_preflight_validation_multiple_violations_reported(tmp_path, monkeypatch, capsys):
    drafts_called = []

    def mock_blind_drafts(*args, **kwargs):
        drafts_called.append(True)
    monkeypatch.setattr('harness.planner.cli.blind_drafts', mock_blind_drafts)
    brief_path = create_brief(tmp_path, omit_sections={'title', 'scope'})
    with pytest.raises(SystemExit) as exc_info:
        main([str(brief_path)])
    assert exc_info.value.code == 2
    assert not drafts_called
    captured = capsys.readouterr()
    assert 'validation failed' in captured.err.lower()
    assert 'title' in captured.err.lower()
    assert 'scope' in captured.err.lower()