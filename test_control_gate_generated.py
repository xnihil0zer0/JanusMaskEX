# ----- _control_section -----
import pytest
from harness.control_gate import _control_section

def test_control_section_extracts_existing_control_dict():
    config = {
        "name": "test_app",
        "control": {
            "timeout": 30,
            "retry_count": 5
        },
        "metadata": {"version": "1.0"}
    }
    result = _control_section(config)
    assert result == {"timeout": 30, "retry_count": 5}

def test_control_section_returns_empty_dict_when_key_is_missing():
    config = {
        "name": "test_app",
        "metadata": {"version": "1.0"}
    }
    result = _control_section(config)
    assert result == {}

def test_control_section_returns_empty_dict_when_config_is_empty():
    config = {}
    result = _control_section(config)
    assert result == {}

def test_control_section_returns_empty_dict_for_non_dict_inputs():
    assert _control_section(None) == {}
    assert _control_section(["not", "a", "dict"]) == {}
    assert _control_section("string_config") == {}
    assert _control_section(42) == {}

def test_control_section_returns_control_value_even_if_not_dict():
    # .get("control", {}) returns whatever value is at "control", even if it's None or a string
    config_with_none = {"control": None}
    assert _control_section(config_with_none) is None
    
    config_with_string = {"control": "disabled"}
    assert _control_section(config_with_string) == "disabled"


# ----- pause_flag_path -----
import pytest
from pathlib import Path
import harness.control_gate as cg
from harness.control_gate import pause_flag_path

@pytest.fixture
def patch_deps(monkeypatch):
    # Patch the internal helper and default constant to control the test environment,
    # raising=False allows this to work even if they are currently stubbed out or missing.
    monkeypatch.setattr(cg, '_control_section', lambda cfg: cfg.get("control", {}), raising=False)
    monkeypatch.setattr(cg, 'DEFAULT_PAUSE_FLAG', 'default.flag', raising=False)

def test_pause_flag_path_absolute_from_config(patch_deps):
    config = {"control": {"pause_flag_path": "/var/run/custom.flag"}}
    state_dir = Path("/opt/app/state")
    
    assert pause_flag_path(state_dir, config) == Path("/var/run/custom.flag")

def test_pause_flag_path_relative_from_config(patch_deps):
    config = {"control": {"pause_flag_path": "subdir/custom.flag"}}
    state_dir = Path("/opt/app/state")
    
    # Should resolve relative to the parent of state_dir (/opt/app)
    assert pause_flag_path(state_dir, config) == Path("/opt/app/subdir/custom.flag")

def test_pause_flag_path_uses_default_when_missing(patch_deps):
    config = {}
    state_dir = Path("/opt/app/state")
    
    assert pause_flag_path(state_dir, config) == Path("/opt/app/default.flag")

def test_pause_flag_path_uses_default_when_falsy(patch_deps):
    config = {"control": {"pause_flag_path": ""}}
    state_dir = Path("/opt/app/state")
    
    assert pause_flag_path(state_dir, config) == Path("/opt/app/default.flag")

def test_pause_flag_path_default_absolute(patch_deps, monkeypatch):
    monkeypatch.setattr(cg, 'DEFAULT_PAUSE_FLAG', '/default/abs.flag', raising=False)
    config = {}
    state_dir = Path("/opt/app/state")
    
    assert pause_flag_path(state_dir, config) == Path("/default/abs.flag")


# ----- decisions_dir -----
import pytest
from pathlib import Path
from unittest.mock import patch

from harness.control_gate import decisions_dir


def test_decisions_dir_relative_path():
    with patch('harness.control_gate._control_section') as mock_cs:
        mock_cs.return_value = {"decisions_dir": "custom_rel_dir"}
        
        state_dir = Path("/var/lib/app/state")
        config = {"example": "config"}
        result = decisions_dir(state_dir, config)
        
        assert result == Path("/var/lib/app/custom_rel_dir")
        mock_cs.assert_called_once_with(config)


def test_decisions_dir_absolute_path():
    with patch('harness.control_gate._control_section') as mock_cs:
        mock_cs.return_value = {"decisions_dir": "/opt/custom/decisions"}
        
        state_dir = Path("/var/lib/app/state")
        config = {"example": "config"}
        result = decisions_dir(state_dir, config)
        
        assert result == Path("/opt/custom/decisions")
        mock_cs.assert_called_once_with(config)


