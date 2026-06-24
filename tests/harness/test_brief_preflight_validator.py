import pytest
from pathlib import Path
import sys
from harness.planner.cli import check_brief_preflight, BriefViolation, main

class ProceededException(Exception):
    pass

def create_valid_brief(tmp_path, **kwargs) -> Path:
    required_task_ids = kwargs.get('required_task_ids', ['task-1', 'task-2'])
    frontmatter = ''
    if required_task_ids is not None:
        frontmatter = '---\nrequired_task_ids:\n'
        for rti in required_task_ids:
            frontmatter += f'  - {rti}\n'
        frontmatter += '---\n'
    title = kwargs.get('title', '# Title\nMy Title')
    scope = kwargs.get('scope', '# Scope\nMy Scope')
    non_goals = kwargs.get('non_goals', '# Non-Goals\nMy Non-Goals')
    inputs = kwargs.get('inputs', '# Inputs\nMy Inputs')
    deliverables = kwargs.get('deliverables', '# Deliverables\nMy Deliverables')
    tasks_content = kwargs.get('tasks_content', '\n## Task 1\nWe need integration testing here.\nThis handles edge_case.\n- task_id: task-1\n\n## Task 2\nThis requires integration.\nThis is a regression_test.\n- task_id: task-2\n')
    content = f'{frontmatter}{title}\n{scope}\n{non_goals}\n{inputs}\n{deliverables}\n{tasks_content}'
    brief_path = tmp_path / 'brief.md'
    brief_path.write_text(content, encoding='utf-8')
    return brief_path

def test_well_formed_brief_passes(tmp_path):
    brief_path = create_valid_brief(tmp_path)
    violations = check_brief_preflight(brief_path)
    assert violations == []

def test_missing_title_rejected_with_title_reason(tmp_path):
    brief_path = create_valid_brief(tmp_path, title='')
    violations = check_brief_preflight(brief_path)
    assert len(violations) == 1
    assert violations[0].code == 'missing_brief_section'
    assert violations[0].location == 'title'
    assert 'title' in violations[0].message.lower()
    brief_path_empty = create_valid_brief(tmp_path / 'empty_title', title='# Title\n   \n')
    violations_empty = check_brief_preflight(brief_path_empty)
    assert len(violations_empty) == 1
    assert violations_empty[0].code == 'empty_brief_section'
    assert violations_empty[0].location == 'title'
    assert 'title' in violations_empty[0].message.lower()

def test_task_missing_integration_named(tmp_path):
    tasks_content = '\n## Task 1\nThis is about disintegration.\nWe must handle edge_case.\n- task_id: task-1\n'
    brief_path = create_valid_brief(tmp_path, required_task_ids=['task-1'], tasks_content=tasks_content)
    violations = check_brief_preflight(brief_path)
    assert len(violations) == 1
    assert violations[0].code == 'task_missing_integration_directive'
    assert violations[0].location == 'task-1'
    assert 'task-1' in violations[0].message

def test_task_missing_edge_case_guidance(tmp_path):
    tasks_content = '\n## Task 1\nWe need integration.\nNo mention of edge case or regression here.\n- task_id: task-1\n'
    brief_path = create_valid_brief(tmp_path, required_task_ids=['task-1'], tasks_content=tasks_content)
    violations = check_brief_preflight(brief_path)
    assert len(violations) == 1
    assert violations[0].code == 'task_missing_edge_case_directive'
    assert violations[0].location == 'task-1'
    assert 'task-1' in violations[0].message

def test_required_task_ids_mismatch(tmp_path):
    tasks_content = '\n## Task 1\nWe need integration.\nThis is an edge_case.\n- task_id: task-1\n'
    brief_path = create_valid_brief(tmp_path, required_task_ids=['task-1', 'task-2'], tasks_content=tasks_content)
    violations = check_brief_preflight(brief_path)
    assert len(violations) == 1
    assert violations[0].code == 'required_task_id_without_section'
    assert violations[0].location == 'task-2'
    assert 'task-2' in violations[0].message
    brief_path_2 = create_valid_brief(tmp_path / 'extra_section', required_task_ids=['task-1'])
    violations_2 = check_brief_preflight(brief_path_2)
    assert len(violations_2) == 1
    assert violations_2[0].code == 'task_section_not_in_required'
    assert violations_2[0].location == 'task-2'
    assert 'task-2' in violations_2[0].message

