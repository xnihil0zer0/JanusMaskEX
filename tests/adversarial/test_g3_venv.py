"""Pytest oracle for G3_VENV (REV23 §3-5).

RED on HEAD: the auto-commit path does not yet jail external execution against
the target's .venv by adding .venv to extra_ro and prefixing .venv/bin to PATH.
It also does not refuse (fail-closed) when the target's .venv/bin/python is absent.
"""

from __future__ import annotations

import inspect
import pytest

from harness.orchestrator import _auto_commit_accepted


def test_external_venv_in_extra_ro_source():
    """Verify that the external target's .venv is added to extra_ro at all 4 sites."""
    src = inspect.getsource(_auto_commit_accepted)
    # Check that _ext_venv_ro helper is defined and used
    assert "_ext_venv_ro" in src, (
        "Expected '_ext_venv_ro' helper list to be defined inside _auto_commit_accepted"
    )
    assert "worktree_root / '.venv'" in src or 'worktree_root / ".venv"' in src, (
        "Expected '.venv' directory to be referenced relative to worktree_root"
    )
    # Check that the sites concatenate the venv-ro list into extra_ro (genuine
    # RED token: '_ext_venv_ro' is referenced in an extra_ro expression today
    # only AFTER the fix lands).
    assert "_ext_venv_ro" in src and "extra_ro" in src, (
        "Expected _ext_venv_ro to be concatenated into the extra_ro argument "
        "at the build_jail_argv sites"
    )


def test_external_venv_bin_on_path_source():
    """Verify that the external target's .venv/bin is prefixed to PATH."""
    src = inspect.getsource(_auto_commit_accepted)
    assert "_venv_jail_env" in src, (
        "Expected nested helper '_venv_jail_env' to be defined inside _auto_commit_accepted"
    )
    assert "PATH" in src, (
        "Expected 'PATH' environment variable to be referenced in the nested helper"
    )
    assert "bin" in src, (
        "Expected 'bin' directory to be referenced in the PATH prefix logic"
    )
    # Check for PATH prefixing logic
    assert "PATH" in src and ".venv" in src and "bin" in src


def test_no_venv_refusal_source():
    """Verify that missing target .venv raises a fail-closed RuntimeError refusal."""
    src = inspect.getsource(_auto_commit_accepted)
    assert "RuntimeError" in src, (
        "Expected RuntimeError to be raised when external .venv is missing"
    )
    assert "G3_VENV" in src, (
        "Expected 'G3_VENV' to be mentioned in the refusal exception message or context"
    )
    assert ".venv" in src, (
        "Expected '.venv' to be mentioned in the refusal exception message or context"
    )
    assert "fail-closed" in src or "refusal" in src or "absent" in src or "missing" in src, (
        "Expected refusal exception to describe the no-venv/fail-closed condition"
    )


def test_self_negative_control_creds_unchanged():
    """Verify bind_credentials=False is still present 4x and unshare is not widened (stays green)."""
    src = inspect.getsource(_auto_commit_accepted)
    # Split by the docstring block to check only the code body
    parts = src.split('"""', 2)
    code_body = parts[2] if len(parts) > 2 else src
    count = code_body.count("bind_credentials=False")
    assert count == 4, f"Expected bind_credentials=False to be present exactly 4 times in the code body, found {count}"
    
    # Verify we did not introduce any new 'unshare' parameters/arguments in the build_jail_argv calls
    assert "unshare=" not in code_body
    unshare_count = code_body.lower().count("unshare")
    assert unshare_count == 0, f"Expected 'unshare' to not be introduced in code, but found it {unshare_count} times"