def test_decisions_dir_default_fallback_missing_key():
    with patch('harness.control_gate._control_section') as mock_cs:
        mock_cs.return_value = {}
        with patch('harness.control_gate.DEFAULT_DECISIONS_DIR', 'default_dir'):
            state_dir = Path("/var/lib/app/state")
            config = {}
            result = decisions_dir(state_dir, config)
            
            assert result == Path("/var/lib/app/default_dir")
            mock_cs.assert_called_once_with(config)


def test_decisions_dir_default_fallback_empty_string():
    with patch('harness.control_gate._control_section') as mock_cs:
        mock_cs.return_value = {"decisions_dir": ""}
        with patch('harness.control_gate.DEFAULT_DECISIONS_DIR', 'default_dir'):
            state_dir = Path("/var/lib/app/state")
            config = {}
            result = decisions_dir(state_dir, config)
            
            assert result == Path("/var/lib/app/default_dir")
            mock_cs.assert_called_once_with(config)


# ----- check_pause -----
import logging
from pathlib import Path

import pytest

from harness.control_gate import check_pause


def test_check_pause_file_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr("harness.control_gate.pause_flag_path", lambda s, c: tmp_path / "not_there")
    assert check_pause(tmp_path, {}) is False


def test_check_pause_is_paused(monkeypatch, tmp_path):
    p = tmp_path / "flag"
    p.write_text("paused")
    monkeypatch.setattr("harness.control_gate.pause_flag_path", lambda s, c: p)
    assert check_pause(tmp_path, {}) is True


def test_check_pause_is_paused_mixed_case(monkeypatch, tmp_path):
    p = tmp_path / "flag"
    p.write_text("  PaUsEd \n")
    monkeypatch.setattr("harness.control_gate.pause_flag_path", lambda s, c: p)
    assert check_pause(tmp_path, {}) is True


def test_check_pause_not_paused(monkeypatch, tmp_path):
    p = tmp_path / "flag"
    p.write_text("running")
    monkeypatch.setattr("harness.control_gate.pause_flag_path", lambda s, c: p)
    assert check_pause(tmp_path, {}) is False


def test_check_pause_is_a_directory(monkeypatch, tmp_path):
    p = tmp_path / "flag_dir"
    p.mkdir()
    monkeypatch.setattr("harness.control_gate.pause_flag_path", lambda s, c: p)
    assert check_pause(tmp_path, {}) is False


def test_check_pause_permission_error_rate_limited_logging(monkeypatch, tmp_path, caplog):
    class MockPath:
        def read_text(self, *args, **kwargs):
            raise PermissionError("EACCES")

        def __str__(self):
            return "mock/path/perm"

    monkeypatch.setattr("harness.control_gate.pause_flag_path", lambda s, c: MockPath())
    
    time_mock = [1000.0]
    monkeypatch.setattr("time.time", lambda: time_mock[0])
    
    with caplog.at_level(logging.WARNING):
        caplog.clear()
        assert check_pause(tmp_path, {}) is False
        assert "unreadable" in caplog.text
        assert "mock/path/perm" in caplog.text
        
        # Immediate second call, no time advanced -> rate limited (no log emitted)
        caplog.clear()
        assert check_pause(tmp_path, {}) is False
        assert caplog.text == ""
        
        # Advance time significantly past the rate limit threshold
        time_mock[0] += 1000000.0
        caplog.clear()
        assert check_pause(tmp_path, {}) is False
        assert "unreadable" in caplog.text


def test_check_pause_os_error(monkeypatch, tmp_path, caplog):
    class MockPath:
        def read_text(self, *args, **kwargs):
            raise OSError("IO Error")

        def __str__(self):
            return "mock/path/oserr"

    monkeypatch.setattr("harness.control_gate.pause_flag_path", lambda s, c: MockPath())
    
    time_mock = [2000.0]
    monkeypatch.setattr("time.time", lambda: time_mock[0])
    
    with caplog.at_level(logging.WARNING):
        caplog.clear()
        assert check_pause(tmp_path, {}) is False
        assert "unreadable" in caplog.text
        assert "IO Error" in caplog.text


# ----- require_approval_for -----
import pytest
from unittest.mock import patch
from harness.control_gate import require_approval_for

@patch('harness.control_gate._control_section')
def test_require_approval_for_phase_in_list(mock_control_section):
    mock_control_section.return_value = {"require_approval": ["plan", "execute"]}
    config = {"dummy": "data"}
    
    assert require_approval_for("execute", config) is True
    mock_control_section.assert_called_once_with(config)

