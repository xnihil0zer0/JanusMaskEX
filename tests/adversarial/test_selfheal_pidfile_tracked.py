from __future__ import annotations
import os
import pathlib
import subprocess
import pytest

import harness.autowork_daemon as ad

class FakeProcess:
    def __init__(self, pid: int = 424242):
        self.pid = pid

def test_selfheal_pidfile_written(tmp_path: pathlib.Path, monkeypatch) -> None:
    # Setup state_dir
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    
    # We must trigger one of the escalation preconditions
    # Create the auto_promote.allowlist file with a dummy task
    allowlist_path = state_dir / 'control' / 'autowork' / 'auto_promote.allowlist'
    allowlist_path.parent.mkdir(parents=True, exist_ok=True)
    allowlist_path.write_text("dummy_task_id\n", encoding="utf-8")
    
    fake_pid = 424242
    
    def mock_popen(cmd, *args, **kwargs):
        return FakeProcess(pid=fake_pid)
    
    monkeypatch.setattr(ad.subprocess, 'Popen', mock_popen)
    # Monkeypatch _contain_selfheal to be a simple passthrough
    monkeypatch.setattr(ad, '_contain_selfheal', lambda cmd, env, work_dir, state_dir, config, agent: cmd)
    
    config = {
        'control': {
            'autobrief_default_agent': 'claude'
        },
        'agents': {
            'claude': {
                'command': 'fake_claude',
                'args': ['-p']
            }
        }
    }
    
    # Clear any preexisting pidfiles in running directory
    running_dir = ad._running_dir(state_dir)
    if running_dir.exists():
        for p in running_dir.glob('*.pid'):
            p.unlink()
            
    # Run inactivity escalation
    ad._escalate_inactivity(state_dir, config)
    
    # Verify the pidfile exists. The stem is PID-uniquified
    # (selfheal_claude_daemon_inactivity_stuck_<pid>) so glob the prefix and
    # assert exactly one match with the right pid content (format-tolerant).
    pidfile_prefix = "selfheal_claude_daemon_inactivity_stuck"
    matches = list(running_dir.glob(f"{pidfile_prefix}*.pid"))
    assert len(matches) == 1, f"Self-heal pidfile was not written (found {matches})"
    pidfile_path = matches[0]
    assert pidfile_path.read_text(encoding="utf-8").strip() == str(fake_pid)

    # Verify that _reap_running recognizes it (prefix match on the returned stems)
    def mock_waitpid(pid, options):
        return 0, 0
    monkeypatch.setattr(os, 'waitpid', mock_waitpid)

    live_tasks = ad._reap_running(state_dir)
    assert any(t.startswith(pidfile_prefix) for t in live_tasks)


def test_selfheal_pidfile_not_written_on_failure(tmp_path: pathlib.Path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    
    allowlist_path = state_dir / 'control' / 'autowork' / 'auto_promote.allowlist'
    allowlist_path.parent.mkdir(parents=True, exist_ok=True)
    allowlist_path.write_text("dummy_task_id\n", encoding="utf-8")
    
    def mock_popen_fail(cmd, *args, **kwargs):
        raise OSError("Failed to start process")
        
    monkeypatch.setattr(ad.subprocess, 'Popen', mock_popen_fail)
    monkeypatch.setattr(ad, '_contain_selfheal', lambda cmd, env, work_dir, state_dir, config, agent: cmd)
    
    config = {
        'control': {
            'autobrief_default_agent': 'claude'
        },
        'agents': {
            'claude': {
                'command': 'fake_claude',
                'args': ['-p']
            }
        }
    }
    
    # Clear any preexisting pidfiles in running directory
    running_dir = ad._running_dir(state_dir)
    if running_dir.exists():
        for p in running_dir.glob('*.pid'):
            p.unlink()
            
    telemetry_events = []
    def mock_emit_telemetry(sd, tid, event, detail):
        telemetry_events.append((tid, event, detail))
    monkeypatch.setattr(ad, '_emit_telemetry', mock_emit_telemetry)
    
    # Run inactivity escalation
    ad._escalate_inactivity(state_dir, config)
    
    # Verify no pidfile exists
    pidfile_path = running_dir / "selfheal_claude_daemon_inactivity_stuck.pid"
    assert not pidfile_path.exists(), "Pidfile should not be written when process spawn fails"
    
    # Verify telemetry spawn_failed was recorded
    assert any(event == 'spawn_failed' for _, event, _ in telemetry_events), "Telemtry spawn_failed event not emitted"
