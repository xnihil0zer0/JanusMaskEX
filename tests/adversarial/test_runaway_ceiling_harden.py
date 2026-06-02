"""Oracle test for PHASE_RUNAWAY_CEILING_HARDEN.

Asserts:
  1. Test A (persistence): setting ceiling=2, pre-writing runaway_ceiling.json with count=2,
     then calling _escalate_inactivity once results in refusal (0 spawns) and a
     'runaway_ceiling_tripped' telemetry event.
  2. Test B (restart survival): driving 2 escalations with ceiling=2 writes count=2 to disk;
     simulating a daemon restart by resetting the in-memory global counter to 0 and
     calling again results in refusal (no additional spawns).
"""

import json
import os
import pathlib
import subprocess
import pytest

import harness.autowork_daemon as dae


class FakePopen:
    """Mock subprocess.Popen to capture spawn attempts without running them."""
    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        self.pid = 99999
        self.returncode = 0
        FakePopen.captured_envs.append(kwargs.get("env", {}))

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0

# Registry for captured environments
FakePopen.captured_envs = []


def _telemetry_events(state_dir):
    ledger = state_dir / 'impl_progress.jsonl'
    if not ledger.exists():
        return []
    events = []
    for line in ledger.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    return events


def test_runaway_ceiling_persistence(tmp_path, monkeypatch):
    """Test A: Setting ceiling=2, writing runaway_ceiling.json with count=2 BEFORE any call,
    then calling _escalate_inactivity once -> REFUSED (0 spawns) + 'runaway_ceiling_tripped'."""
    FakePopen.captured_envs.clear()

    # Reset daemon-level escalation count to 0 via monkeypatch
    monkeypatch.setattr(dae, '_SELFHEAL_ESCALATION_COUNT', 0, raising=False)
    # Monkeypatch subprocess.Popen
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    # Monkeypatch _contain_selfheal to be a simple passthrough
    monkeypatch.setattr(dae, "_contain_selfheal", lambda cmd, env, work_dir, state_dir, config, agent="": cmd)

    # Setup temp state dir and auto_promote allowlist to bypass inactivity degenerate check
    state_dir = tmp_path / "state"
    control_dir = state_dir / "control" / "autowork"
    control_dir.mkdir(parents=True, exist_ok=True)
    allowlist_path = control_dir / "auto_promote.allowlist"
    allowlist_path.write_text("some_task_slug\n", encoding="utf-8")

    # Set the agent workroot outside the repo tree to avoid ValueError in agent_workroot()
    agent_workroot_dir = tmp_path / "agent_workroot"
    agent_workroot_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(agent_workroot_dir))

    # Pre-write runaway_ceiling.json with count=2
    ceiling_file = control_dir / "runaway_ceiling.json"
    ceiling_file.write_text(json.dumps({"count": 2}), encoding="utf-8")

    # Configure a ceiling of 2
    config = {
        'autowork': {
            'max_total_selfheal_escalations': 2
        }
    }

    # Call _escalate_inactivity once
    dae._escalate_inactivity(state_dir, config)

    # Assert that no spawns occurred (refused because count=2 >= ceiling=2)
    assert len(FakePopen.captured_envs) == 0, f"Expected 0 spawns, got {len(FakePopen.captured_envs)}"

    # Check telemetry for the tripped event
    events = _telemetry_events(state_dir)
    tripped_events = [e for e in events if e.get('event') == 'runaway_ceiling_tripped']
    assert len(tripped_events) == 1, "Expected exactly 1 'runaway_ceiling_tripped' event"
    
    event = tripped_events[0]
    assert event.get('detail') == 'dropped escalation, count=2/2', f"Unexpected telemetry detail: {event.get('detail')}"


def test_runaway_ceiling_restart_survival(tmp_path, monkeypatch):
    """Test B: ceiling=2, drive 2 escalations, assert runaway_ceiling.json count==2 on disk;
    simulate restart by setting dae._SELFHEAL_ESCALATION_COUNT=0; call again -> REFUSED."""
    FakePopen.captured_envs.clear()

    # Reset daemon-level escalation count to 0 via monkeypatch
    monkeypatch.setattr(dae, '_SELFHEAL_ESCALATION_COUNT', 0, raising=False)
    # Monkeypatch subprocess.Popen
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    # Monkeypatch _contain_selfheal to be a simple passthrough
    monkeypatch.setattr(dae, "_contain_selfheal", lambda cmd, env, work_dir, state_dir, config, agent="": cmd)

    # Setup temp state dir and auto_promote allowlist to bypass inactivity degenerate check
    state_dir = tmp_path / "state"
    control_dir = state_dir / "control" / "autowork"
    control_dir.mkdir(parents=True, exist_ok=True)
    allowlist_path = control_dir / "auto_promote.allowlist"
    allowlist_path.write_text("some_task_slug\n", encoding="utf-8")

    # Set the agent workroot outside the repo tree to avoid ValueError in agent_workroot()
    agent_workroot_dir = tmp_path / "agent_workroot"
    agent_workroot_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(agent_workroot_dir))

    # Configure a ceiling of 2
    config = {
        'autowork': {
            'max_total_selfheal_escalations': 2
        }
    }

    # Drive 2 escalations
    dae._escalate_inactivity(state_dir, config)
    dae._escalate_inactivity(state_dir, config)

    # Assert exactly 2 spawns occurred
    assert len(FakePopen.captured_envs) == 2, f"Expected 2 spawns, got {len(FakePopen.captured_envs)}"

    # Assert runaway_ceiling.json count == 2 on disk
    ceiling_file = control_dir / "runaway_ceiling.json"
    assert ceiling_file.exists(), "runaway_ceiling.json does not exist on disk"
    
    data = json.loads(ceiling_file.read_text(encoding="utf-8"))
    assert data.get("count") == 2, f"Expected count=2 on disk, got {data.get('count')}"

    # Simulate restart by resetting in-memory global counter to 0
    monkeypatch.setattr(dae, '_SELFHEAL_ESCALATION_COUNT', 0, raising=False)

    # Call _escalate_inactivity again (3rd time)
    dae._escalate_inactivity(state_dir, config)

    # Assert that no additional spawn occurred (refused because persisted count is 2)
    assert len(FakePopen.captured_envs) == 2, f"Expected still 2 spawns, got {len(FakePopen.captured_envs)}"

    # Check telemetry for the tripped event
    events = _telemetry_events(state_dir)
    tripped_events = [e for e in events if e.get('event') == 'runaway_ceiling_tripped']
    assert len(tripped_events) == 1, "Expected exactly 1 'runaway_ceiling_tripped' event"