def test_all_failures_reported_together(tmp_path):
    tasks_content = '\n## Task 1\nNo integration word here.\nBut we have edge_case.\n- task_id: task-1\n\n## Task 2\nWe need integration.\nNo edge case word here.\n- task_id: task-2\n'
    brief_path = create_valid_brief(tmp_path, required_task_ids=['task-3'], scope='', tasks_content=tasks_content)
    violations = check_brief_preflight(brief_path)
    assert len(violations) > 1
    codes = [v.code for v in violations]
    locations = [v.location for v in violations]
    assert 'missing_brief_section' in codes
    assert 'task_missing_integration_directive' in codes
    assert 'task_missing_edge_case_directive' in codes
    assert 'required_task_id_without_section' in codes
    assert 'task_section_not_in_required' in codes
    assert 'scope' in locations
    assert 'task-1' in locations
    assert 'task-2' in locations
    assert 'task-3' in locations
    assert violations == sorted(violations)

def test_decoy_task_id_in_prose(tmp_path):
    tasks_content = '\n## Task 1\nThis is about integration.\nWe must handle edge_case.\nDecoy bullet that is not a bullet: task_id: decoy-1\nWe have another decoy - task_id: decoy-2 in prose.\n- task_id: task-old\n- task_id: task-1\n'
    brief_path = create_valid_brief(tmp_path, required_task_ids=['task-1'], tasks_content=tasks_content)
    violations = check_brief_preflight(brief_path)
    assert violations == []

def test_unreadable_path_returns_violation_never_raises(tmp_path):
    non_existent = tmp_path / 'does_not_exist.md'
    violations = check_brief_preflight(non_existent)
    assert len(violations) == 1
    assert violations[0].code == 'unreadable_brief'
    assert violations[0].location == str(non_existent)
    dir_path = tmp_path / 'some_dir'
    dir_path.mkdir()
    violations_dir = check_brief_preflight(dir_path)
    assert len(violations_dir) == 1
    assert violations_dir[0].code == 'unreadable_brief'
    assert violations_dir[0].location == str(dir_path)
    brief_path = create_valid_brief(tmp_path / 'det')
    v1 = check_brief_preflight(brief_path)
    v2 = check_brief_preflight(brief_path)
    assert v1 == v2
    v_err1 = check_brief_preflight(non_existent)
    v_err2 = check_brief_preflight(non_existent)
    assert v_err1 == v_err2

def test_malformed_brief_wiring_short_circuits(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr('harness.orchestrator.load_config', lambda *a, **kw: {})
    monkeypatch.setattr('harness.depth_validator.check_brief_depth', lambda *a, **kw: True)
    drafts_called = []

    def mock_blind_drafts(*args, **kwargs):
        drafts_called.append(True)
    monkeypatch.setattr('harness.planner.cli.blind_drafts', mock_blind_drafts)
    brief_path = create_valid_brief(tmp_path, title='')
    with pytest.raises(SystemExit) as exc_info:
        main([str(brief_path)])
    assert exc_info.value.code == 2
    assert not drafts_called
    captured = capsys.readouterr()
    assert 'validation failed' in captured.err.lower()

def test_well_formed_brief_wiring_proceeds(tmp_path, monkeypatch):
    monkeypatch.setattr('harness.orchestrator.load_config', lambda *a, **kw: {})
    monkeypatch.setattr('harness.depth_validator.check_brief_depth', lambda *a, **kw: True)

    def mock_blind_drafts(*args, **kwargs):
        raise ProceededException('Proceeded!')
    monkeypatch.setattr('harness.planner.cli.blind_drafts', mock_blind_drafts)
    brief_path = create_valid_brief(tmp_path)
    with pytest.raises(ProceededException):
        main([str(brief_path)])