@patch('harness.control_gate._control_section')
def test_require_approval_for_phase_not_in_list(mock_control_section):
    mock_control_section.return_value = {"require_approval": ["plan"]}
    config = {"dummy": "data"}
    
    assert require_approval_for("execute", config) is False
    mock_control_section.assert_called_once_with(config)

@patch('harness.control_gate._control_section')
def test_require_approval_for_missing_key(mock_control_section):
    mock_control_section.return_value = {"other_key": True}
    config = {"dummy": "data"}
    
    assert require_approval_for("execute", config) is False
    mock_control_section.assert_called_once_with(config)

@patch('harness.control_gate._control_section')
def test_require_approval_for_none_value(mock_control_section):
    mock_control_section.return_value = {"require_approval": None}
    config = {"dummy": "data"}
    
    assert require_approval_for("execute", config) is False
    mock_control_section.assert_called_once_with(config)

@patch('harness.control_gate._control_section')
def test_require_approval_for_empty_list(mock_control_section):
    mock_control_section.return_value = {"require_approval": []}
    config = {"dummy": "data"}
    
    assert require_approval_for("execute", config) is False
    mock_control_section.assert_called_once_with(config)


# ----- _read_decision -----
import json
from pathlib import Path
from harness.control_gate import _read_decision

def test_read_decision_valid(tmp_path: Path) -> None:
    decision_file = tmp_path / "decision.json"
    decision_data = {"decision": "continue", "reason": "no issues"}
    decision_file.write_text(json.dumps(decision_data))
    
    result = _read_decision(decision_file)
    assert result == decision_data

def test_read_decision_absent(tmp_path: Path) -> None:
    decision_file = tmp_path / "absent.json"
    result = _read_decision(decision_file)
    assert result is None

def test_read_decision_invalid_json(tmp_path: Path) -> None:
    decision_file = tmp_path / "invalid.json"
    decision_file.write_text("not real json {")
    
    result = _read_decision(decision_file)
    assert result is None

def test_read_decision_missing_key(tmp_path: Path) -> None:
    decision_file = tmp_path / "missing.json"
    decision_file.write_text(json.dumps({"other": "value"}))
    
    result = _read_decision(decision_file)
    assert result is None

def test_read_decision_wrong_type(tmp_path: Path) -> None:
    decision_file = tmp_path / "wrong.json"
    decision_file.write_text(json.dumps(["decision", "value"]))
    
    result = _read_decision(decision_file)
    assert result is None


# ----- await_decision -----
import json
import threading
import time
from pathlib import Path

from harness.control_gate import await_decision

def test_await_decision_auto_when_not_required(tmp_path):
    config = {
        "control": {
            "require_approval": ["other_phase"]
        }
    }
    result = await_decision(
        state_dir=tmp_path,
        task_id="t1",
        phase="test_phase",
        config=config,
    )
    assert result == "auto"

def test_await_decision_reads_decision_file(tmp_path):
    config = {
        "control": {
            "require_approval": ["test_phase"]
        }
    }
    task_id = "t1"
    d_dir = tmp_path / "control" / "decisions"
    d_dir.mkdir(parents=True)
    (d_dir / f"{task_id}.json").write_text(json.dumps({"decision": "APPROVE"}))
    
    result = await_decision(
        state_dir=tmp_path,
        task_id=task_id,
        phase="test_phase",
        config=config,
        poll_interval=0.01,
    )
    assert result == "approve"

def test_await_decision_empty_decision(tmp_path):
    config = {
        "control": {
            "require_approval": ["test_phase"]
        }
    }
    task_id = "t1"
    d_dir = tmp_path / "control" / "decisions"
    d_dir.mkdir(parents=True)
    (d_dir / f"{task_id}.json").write_text(json.dumps({}))
    
    result = await_decision(
        state_dir=tmp_path,
        task_id=task_id,
        phase="test_phase",
        config=config,
        poll_interval=0.01,
    )
    assert result == "auto"

def test_await_decision_timeout(tmp_path):
    config = {
        "control": {
            "require_approval": ["test_phase"]
        }
    }
    task_id = "t2"
    
    result = await_decision(
        state_dir=tmp_path,
        task_id=task_id,
        phase="test_phase",
        config=config,
        timeout=0.05,
        poll_interval=0.01,
    )
    assert result == "timeout"

