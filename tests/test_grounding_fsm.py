import os
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from harness.state import VALID_PHASES, get_phase, set_phase
from harness.orchestrator import run_pipeline

class StopPipeline(Exception):
    pass

@pytest.fixture
def temp_state_dir():
    temp_dir = tempfile.mkdtemp()
    state_dir = Path(temp_dir)
    (state_dir / 'tasks').mkdir()
    (state_dir / 'sessions').mkdir()
    state_file = state_dir / 'STATE.json'
    initial_state = {'task_id': 'test_task', 'round': 0, 'phase': 'idle', 'claude_status': 'pending', 'gemini_status': 'pending', 'antigravity_status': 'pending', 'status_updated_at_epoch': None, 'fuzz_results': None, 'cross_exam_round': 0, 'decomposed': False, 'parent_task': None, 'children': []}
    with open(state_file, 'w') as f:
        json.dump(initial_state, f)
    (state_dir / 'state.lock').touch()
    yield state_dir
    shutil.rmtree(temp_dir)

def test_state_valid_phases_contains_grounding():
    assert 'grounding' in VALID_PHASES

def test_fsm_routes_to_grounding_on_conceptual_mismatch(temp_state_dir):
    task_file = temp_state_dir / 'tasks' / 'test_task_123.json'
    with open(task_file, 'w') as f:
        json.dump({'task_id': 'test_task_123'}, f)
    config = {'synthesis': {'timeout_seconds': 10, 'max_ast_retries': 1, 'use_retry_module': False, 'active_agents': ['claude', 'gemini']}}
    calls = [0]

    def mock_get_next_task(sd):
        if calls[0] == 0:
            calls[0] += 1
            (temp_state_dir / 'tasks' / 'test_task_123.json').rename(temp_state_dir / 'tasks' / 'test_task_123.json.processing')
            return {'task_id': 'test_task_123', 'grounding_bundle': 'mock_bundle.json', 'grounding_key': 'mock_key'}
        else:
            raise StopPipeline()

    def mock_validate(path, key):
        assert get_phase(temp_state_dir) == 'grounding'
        raise StopPipeline()
    with patch('harness.orchestrator.get_next_task', side_effect=mock_get_next_task), patch('harness.orchestrator.prepare_task_prompt', side_effect=ValueError('Simulated failure')), patch('harness.grounding.classify_failure_severity', return_value='conceptual_mismatch'), patch('harness.grounding.validate_grounding_bundle', side_effect=mock_validate):
        with pytest.raises(StopPipeline):
            run_pipeline(config, temp_state_dir)
    assert get_phase(temp_state_dir) == 'grounding'

def test_fsm_bypasses_grounding_on_implementation_defect(temp_state_dir):
    task_file = temp_state_dir / 'tasks' / 'test_task_123.json'
    with open(task_file, 'w') as f:
        json.dump({'task_id': 'test_task_123'}, f)
    config = {'synthesis': {'timeout_seconds': 10, 'max_ast_retries': 1, 'use_retry_module': False, 'active_agents': ['claude', 'gemini']}}
    calls = [0]

    def mock_get_next_task(sd):
        if calls[0] == 0:
            calls[0] += 1
            (temp_state_dir / 'tasks' / 'test_task_123.json').rename(temp_state_dir / 'tasks' / 'test_task_123.json.processing')
            return {'task_id': 'test_task_123'}
        else:
            raise StopPipeline()
    with patch('harness.orchestrator.get_next_task', side_effect=mock_get_next_task), patch('harness.orchestrator.prepare_task_prompt', side_effect=ValueError('Simulated defect')), patch('harness.grounding.classify_failure_severity', return_value='implementation_defect'):
        with pytest.raises(ValueError, match='Simulated defect'):
            run_pipeline(config, temp_state_dir)
    assert get_phase(temp_state_dir) != 'grounding'

