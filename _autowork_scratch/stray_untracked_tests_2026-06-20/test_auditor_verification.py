import os
import sys
import json
import time
import shutil
import hashlib
import pathlib
import subprocess
import yaml
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to python path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import harness.paths as paths
import harness.state_reconciler as state_reconciler
import harness.control_gate as control_gate
import harness.autowork_daemon as autowork_daemon

def test_finding_7_agent_workroot_ignores_env_var(monkeypatch):
    """
    Finding 7: Agent Workroot Env Var Override Mismatch
    Verifies that harness.state_reconciler.agent_workroot ignores JANUSMASK_AGENT_WORKROOT env override.
    """
    override_path = "/tmp/override_workroot_finding_7"
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", override_path)
    
    # paths.agent_workroot() honors the override
    assert str(paths.agent_workroot()) == override_path
    
    # state_reconciler.agent_workroot() ignores it and uses the repo name peer
    reconciler_derived = state_reconciler.agent_workroot("/home/xnihil0zer0/JanusMaskJR")
    assert str(reconciler_derived) == "/home/xnihil0zer0/JanusMaskJR_agentwork"
    assert str(reconciler_derived) != override_path

def test_finding_8_git_worktree_list_failure_deletes(tmp_path):
    """
    Finding 8: Fail-Safe Violation on Git Worktree List Failure
    Verifies that if git worktree list returns empty (e.g., due to failure),
    reap_orphaned_workdirs deletes active worktree directories without failing closed.
    """
    repo = tmp_path / 'repo'
    repo.mkdir()
    
    # Peer directory for agent workroot as derived by state_reconciler.agent_workroot
    agent_workroot = tmp_path / 'repo_agentwork'
    agent_workroot.mkdir()
    
    agent_dir = agent_workroot / 'agent1'
    agent_dir.mkdir()
    
    # Create workdir corresponding to an active worktree
    workdir = agent_dir / 'agent1-r1-task1-12345678'
    workdir.mkdir()
    
    # Set mtime to older than grace to make it eligible for reap
    old_time = time.time() - 3600
    os.utime(workdir, (old_time, old_time))
    
    # Mock git_worktree_list to simulate a failure/empty list
    with patch('harness.state_reconciler.git_worktree_list', return_value=[]):
        # Even though the workdir is registered (not mocked here), 
        # because git_worktree_list returned [], the reconciler proceeds and deletes it.
        state_reconciler.reap_orphaned_workdirs(repo, grace=60)
        
    assert not workdir.exists()

def test_finding_9_reconcile_ledger_heads_unlocked_race(tmp_path):
    """
    Finding 9: Non-atomic and Unlocked Ledger Re-writing in _reconcile_stale_ledger_heads
    Verifies that a concurrent write is overwritten and lost because _reconcile_stale_ledger_heads
    does not lock or write atomically.
    """
    repo = tmp_path / 'repo'
    repo.mkdir()
    
    state_dir = repo / 'state'
    state_dir.mkdir()
    ledger_path = state_dir / 'impl_progress.jsonl'
    
    # Write initial accepted row to trigger head revert pop
    initial_row = {'ts': time.time() - 100, 'phase': 'accepted', 'event': 'auto_commit', 'task_id': 'task_1', 'commit_sha': 'deadbeef'}
    ledger_path.write_text(json.dumps(initial_row) + '\n', encoding='utf-8')
    
    original_run = subprocess.run
    def mock_run(args, **kwargs):
        if len(args) > 3 and args[3] == 'merge-base':
            # Simulate a concurrent append while the reconciler is running git check
            concurrent_row = {'ts': time.time(), 'phase': 'accepted', 'event': 'auto_commit', 'task_id': 'task_concurrent', 'commit_sha': 'feedface'}
            with open(ledger_path, 'a') as f:
                f.write(json.dumps(concurrent_row) + '\n')
            return subprocess.CompletedProcess(args, 1, stdout='', stderr='')
        return original_run(args, **kwargs)
        
    with patch('subprocess.run', side_effect=mock_run):
        state_reconciler._reconcile_stale_ledger_heads(repo)
        
    # Read the ledger after. The concurrent row is completely lost!
    lines = ledger_path.read_text(encoding='utf-8').splitlines()
    rows = [json.loads(l) for l in lines]
    
    assert any(r.get('task_id') == 'task_1' for r in rows)
    assert any(r.get('event') == 'task_blocked' for r in rows) # the popped row
    
    # This assertion proves the concurrent row was lost
    with pytest.raises(AssertionError):
        assert any(r.get('task_id') == 'task_concurrent' for r in rows)