def test_await_decision_timeout_from_config(tmp_path):
    config = {
        "control": {
            "require_approval": ["test_phase"],
            "approval_timeout_sec": 0.05,
        }
    }
    task_id = "t2_cfg"
    
    result = await_decision(
        state_dir=tmp_path,
        task_id=task_id,
        phase="test_phase",
        config=config,
        timeout=None,
        poll_interval=0.01,
    )
    assert result == "timeout"

def test_await_decision_callbacks(tmp_path):
    config = {
        "control": {
            "require_approval": ["test_phase"]
        }
    }
    task_id = "t3"
    
    pending_called = []
    def emit_pending(tid, ph):
        pending_called.append((tid, ph))
        
    timeout_called = []
    def emit_timeout(tid, ph):
        timeout_called.append((tid, ph))
        
    result = await_decision(
        state_dir=tmp_path,
        task_id=task_id,
        phase="test_phase",
        config=config,
        emit_pending=emit_pending,
        emit_timeout=emit_timeout,
        timeout=0.05,
        poll_interval=0.01,
    )
    assert result == "timeout"
    assert pending_called == [(task_id, "test_phase")]
    assert timeout_called == [(task_id, "test_phase")]

def test_await_decision_callbacks_exceptions_ignored(tmp_path):
    config = {
        "control": {
            "require_approval": ["test_phase"]
        }
    }
    task_id = "t4"
    
    def emit_pending_err(tid, ph):
        raise ValueError("boom pending")
        
    def emit_timeout_err(tid, ph):
        raise ValueError("boom timeout")
        
    # Should not raise
    result = await_decision(
        state_dir=tmp_path,
        task_id=task_id,
        phase="test_phase",
        config=config,
        emit_pending=emit_pending_err,
        emit_timeout=emit_timeout_err,
        timeout=0.05,
        poll_interval=0.01,
    )
    assert result == "timeout"

def test_await_decision_delayed_file(tmp_path):
    config = {
        "control": {
            "require_approval": ["test_phase"]
        }
    }
    task_id = "t5"
    d_dir = tmp_path / "control" / "decisions"
    
    def delayed_write():
        time.sleep(0.05)
        d_dir.mkdir(parents=True, exist_ok=True)
        (d_dir / f"{task_id}.json").write_text(json.dumps({"decision": "RETRY"}))
        
    t = threading.Thread(target=delayed_write)
    t.start()
    
    try:
        result = await_decision(
            state_dir=tmp_path,
            task_id=task_id,
            phase="test_phase",
            config=config,
            timeout=1.0,
            poll_interval=0.01,
        )
        assert result == "retry"
    finally:
        t.join()


# ----- record_agent_pid -----
import sys
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from harness.control_gate import record_agent_pid

def test_record_agent_pid_success(monkeypatch, tmp_path: Path):
    mock_state = MagicMock()
    captured = []

    def fake_rmw(cb, d):
        captured.append((cb, d))

    mock_state.locked_read_modify_write.side_effect = fake_rmw

    monkeypatch.setitem(sys.modules, 'harness.state', mock_state)
    if 'harness' in sys.modules:
        monkeypatch.setattr(sys.modules['harness'], 'state', mock_state, raising=False)

    record_agent_pid(tmp_path, "testagent", 123)

    assert mock_state.locked_read_modify_write.called
    assert len(captured) == 1
    
    cb, d = captured[0]
    assert d == tmp_path
    
    state_dict = {"other": 1}
    res = cb(state_dict)
    assert res is state_dict
    assert state_dict == {"other": 1, "testagent_pid": 123}

def test_record_agent_pid_swallows_execution_error(monkeypatch, tmp_path: Path):
    mock_state = MagicMock()
    mock_state.locked_read_modify_write.side_effect = RuntimeError("disk IO error")

    monkeypatch.setitem(sys.modules, 'harness.state', mock_state)
    if 'harness' in sys.modules:
        monkeypatch.setattr(sys.modules['harness'], 'state', mock_state, raising=False)

    # Should not raise exception
    record_agent_pid(tmp_path, "testagent", 123)
    assert mock_state.locked_read_modify_write.called

def test_record_agent_pid_swallows_import_error(monkeypatch, tmp_path: Path):
    # Forcing a ModuleNotFoundError to simulate missing module or failure during import
    monkeypatch.setitem(sys.modules, 'harness.state', None)
    if 'harness' in sys.modules:
        monkeypatch.delattr(sys.modules['harness'], 'state', raising=False)
        
    # Should not raise exception
    record_agent_pid(tmp_path, "testagent", 123)
