"""E2E Full Pipeline Tests (E-01 through E-08) for JanusMask.

Uses mock agent scripts and mock subprocess calls to test the full
orchestration pipeline end-to-end.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from harness.state import init_state, read_state, INITIAL_STATE
from harness.orchestrator import load_config, get_next_task, prepare_task_prompt, collect_submissions, spawn_agent, await_both, _validate_submission, _persist_fuzz_results, _mark_processed, DEFAULT_CONFIG_PATH
from harness.diff_fuzzer import FuzzResult, FuzzFailure
from harness.sandbox import ExecutionResult
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

def _write_task(state_dir, task_id, spec, func_sig='def f(x: int) -> int'):
    """Helper: write a task JSON file to the tasks directory."""
    tasks_dir = state_dir / 'tasks'
    tasks_dir.mkdir(parents=True, exist_ok=True)
    task = {'task_id': task_id, 'round': 1, 'specification': spec, 'constraints': {'language': 'python', 'function_signature': func_sig, 'deterministic': True}}
    path = tasks_dir / f'{task_id}.json'
    with open(path, 'w') as f:
        json.dump(task, f, indent=2)
    return task

def _write_submission(state_dir, agent, round_number, code, task_id='default'):
    """Helper: write a code submission as if an agent submitted it.

    Filename matches harness.session_namer.generate_submission_filename; task_id
    defaults to "default" to align with orchestrator.collect_submissions, which
    reads JANUSMASK_TASK_ID with the same fallback (harness/orchestrator.py:685).
    """
    sessions_dir = state_dir / 'sessions'
    sessions_dir.mkdir(parents=True, exist_ok=True)
    submission = {'code': code}
    path = sessions_dir / f'{agent}_round{round_number}_{task_id}_submission.json'
    with open(path, 'w') as f:
        json.dump(submission, f, indent=2)

def _make_mock_agent_result(code, returncode=0):
    """Create a mock subprocess.CompletedProcess that looks like an agent response."""
    return subprocess.CompletedProcess(args=['mock_agent'], returncode=returncode, stdout=json.dumps({'code': code}), stderr='')

class TestHappyPath:

    def test_e01_happy_path_both_identical(self, tmp_state_dir):
        """E-01: Both agents produce identical code -> task accepted after round 1."""
        init_state(tmp_state_dir)
        task = _write_task(tmp_state_dir, 'task-e01', 'Increment an integer by 1', 'def inc(x: int) -> int')
        code = 'def inc(x: int) -> int:\n    return x + 1\n'
        _write_submission(tmp_state_dir, 'claude', 1, code)
        _write_submission(tmp_state_dir, 'gemini', 1, code)
        claude_code, gemini_code = collect_submissions(tmp_state_dir, 1)
        assert claude_code == code
        assert gemini_code == code
        valid_c, _ = _validate_submission(claude_code, 'claude', task)
        valid_g, _ = _validate_submission(gemini_code, 'gemini', task)
        assert valid_c
        assert valid_g

class TestDivergentConverge:

    def test_e02_divergent_then_converge(self, tmp_state_dir):
        """E-02: Agents disagree at first, but both submissions are valid."""
        init_state(tmp_state_dir)
        task = _write_task(tmp_state_dir, 'task-e02', 'Check if a string is a palindrome', 'def is_palindrome(s: str) -> bool')
        code_a = 'def is_palindrome(s: str) -> bool:\n    return s == s[::-1]\n'
        code_b = 'def is_palindrome(s: str) -> bool:\n    s = s.lower()\n    return s == s[::-1]\n'
        _write_submission(tmp_state_dir, 'claude', 1, code_a)
        _write_submission(tmp_state_dir, 'gemini', 1, code_b)
        claude_code, gemini_code = collect_submissions(tmp_state_dir, 1)
        assert claude_code is not None
        assert gemini_code is not None
        assert claude_code != gemini_code
        _write_submission(tmp_state_dir, 'claude', 2, code_a)
        _write_submission(tmp_state_dir, 'gemini', 2, code_a)
        claude_r2, gemini_r2 = collect_submissions(tmp_state_dir, 2)
        assert claude_r2 == gemini_r2

class TestDivergentDecompose:

    def test_e03_persistent_divergence_decomposes(self, tmp_state_dir):
        """E-03: Agents persistently disagree -> task decomposed into subtasks."""
        from harness.task_decomposer import decompose_task, enqueue_subtasks, update_parent_state
        init_state(tmp_state_dir)
        task = _write_task(tmp_state_dir, 'task-e03', 'Sort a list of integers', 'def sort_list(data: list[int]) -> list[int]')
        result_a = ExecutionResult(success=True, return_value=[1, 2, 3], return_repr='[1, 2, 3]')
        result_b = ExecutionResult(success=True, return_value=[3, 2, 1], return_repr='[3, 2, 1]')
        failures = [FuzzFailure(input_args=[[3, 1, 2]], input_kwargs={}, result_a=result_a, result_b=result_b, reason='return_mismatch'), FuzzFailure(input_args=[[]], input_kwargs={}, result_a=ExecutionResult(success=True, return_value=[], return_repr='[]'), result_b=ExecutionResult(success=False, exception_type='IndexError', exception_message='list index out of range'), reason='exception_vs_return')]
        config = {'decomposition': {'max_subtasks': 5}}
        code_a = 'def sort_list(data: list[int]) -> list[int]:\n    return sorted(data)\n'
        code_b = 'def sort_list(data: list[int]) -> list[int]:\n    return list(reversed(data))\n'
        result = decompose_task(task, failures, config, code_a=code_a, code_b=code_b)
        assert len(result.subtasks) > 0
        assert result.parent_task_id == 'task-e03'
        enqueue_subtasks(result.subtasks, tmp_state_dir)
        subtask_ids = [s.task_id for s in result.subtasks]
        tasks_dir = tmp_state_dir / 'tasks'
        for st in result.subtasks:
            path = tasks_dir / f'{st.task_id}.json'
            assert path.is_file(), f'Subtask file missing: {st.task_id}'
        update_parent_state(tmp_state_dir, 'task-e03', subtask_ids)
        final_state = read_state(tmp_state_dir)
        assert final_state['decomposed'] is True
        assert final_state['phase'] == 'decomposition'
        assert final_state['children'] == subtask_ids

class TestOneAgentTimeout:

    def test_e04_one_agent_timeout(self, tmp_state_dir):
        """E-04: Claude submits, Gemini times out -> only one submission."""
        init_state(tmp_state_dir)
        task = _write_task(tmp_state_dir, 'task-e04', 'Add two numbers', 'def add(a: int, b: int) -> int')
        code = 'def add(a: int, b: int) -> int:\n    return a + b\n'
        _write_submission(tmp_state_dir, 'claude', 1, code)
        claude_code, gemini_code = collect_submissions(tmp_state_dir, 1)
        assert claude_code is not None
        assert gemini_code is None

class TestBothAgentsTimeout:

    def test_e05_both_timeout(self, tmp_state_dir):
        """E-05: Neither submits -> both None."""
        init_state(tmp_state_dir)
        _write_task(tmp_state_dir, 'task-e05', 'No submissions', 'def f(x: int) -> int')
        claude_code, gemini_code = collect_submissions(tmp_state_dir, 1)
        assert claude_code is None
        assert gemini_code is None

class TestASTFailure:

    def test_e06_ast_failure_rejected(self, tmp_state_dir):
        """E-06: Agent submits invalid code -> AST validation fails."""
        init_state(tmp_state_dir)
        task = _write_task(tmp_state_dir, 'task-e06', 'Add numbers', 'def add(a: int, b: int) -> int')
        bad_code = 'def add(a, b):\n    return a +\n'
        _write_submission(tmp_state_dir, 'claude', 1, bad_code)
        claude_code, _ = collect_submissions(tmp_state_dir, 1)
        valid, violations = _validate_submission(claude_code, 'claude', task)
        assert not valid
        assert any((v.rule == 'syntax' for v in violations))

class TestMultipleTasks:

    def test_e07_multiple_tasks_processed_sequentially(self, tmp_state_dir):
        """E-07: 3 tasks queued — all processed sequentially."""
        init_state(tmp_state_dir)
        for i in range(1, 4):
            _write_task(tmp_state_dir, f'task-e07-{i:03d}', f'Task number {i}', 'def f(x: int) -> int')
        task1 = get_next_task(tmp_state_dir)
        assert task1 is not None
        assert task1['task_id'] == 'task-e07-001'
        _mark_processed(tmp_state_dir, 'task-e07-001')
        task2 = get_next_task(tmp_state_dir)
        assert task2 is not None
        assert task2['task_id'] == 'task-e07-002'
        _mark_processed(tmp_state_dir, 'task-e07-002')
        task3 = get_next_task(tmp_state_dir)
        assert task3 is not None
        assert task3['task_id'] == 'task-e07-003'
        _mark_processed(tmp_state_dir, 'task-e07-003')
        assert get_next_task(tmp_state_dir) is None

class TestSubtaskPipeline:

    def test_e08_decomposed_subtasks_reenter_pipeline(self, tmp_state_dir):
        """E-08: Decomposed subtasks re-enter the pipeline as new tasks."""
        from harness.task_decomposer import Subtask, enqueue_subtasks
        init_state(tmp_state_dir)
        _write_task(tmp_state_dir, 'task-e08', 'Parent task', 'def f(x: int) -> int')
        parent_task = get_next_task(tmp_state_dir)
        assert parent_task['task_id'] == 'task-e08'
        _mark_processed(tmp_state_dir, 'task-e08')
        subtasks = [Subtask(task_id='task-e08-edge', parent_task_id='task-e08', specification='Handle edge cases', constraints={'language': 'python'}), Subtask(task_id='task-e08-compose', parent_task_id='task-e08', specification='Compose solutions', constraints={'language': 'python'}, depends_on=['task-e08-edge'])]
        enqueue_subtasks(subtasks, tmp_state_dir)
        next_task = get_next_task(tmp_state_dir)
        assert next_task is not None
        assert next_task['task_id'] in ('task-e08-edge', 'task-e08-compose')
        assert next_task.get('parent_task') == 'task-e08'
from harness.planner.taxonomies import META_TASK_POLICY, SKIP_SMOKE_GATE_TYPES

class TestMetaTaskTypeSmokeGatePolicy:
    """Assert META_TASK_POLICY-driven skip_smoke_gates behavior; closes the post-G8 6f52adc e2e coverage gap."""

    def test_harness_self_fix_skip_smoke_gates_true(self):
        """harness_self_fix mtt opts in to skip_smoke_gates and is listed in SKIP_SMOKE_GATE_TYPES."""
        assert META_TASK_POLICY['harness_self_fix']['skip_smoke_gates'] is True
        assert 'harness_self_fix' in SKIP_SMOKE_GATE_TYPES

    def test_data_model_skip_smoke_gates_false(self):
        """data_model mtt does NOT opt in to skip_smoke_gates and is absent from SKIP_SMOKE_GATE_TYPES."""
        assert META_TASK_POLICY.get('data_model', {}).get('skip_smoke_gates', False) is False
        assert 'data_model' not in SKIP_SMOKE_GATE_TYPES

    def test_skip_smoke_gate_types_invariant_subset_of_policy(self):
        """Every mtt in SKIP_SMOKE_GATE_TYPES must be a known key in META_TASK_POLICY."""
        assert SKIP_SMOKE_GATE_TYPES <= frozenset(META_TASK_POLICY.keys())