def test_finding_10_unsafe_60s_grace(tmp_path):
    """
    Finding 10: Unsafe 60-second Default Grace in Standalone Disk Reaper
    Verifies that standalone cleanup_state/reap_stale_disk defaults to 60s grace,
    which deletes directories newer than 24 hours.
    """
    repo = tmp_path / 'repo'
    repo.mkdir()
    
    agent_workroot = tmp_path / 'repo_agentwork'
    agent_workroot.mkdir()
    
    agent_dir = agent_workroot / 'agent1'
    agent_dir.mkdir()
    
    # Workdir that is 10 minutes old (600s) -> should be kept under 24h grace, but is reaped under 60s grace
    workdir = agent_dir / 'agent1-r1-task1-12345678'
    workdir.mkdir()
    ten_min_ago = time.time() - 600
    os.utime(workdir, (ten_min_ago, ten_min_ago))
    
    # Run standalone cleanup
    with patch('harness.state_reconciler.git_worktree_list', return_value=[]):
        state_reconciler.cleanup_state(repo, mode='apply')
        
    assert not workdir.exists()

def test_finding_11_planned_stale_archives_brief_instead_of_plan(tmp_path):
    """
    Finding 11: Stale Plan Leak (Catastrophic PLANNED_STALE Archival Defect)
    Verifies that _reclaim_zombie_briefs archives the updated brief instead of the stale plan.
    """
    repo = tmp_path / 'repo'
    repo.mkdir()
    
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    (state_dir / 'control' / 'autowork').mkdir(parents=True)
    (state_dir / 'tasks' / 'processed').mkdir(parents=True)
    
    # Create config.yaml to enable state_reconcile
    harness_dir = tmp_path / 'harness'
    harness_dir.mkdir()
    (harness_dir / 'config.yaml').write_text('autowork:\n  state_reconcile: true\n', encoding='utf-8')
    
    # Updated brief
    slug = 'stale_test'
    brief = repo / f'brief_hooks_{slug}.md'
    brief.write_text("updated brief content", encoding='utf-8')
    
    # Stale plan (mismatched SHA)
    plan = repo / f'plan_hooks_{slug}.json'
    plan.write_text(json.dumps({
        'source_brief_sha256': 'wrong_sha_value',
        'tasks': [{'task_id': 'task_1'}]
    }), encoding='utf-8')
    
    # Run reclaim sweep
    autowork_daemon._reclaim_zombie_briefs(repo, state_dir)
    
    # The updated brief was deleted from the repo (archived)
    assert not brief.exists()
    
    # The stale plan was also deleted (archived as an orphan only because the brief was deleted first)
    assert not plan.exists()
    
    # In a correct implementation, the updated brief must remain in the repo root to be re-planned,
    # and only the stale plan should be archived.

def test_finding_12_orphaned_plans_not_archived_standalone(tmp_path):
    """
    Finding 12: Orphaned Plan File Leak
    Verifies that standalone cleanup_state does not archive orphaned plan files in the repo root.
    """
    repo = tmp_path / 'repo'
    repo.mkdir()
    
    # Create an orphaned plan directly in the repo root
    plan_path = repo / 'plan_hooks_orphaned.json'
    plan_path.write_text(json.dumps({
        'source_brief_sha256': '0'*64,
        'tasks': []
    }), encoding='utf-8')
    
    state_reconciler.cleanup_state(repo, mode='apply')
    
    # Standalone cleanup fails to archive it because it only looks in <root>/products/
    assert plan_path.exists()

def test_finding_19_allowlist_id_misalignment(tmp_path):
    """
    Finding 19: T4 Allowlist ID Misalignment
    Verifies that setting task IDs (e.g. T1, T2, T3) in auto_promote.allowlist
    does not match the actual brief slugs.
    """
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    (state_dir / 'control' / 'autowork').mkdir(parents=True)
    
    # Recovery plan tells operator to write T1, T2, T3
    allowlist = state_dir / 'control' / 'autowork' / 'auto_promote.allowlist'
    allowlist.write_text("T1\nT2\nT3\n", encoding='utf-8')
    
    allow = autowork_daemon._auto_promote_allowlist(state_dir)
    assert allow == {'T1', 'T2', 'T3'}
    
    # The actual brief slug (e.g. stale-reconcile-serialization-lock) does not match
    real_slug = 'stale-reconcile-serialization-lock'
    assert real_slug not in allow

