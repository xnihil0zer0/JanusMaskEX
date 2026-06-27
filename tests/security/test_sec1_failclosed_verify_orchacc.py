"""SEC-1 fail-closed verification orchestrator oracle: filtered D-Bus proxy failure.

Final dest test path: tests/security/test_sec1_failclosed_verify_orchacc.py
"""
from __future__ import annotations

import os
import shutil
import unittest.mock as mock
from pathlib import Path

import pytest

import harness.agent_jail as agent_jail
import harness.dbus_proxy as dbus_proxy
import harness.git_integration as git_integration
import harness._journal as journal
from harness.orchestrator import _auto_commit_accepted


class _FakeRaisingProxyCM:
    """Fake D-Bus proxy context manager whose __enter__ raises RuntimeError."""

    def __enter__(self):
        raise RuntimeError("Fake D-Bus proxy failure: xdg-dbus-proxy failed to start.")

    def __exit__(self, exc_type, exc, tb):
        return False


def _drive_auto_commit(tmp_path, monkeypatch, *, sandbox_enabled, xdg_dbus_proxy_path, captured=None):
    """Drive ``_auto_commit_accepted`` to (and through) the four jailed spawns."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    # mutant work_dir / staging sibling + worktree root must be real dirs:
    (tmp_path / "JanusMaskEX_staging").mkdir()
    (tmp_path / "JanusMaskEX").mkdir(exist_ok=True)

    task = {
        "verification_command": "pytest tests/test_dummy.py",
        "mutations": [{"apply": "true"}],
        "meta_task_type": "harness_self_fix",
    }
    task_id = "sec1_failclosed_verify_orchacc_probe"

    def _proxy_factory(*args, **kwargs):
        return _FakeRaisingProxyCM()

    monkeypatch.setattr(dbus_proxy, "proxied_session_bus", _proxy_factory)

    if captured is None:
        captured = []

    def _bja_recorder(cmd, *, repo_root, work_dir, state_dir, dbus_proxy_socket=None, **kwargs):
        captured.append(dbus_proxy_socket)
        return ["/usr/bin/bwrap", "--ro-bind", "/", "/"] + list(cmd)

    monkeypatch.setattr(agent_jail, "build_jail_argv", _bja_recorder)
    monkeypatch.setattr(agent_jail, "sandbox_enabled", lambda cfg: bool(sandbox_enabled))
    monkeypatch.setattr(
        "harness.orchestrator.load_config",
        lambda: {"agent_sandbox": {"bwrap": bool(sandbox_enabled)}, "synthesis": {}},
    )

    run_calls = []

    def _mock_run(cmd, *args, **kwargs):
        run_calls.append(cmd)
        proc = mock.MagicMock()
        proc.returncode = 0
        if isinstance(cmd, list) and cmd[:2] == ["git", "rev-parse"]:
            proc.stdout = str(tmp_path / "JanusMaskEX")
        else:
            proc.stdout = ""
        proc.stderr = ""
        return proc

    monkeypatch.setattr("harness.orchestrator.subprocess.run", _mock_run)

    git_stub = mock.MagicMock()
    git_stub.commit_accepted_output.return_value = {"committed": True, "sha": "deadbeef"}

    monkeypatch.setattr("harness.orchestrator._resolve_files_touched", lambda *a, **kw: ["dummy.py"])
    monkeypatch.setattr(
        "harness.orchestrator._resolve_verification_command",
        lambda *a, **kw: "pytest tests/test_dummy.py",
    )
    monkeypatch.setattr("harness.orchestrator._apply_approval_granted", lambda *a, **kw: True)
    monkeypatch.setattr("harness.orchestrator._rollback_rejected_commit", mock.MagicMock())
    monkeypatch.setattr("harness.orchestrator._mark_processed", mock.MagicMock())
    monkeypatch.setattr("harness.orchestrator._mark_blocked", mock.MagicMock())
    monkeypatch.setattr(git_integration, "commit_accepted_output", git_stub.commit_accepted_output)
    monkeypatch.setattr(git_integration, "create_staging_worktree", mock.MagicMock())
    monkeypatch.setattr(git_integration, "remove_staging_worktree", mock.MagicMock())
    monkeypatch.setattr(git_integration, "merge_staging_to_parent", mock.MagicMock())
    monkeypatch.setattr(journal, "write_jsonl_row", mock.MagicMock())

    original_which = shutil.which
    def mock_which(binary):
        if binary == "xdg-dbus-proxy":
            return xdg_dbus_proxy_path
        if binary == "bwrap":
            return "/usr/bin/bwrap"
        return original_which(binary)
    monkeypatch.setattr(shutil, "which", mock_which)

    monkeypatch.setattr(shutil, "copytree", mock.MagicMock())
    monkeypatch.setattr(shutil, "rmtree", mock.MagicMock())
    monkeypatch.setattr(os, "symlink", mock.MagicMock())

    _auto_commit_accepted(state_dir, task, task_id)
    return captured


def test_sec1_failclosed_verify_orchacc_refuses_on_proxy_failure(tmp_path, monkeypatch):
    """TEST 1 (RED on HEAD): with sandbox on + which truthy + proxy raising,
    assert _auto_commit_accepted raises RuntimeError matching 'fail-closed'
    AND that build_jail_argv was NEVER called with dbus_proxy_socket=None.
    """
    captured = []
    with pytest.raises(RuntimeError, match="fail-closed"):
        _drive_auto_commit(
            tmp_path,
            monkeypatch,
            sandbox_enabled=True,
            xdg_dbus_proxy_path="/usr/bin/xdg-dbus-proxy",
            captured=captured,
        )

    # Assert build_jail_argv was NEVER called with dbus_proxy_socket=None
    # (On HEAD it does not raise and does call with None)
    assert None not in captured, f"build_jail_argv was called with None: {captured!r}"


def test_sec1_failclosed_verify_orchacc_graceful_degrade(tmp_path, monkeypatch):
    """TEST 2 (NEGATIVE CONTROL, must pass on HEAD and after fix):
    set shutil.which('xdg-dbus-proxy') to None (binary absent); proxy still raises;
    assert NO RuntimeError('fail-closed') escapes (graceful degrade preserved).
    """
    captured = []
    res = _drive_auto_commit(
        tmp_path,
        monkeypatch,
        sandbox_enabled=True,
        xdg_dbus_proxy_path=None,
        captured=captured,
    )
    # The negative control must pass on HEAD and after fix
    assert res is not None
    assert None in captured
