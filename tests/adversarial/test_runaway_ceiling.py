"""Oracle test for PHASE_RUNAWAY_CEILING.

Asserts:
  1. Setting max_total_selfheal_escalations to N allows exactly N spawns.
  2. The (N+1)th escalation is dropped/skipped.
  3. A 'runaway_ceiling_tripped' telemetry event is recorded with the correct count/ceiling detail.
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


def test_runaway_ceiling_tripped(tmp_path, monkeypatch):
    # Clear captured environments
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

    # Configure a low ceiling of 2
    config = {
        'autowork': {
            'max_total_selfheal_escalations': 2
        }
    }

    # Drive _escalate_inactivity 3 times (N=2, so 3 is N+1)
    for _ in range(3):
        dae._escalate_inactivity(state_dir, config)

    # We assert that exactly N (2) spawns occurred
    assert len(FakePopen.captured_envs) == 2, f"Expected exactly 2 spawns, got {len(FakePopen.captured_envs)}"

    # Check telemetry for the tripped event
    events = _telemetry_events(state_dir)
    tripped_events = [e for e in events if e.get('event') == 'runaway_ceiling_tripped']
    assert len(tripped_events) == 1, "Expected exactly 1 'runaway_ceiling_tripped' event"
    
    event = tripped_events[0]
    assert event.get('detail') == 'dropped escalation, count=2/2', f"Unexpected telemetry detail: {event.get('detail')}"