def test_finding_20_watchdog_active_when_paused(tmp_path):
    """
    Finding 20: Inactivity Watchdog Pause-Blindness & Flaky LLM Escalation
    Verifies that _check_inactivity_watchdog triggers and escalates even when the daemon is paused.
    """
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    (state_dir / 'control' / 'autowork').mkdir(parents=True)
    
    # Pause flag exists
    pause_flag = state_dir / 'control' / 'autowork' / 'pause'
    pause_flag.write_text("paused")
    
    # Mock compute_autowork_backlog to return unfinished work
    mock_brief_status = MagicMock()
    mock_brief_status.compute_autowork_backlog.return_value = {
        'eligible_with_work': ['some-stuck-brief']
    }
    sys.modules['harness.brief_status'] = mock_brief_status
    
    # Ledger has old event
    ledger_path = state_dir / 'impl_progress.jsonl'
    ledger_path.write_text(json.dumps({'ts': time.time() - 3600, 'phase': 'accepted', 'event': 'auto_commit', 'task_id': 'task_1'}) + '\n')
    
    escalated = False
    def mock_escalate(s_dir, cfg):
        nonlocal escalated
        escalated = True
        
    with patch('harness.autowork_daemon._escalate_inactivity', side_effect=mock_escalate):
        autowork_daemon._check_inactivity_watchdog(tmp_path / 'repo', state_dir, {})
        
    assert escalated # Triggers escalation despite being paused!

def test_finding_21_pause_flag_discrepancy(tmp_path):
    """
    Finding 21: Pause Flag Path Config Discrepancy
    Verifies that control_gate and autowork_daemon resolve two different paths for the pause flag.
    """
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    
    config = {
        'control': {
            'pause_flag_path': 'state/control/orchestrator.flag'
        }
    }
    
    cg_path = control_gate.pause_flag_path(state_dir, config)
    ad_path = autowork_daemon._pause_flag_path(state_dir)
    
    assert cg_path != ad_path
    assert str(cg_path).endswith('state/control/orchestrator.flag')
    assert str(ad_path).endswith('state/control/autowork/pause')

def test_finding_22_inert_cleanup_entrypoint(tmp_path):
    """
    Finding 22: Inert Workspace Cleanup Entrypoint
    Verifies that cleanup_state only scans <root>/products, which is nonexistent in the repo layout.
    """
    repo = tmp_path / 'repo'
    repo.mkdir()
    
    # Create plan and brief in repo root
    brief = repo / 'brief_hooks_test.md'
    brief.touch()
    plan = repo / 'plan_hooks_test.json'
    plan.touch()
    
    # Check that cleanup_state doesn't read either, returning status with 0 products
    status = state_reconciler.cleanup_state(repo)
    assert len(status.products) == 0

def test_finding_23_compaction_reads_before_lock(tmp_path):
    """
    Finding 23: Ledger Compaction Race Condition
    Verifies that compact_impl_progress_ledger reads the ledger before taking the lock,
    allowing concurrent writes to be overwritten and lost.
    """
    repo = tmp_path / 'repo'
    repo.mkdir()
    state_dir = repo / 'state'
    state_dir.mkdir()
    ledger_path = state_dir / 'impl_progress.jsonl'
    
    # Initial ledger row
    initial_row = {'ts': time.time(), 'phase': 'accepted', 'event': 'auto_commit', 'task_id': 'task_1'}
    ledger_path.write_text(json.dumps(initial_row) + '\n', encoding='utf-8')
    
    # We will mock Path.read_text for ledger_path. During the read, we will append a concurrent row.
    original_read = Path.read_text
    def mock_read(self, *args, **kwargs):
        res = original_read(self, *args, **kwargs)
        if 'impl_progress.jsonl' in str(self):
            # Concurrent append after read but before flock
            concurrent_row = {'ts': time.time(), 'phase': 'accepted', 'event': 'auto_commit', 'task_id': 'task_concurrent'}
            with open(ledger_path, 'a') as f:
                f.write(json.dumps(concurrent_row) + '\n')
        return res
        
    # We must allow the compaction to perform a drop to trigger writing. 
    # To do this, we append a non-allowlisted line so it gets dropped.
    with open(ledger_path, 'a') as f:
        f.write("invalid line to drop\n")
        
    with patch.object(Path, 'read_text', mock_read):
        state_reconciler.compact_impl_progress_ledger(repo)
        
    # Read the ledger after compaction
    lines = ledger_path.read_text(encoding='utf-8').splitlines()
    rows = [json.loads(l) for l in lines]
    
    assert any(r.get('task_id') == 'task_1' for r in rows)
    
    # Proves the concurrent row was lost
    with pytest.raises(AssertionError):
        assert any(r.get('task_id') == 'task_concurrent' for r in rows)
