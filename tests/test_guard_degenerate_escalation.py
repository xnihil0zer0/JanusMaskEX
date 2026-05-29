"""Oracle test for GUARD_DEGENERATE_ESCALATION (Brief 2).

Verifies the degenerate-escalation guards on BOTH self-heal paths in
harness/autowork_daemon.py:
  - _escalate_to_autobrief  (the EX / blocked-retry path)
  - _escalate_inactivity    (the daemon_inactivity_stuck path; independent
                             function, NOT a caller of _escalate_to_autobrief)

A degenerate escalation must emit a `skip_degenerate_escalation` telemetry row
and dispatch NO planning agent (no subprocess.Popen). A legitimate escalation
must still dispatch exactly one planning agent, unchanged.

This is the verification oracle for the pipeline-routed change. It FAILS against
the pre-Brief-2 source (which always spawns) and PASSES once both guards land.
"""
import json
import subprocess

import harness.autowork_daemon as d


class _DummyProc:
    pid = -1

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


def _patch_popen(monkeypatch):
    """Replace subprocess.Popen and record every dispatch attempt."""
    calls = []

    def _fake(*args, **kwargs):
        calls.append((args, kwargs))
        return _DummyProc()

    monkeypatch.setattr(subprocess, 'Popen', _fake)
    return calls


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


def _skips(state_dir):
    return [e for e in _telemetry_events(state_dir)
            if e.get('event') == 'skip_degenerate_escalation']


def _write_blocked_task(state_dir, task_id, objective='', files_touched=None):
    blocked = state_dir / 'tasks' / 'blocked'
    blocked.mkdir(parents=True, exist_ok=True)
    (blocked / f'{task_id}.json').write_text(
        json.dumps({'task_id': task_id, 'objective': objective,
                    'files_touched': files_touched or []}),
        encoding='utf-8')


# ---- _escalate_to_autobrief ----

def test_autobrief_skips_missing_task(tmp_path, monkeypatch):
    calls = _patch_popen(monkeypatch)
    d._escalate_to_autobrief(tmp_path, 'PHANTOM_NONE', 'orphaned')
    assert calls == [], 'no planning agent for a missing backing task'
    assert _skips(tmp_path), 'expected a skip_degenerate_escalation telemetry row'


def test_autobrief_skips_empty_task(tmp_path, monkeypatch):
    calls = _patch_popen(monkeypatch)
    _write_blocked_task(tmp_path, 'EMPTY_TASK', objective='', files_touched=[])
    d._escalate_to_autobrief(tmp_path, 'EMPTY_TASK', 'orphaned')
    assert calls == [], 'no dispatch when objective/files empty and no error logs'
    assert _skips(tmp_path)


def test_autobrief_proceeds_for_real_task(tmp_path, monkeypatch):
    calls = _patch_popen(monkeypatch)
    _write_blocked_task(tmp_path, 'REAL_TASK', objective='Fix the thing',
                        files_touched=['harness/x.py'])
    d._escalate_to_autobrief(tmp_path, 'REAL_TASK', 'orphaned')
    assert len(calls) == 1, 'a legitimate task must still dispatch one planning agent'
    assert not _skips(tmp_path), 'a legitimate task must not be marked degenerate'


# ---- _escalate_inactivity ----

def test_inactivity_skips_when_no_work(tmp_path, monkeypatch):
    calls = _patch_popen(monkeypatch)
    d._escalate_inactivity(tmp_path, {})
    assert calls == [], 'no dispatch when there is no actionable work'
    assert _skips(tmp_path)


def test_inactivity_proceeds_with_allowlisted_work(tmp_path, monkeypatch):
    calls = _patch_popen(monkeypatch)
    aw = tmp_path / 'control' / 'autowork'
    aw.mkdir(parents=True, exist_ok=True)
    (aw / 'auto_promote.allowlist').write_text('some_real_brief\n', encoding='utf-8')
    d._escalate_inactivity(tmp_path, {})
    assert len(calls) == 1, 'allowlisted work present -> inactivity escalation must still dispatch'
    assert not _skips(tmp_path)