def test_fsm_rejects_on_grounding_validation_failure(temp_state_dir):
    task_file = temp_state_dir / 'tasks' / 'test_task_123.json'
    with open(task_file, 'w') as f:
        json.dump({'task_id': 'test_task_123'}, f)
    config = {'synthesis': {'timeout_seconds': 10, 'max_ast_retries': 1, 'use_retry_module': False, 'active_agents': ['claude', 'gemini']}}
    calls = [0]

    def mock_get_next_task(sd):
        if calls[0] == 0:
            calls[0] += 1
            (temp_state_dir / 'tasks' / 'test_task_123.json').rename(temp_state_dir / 'tasks' / 'test_task_123.json.processing')
            return {'task_id': 'test_task_123'}
        else:
            raise StopPipeline()
    with patch('harness.orchestrator.get_next_task', side_effect=mock_get_next_task), patch('harness.orchestrator.prepare_task_prompt', side_effect=ValueError('Simulated mismatch')), patch('harness.grounding.classify_failure_severity', return_value='conceptual_mismatch'), patch('harness.grounding.validate_grounding_bundle', return_value=False):
        with pytest.raises(StopPipeline):
            run_pipeline(config, temp_state_dir)
    assert get_phase(temp_state_dir) == 'rejected'
    assert (temp_state_dir / 'tasks' / 'processed' / 'test_task_123.json').exists()

def test_pipeline_grounding_transition_flow(temp_state_dir):
    task_file = temp_state_dir / 'tasks' / 'test_task_123.json'
    with open(task_file, 'w') as f:
        json.dump({'task_id': 'test_task_123'}, f)
    config = {'synthesis': {'timeout_seconds': 10, 'max_ast_retries': 1, 'use_retry_module': False, 'active_agents': ['claude', 'gemini']}}
    calls = [0]

    def mock_get_next_task(sd):
        if calls[0] == 0:
            calls[0] += 1
            (temp_state_dir / 'tasks' / 'test_task_123.json').rename(temp_state_dir / 'tasks' / 'test_task_123.json.processing')
            return {'task_id': 'test_task_123', 'grounding_bundle': 'mock_bundle.json', 'grounding_key': 'mock_key'}
        else:
            raise StopPipeline()
    with patch('harness.orchestrator.get_next_task', side_effect=mock_get_next_task), patch('harness.orchestrator.prepare_task_prompt', side_effect=ValueError('Simulated failure')), patch('harness.grounding.classify_failure_severity', return_value='conceptual_mismatch'), patch('harness.grounding.validate_grounding_bundle', return_value=True):
        with pytest.raises(StopPipeline):
            run_pipeline(config, temp_state_dir)
    assert (temp_state_dir / 'tasks' / 'test_task_123.json').exists()

def test_state_lock_concurrency_during_grounding(temp_state_dir):
    task_file = temp_state_dir / 'tasks' / 'test_task_123.json'
    with open(task_file, 'w') as f:
        json.dump({'task_id': 'test_task_123'}, f)
    config = {'synthesis': {'timeout_seconds': 10, 'max_ast_retries': 1, 'use_retry_module': False, 'active_agents': ['claude', 'gemini']}}
    calls = [0]

    def mock_get_next_task(sd):
        if calls[0] == 0:
            calls[0] += 1
            (temp_state_dir / 'tasks' / 'test_task_123.json').rename(temp_state_dir / 'tasks' / 'test_task_123.json.processing')
            return {'task_id': 'test_task_123'}
        else:
            raise StopPipeline()
    with patch('harness.orchestrator.get_next_task', side_effect=mock_get_next_task), patch('harness.orchestrator.prepare_task_prompt', side_effect=ValueError('Simulated mismatch')), patch('harness.grounding.classify_failure_severity', return_value='conceptual_mismatch'), patch('harness.grounding.validate_grounding_bundle', return_value=True):
        with pytest.raises(StopPipeline):
            run_pipeline(config, temp_state_dir)
    assert get_phase(temp_state_dir) == 'synthesis'

def test_fsm_state_transitions_property(temp_state_dir):
    for phase in VALID_PHASES:
        set_phase(temp_state_dir, phase=phase)
        assert get_phase(temp_state_dir) == phase
    with pytest.raises(Exception):
        set_phase(temp_state_dir, phase='invalid_phase_name')

