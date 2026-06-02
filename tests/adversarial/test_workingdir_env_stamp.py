import os
import pytest
from pathlib import Path
import harness.orchestrator as orch

class _StopLoop(Exception):
    pass

def _run_one_task(monkeypatch, task, tmp_path):
    cfg = {"synthesis": {"timeout_seconds": 1, "active_agents": ["claude", "gemini"]}}
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    
    # stubs
    monkeypatch.setattr(orch.control_gate, "check_pause", lambda *a, **k: False)
    
    # Yield the task once, then return None
    task_container = [task]
    def mock_get_next_task(*a, **k):
        if task_container:
            return task_container.pop(0)
        return None
    monkeypatch.setattr(orch, "get_next_task", mock_get_next_task)
    
    # Break loop after environment stamping
    def mock_prepare_task_prompt(*a, **k):
        raise _StopLoop()
    monkeypatch.setattr(orch, "prepare_task_prompt", mock_prepare_task_prompt)
    
    with pytest.raises(_StopLoop):
        orch.run_pipeline(cfg, state_dir)

def test_external_working_dir_stamped(monkeypatch, tmp_path):
    monkeypatch.delenv("JANUSMASK_WORKING_DIR", raising=False)
    task = {"task_id": "EXT", "working_dir": "/some/external/dir"}
    _run_one_task(monkeypatch, task, tmp_path)
    assert os.environ.get("JANUSMASK_WORKING_DIR") == "/some/external/dir"

@pytest.mark.parametrize("bad_wd", [None, "", 0, 123, 1.5, ["x"], {"a": 1}, ()])
def test_self_task_clears_after_external(monkeypatch, tmp_path, bad_wd):
    monkeypatch.delenv("JANUSMASK_WORKING_DIR", raising=False)

    # First run an external task: a non-empty string working_dir gets stamped.
    task1 = {"task_id": "EXT", "working_dir": "/some/external/dir"}
    _run_one_task(monkeypatch, task1, tmp_path / "first")
    assert os.environ.get("JANUSMASK_WORKING_DIR") == "/some/external/dir"

    # Then run a task whose working_dir is NOT a non-empty string (None, empty
    # string, or a non-str type). The prior task's value must be popped so it
    # never leaks into the next task.
    task2 = {"task_id": "SELF", "working_dir": bad_wd}
    _run_one_task(monkeypatch, task2, tmp_path / "second")
    assert os.environ.get("JANUSMASK_WORKING_DIR") is None

def test_missing_working_dir_key_clears(monkeypatch, tmp_path):
    monkeypatch.delenv('JANUSMASK_WORKING_DIR', raising=False)
    task1 = {'task_id': 'EXT', 'working_dir': '/some/external/dir'}
    _run_one_task(monkeypatch, task1, tmp_path / 'first')
    assert os.environ.get('JANUSMASK_WORKING_DIR') == '/some/external/dir'
    task2 = {'task_id': 'SELF'}
    _run_one_task(monkeypatch, task2, tmp_path / 'second')
    assert os.environ.get('JANUSMASK_WORKING_DIR') is None
def test_task_id_still_stamped(monkeypatch, tmp_path):
    monkeypatch.delenv("JANUSMASK_WORKING_DIR", raising=False)
    task = {"task_id": "TID", "working_dir": "/x"}
    _run_one_task(monkeypatch, task, tmp_path)
    assert os.environ.get("JANUSMASK_TASK_ID") == "TID"
