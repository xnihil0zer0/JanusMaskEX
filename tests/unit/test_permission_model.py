import pytest
from pathlib import Path
from services.permission_model import PermissionMode, PermissionPolicy, PermissionEnforcer, _execute_bypass

def test_permission_mode_ordering():
    assert PermissionMode.READ_ONLY < PermissionMode.WORKSPACE_WRITE
    assert PermissionMode.WORKSPACE_WRITE < PermissionMode.ALLOW
    assert PermissionMode.ALLOW < PermissionMode.DANGER_FULL_ACCESS

def test_policy_creation():
    policy = PermissionPolicy.for_worker_type('hunt')
    assert policy.active_mode == PermissionMode.WORKSPACE_WRITE
    assert 'tmp/' in policy.allowed_paths
    policy_simple = PermissionPolicy.for_worker_type('simple')
    assert policy_simple.active_mode == PermissionMode.READ_ONLY

def test_enforcer_check_tool():
    policy = PermissionPolicy.for_worker_type('simple')
    enforcer = PermissionEnforcer(policy)
    assert enforcer.check_tool('proxy_read_file').allowed
    assert not enforcer.check_tool('proxy_write_file').allowed

def test_enforcer_check_file_write(tmp_path):
    policy = PermissionPolicy(active_mode=PermissionMode.WORKSPACE_WRITE, workspace_root=tmp_path, allowed_paths=['tmp/', 'data/'])
    enforcer = PermissionEnforcer(policy)
    assert enforcer.check_file_write(tmp_path / 'tmp' / 'test.txt').allowed
    assert enforcer.check_file_write(tmp_path / 'data' / 'sub' / 'test.txt').allowed
    outside_path = tmp_path.parent / 'outside.txt'
    assert not enforcer.check_file_write(outside_path).allowed
    assert not enforcer.check_file_write(tmp_path / 'other' / 'test.txt').allowed

def test_enforcer_check_bash():
    policy = PermissionPolicy.for_worker_type('simple')
    enforcer = PermissionEnforcer(policy)
    assert enforcer.check_bash('ls -la').allowed
    assert enforcer.check_bash('git diff').allowed
    assert not enforcer.check_bash("echo 'hello' > test.txt").allowed
    assert not enforcer.check_bash("git commit -m 'test'").allowed

def test_execute_bypass():
    session_id = 'test-session'
    assert session_id not in _execute_bypass
    _execute_bypass.add(session_id)
    assert session_id in _execute_bypass
    _execute_bypass.discard(session_id)
    assert session_id not in _execute_bypass