def test_pipeline_continues_after_successful_grounding(temp_state_dir):
    task_file = temp_state_dir / 'tasks' / 'test_task_123.json'
    with open(task_file, 'w') as f:
        json.dump({'task_id': 'test_task_123'}, f)
    config = {'synthesis': {'timeout_seconds': 10, 'max_ast_retries': 1, 'use_retry_module': False, 'active_agents': ['claude', 'gemini']}}
    calls = [0]

    def mock_get_next_task(sd):
        if calls[0] == 0:
            calls[0] += 1
            (temp_state_dir / 'tasks' / 'test_task_123.json').rename(temp_state_dir / 'tasks' / 'test_task_123.json.processing')
            return {'task_id': 'test_task_123'}
        else:
            raise StopPipeline()
    with patch('harness.orchestrator.get_next_task', side_effect=mock_get_next_task), patch('harness.orchestrator.prepare_task_prompt', side_effect=ValueError('Simulated mismatch')), patch('harness.grounding.classify_failure_severity', return_value='conceptual_mismatch'), patch('harness.grounding.validate_grounding_bundle', return_value=True):
        with pytest.raises(StopPipeline):
            run_pipeline(config, temp_state_dir)
    assert get_phase(temp_state_dir) == 'synthesis'
    assert (temp_state_dir / 'tasks' / 'test_task_123.json').exists()

def test_pipeline_recovers_from_corrupt_grounding_bundle(temp_state_dir):
    task_file = temp_state_dir / 'tasks' / 'test_task_123.json'
    with open(task_file, 'w') as f:
        json.dump({'task_id': 'test_task_123'}, f)
    config = {'synthesis': {'timeout_seconds': 10, 'max_ast_retries': 1, 'use_retry_module': False, 'active_agents': ['claude', 'gemini']}}
    calls = [0]

    def mock_get_next_task(sd):
        if calls[0] == 0:
            calls[0] += 1
            (temp_state_dir / 'tasks' / 'test_task_123.json').rename(temp_state_dir / 'tasks' / 'test_task_123.json.processing')
            return {'task_id': 'test_task_123'}
        else:
            raise StopPipeline()
    with patch('harness.orchestrator.get_next_task', side_effect=mock_get_next_task), patch('harness.orchestrator.prepare_task_prompt', side_effect=ValueError('Simulated mismatch')), patch('harness.grounding.classify_failure_severity', return_value='conceptual_mismatch'), patch('harness.grounding.validate_grounding_bundle', side_effect=ValueError('Corrupt JSON')):
        with pytest.raises(StopPipeline):
            run_pipeline(config, temp_state_dir)
    assert get_phase(temp_state_dir) == 'rejected'
    assert (temp_state_dir / 'tasks' / 'processed' / 'test_task_123.json').exists()

def test_pipeline_handles_unsupported_exception_types(temp_state_dir):
    task_file = temp_state_dir / 'tasks' / 'test_task_123.json'
    with open(task_file, 'w') as f:
        json.dump({'task_id': 'test_task_123'}, f)
    config = {'synthesis': {'timeout_seconds': 10, 'max_ast_retries': 1, 'use_retry_module': False, 'active_agents': ['claude', 'gemini']}}
    calls = [0]

    def mock_get_next_task(sd):
        if calls[0] == 0:
            calls[0] += 1
            (temp_state_dir / 'tasks' / 'test_task_123.json').rename(temp_state_dir / 'tasks' / 'test_task_123.json.processing')
            return {'task_id': 'test_task_123'}
        else:
            raise StopPipeline()
    with patch('harness.orchestrator.get_next_task', side_effect=mock_get_next_task), patch('harness.orchestrator.prepare_task_prompt', side_effect=ValueError('Simulated mismatch')), patch('harness.grounding.classify_failure_severity', side_effect=KeyError('unsupported error')):
        with pytest.raises(ValueError, match='Simulated mismatch'):
            run_pipeline(config, temp_state_dir)
    assert get_phase(temp_state_dir) != 'grounding'