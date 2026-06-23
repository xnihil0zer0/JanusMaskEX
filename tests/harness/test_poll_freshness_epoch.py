"""Oracle pinning the spawn_start_epoch freshness gate in harness.orchestrator.

A planning draft written *during* claude's BLOCKING tmux spawn has an mtime
earlier than ``poll_start_wall`` (which ``poll_for_submission`` only samples
AFTER the spawn returns). That draft must be KEPT when ``run_agent_phase``
forwards the true pre-spawn epoch as ``spawn_start_epoch`` -- while a genuine
prior-spawn leftover (mtime before that epoch) is still discarded.

RED on HEAD (the kwarg path is absent / the gate uses poll_start_wall=now > M),
GREEN once planner-freshness-epoch-impl lands. The module is loaded via importlib
only; no exec/eval/compile/__import__ (AST-banned by harness/ast_enforcer.py).
"""
import importlib
import os
import time
import types
orch = importlib.import_module('harness.orchestrator')
DRAFT_TEXT = '{"tasks": []}'

def _make_workdir(tmp_path, mtime):
    """Create <tmp>/work/outbox/plan_draft.json, stamp its mtime via os.utime,
    and return (work_dir, draft_path)."""
    work_dir = tmp_path / 'work'
    outbox = work_dir / 'outbox'
    outbox.mkdir(parents=True)
    draft = outbox / 'plan_draft.json'
    draft.write_text(DRAFT_TEXT)
    os.utime(draft, (mtime, mtime))
    return (work_dir, draft)

def _fake_proc(work_dir):
    """An already-exited fake proc honoring the poll/returncode/_work_dir seam."""
    return types.SimpleNamespace(_work_dir=work_dir, returncode=0, poll=lambda: 0)

def test_oracle_imports_orchestrator_via_importlib():
    mod = importlib.import_module('harness.orchestrator')
    assert mod is orch
    assert callable(mod.poll_for_submission)
    assert callable(mod.run_agent_phase)

def test_fresh_draft_kept_when_pre_spawn_epoch_forwarded(tmp_path, monkeypatch):
    monkeypatch.setenv('JANUSMASK_MODE', 'planning')
    now = time.time()
    pre_spawn = now - 10
    work_dir, _draft = _make_workdir(tmp_path, now - 5)
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    proc = _fake_proc(work_dir)
    result = orch.poll_for_submission('claude', state_dir, 1, proc, 5, spawn_start_epoch=pre_spawn)
    assert result == DRAFT_TEXT

def test_stale_draft_discarded_when_mtime_predates_epoch(tmp_path, monkeypatch):
    monkeypatch.setenv('JANUSMASK_MODE', 'planning')
    now = time.time()
    work_dir, _draft = _make_workdir(tmp_path, now - 1000)
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    proc = _fake_proc(work_dir)
    result = orch.poll_for_submission('claude', state_dir, 1, proc, 5, spawn_start_epoch=now - 10)
    assert result is None

def test_freshness_gate_monotonic_in_epoch(tmp_path, monkeypatch):
    monkeypatch.setenv('JANUSMASK_MODE', 'planning')
    now = time.time()
    m = now - 100
    work_dir, _draft = _make_workdir(tmp_path, m)
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    proc = _fake_proc(work_dir)
    for epoch in (m - 200, m - 150, m - 1):
        assert orch.poll_for_submission('claude', state_dir, 1, proc, 5, spawn_start_epoch=epoch) == DRAFT_TEXT
    for epoch in (m + 1, m + 50, m + 100):
        assert orch.poll_for_submission('claude', state_dir, 1, proc, 5, spawn_start_epoch=epoch) is None

def test_run_agent_phase_spawns_once_no_retry_storm(tmp_path, monkeypatch):
    monkeypatch.setenv('JANUSMASK_MODE', 'planning')
    work_dir, draft = _make_workdir(tmp_path, time.time() - 5)
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    fake_proc = _fake_proc(work_dir)
    count = {'n': 0}

    def fake_spawn(*a, **k):
        count['n'] += 1
        time.sleep(0.02)
        t = time.time()
        os.utime(draft, (t, t))
        time.sleep(0.02)
        return fake_proc
    monkeypatch.setattr(orch, 'spawn_agent', fake_spawn)
    monkeypatch.setattr(orch, 'kill_agent', lambda *a, **k: None)
    config = {'synthesis': {'timeout_seconds': 5}}
    result = orch.run_agent_phase('claude', 'prompt', config, state_dir, 1, 'planning')
    assert count['n'] == 1
    assert result == DRAFT_TEXT

def test_blocking_spawn_draft_not_discarded_regression(tmp_path, monkeypatch):
    monkeypatch.setenv('JANUSMASK_MODE', 'planning')
    now = time.time()
    pre_spawn = now - 10
    work_dir, _draft = _make_workdir(tmp_path, now - 5)
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    proc = _fake_proc(work_dir)
    assert orch.poll_for_submission('claude', state_dir, 1, proc, 5) is None
    assert orch.poll_for_submission('claude', state_dir, 1, proc, 5, spawn_start_epoch=pre_spawn) == DRAFT_TEXT