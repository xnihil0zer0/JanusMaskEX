"""H2C oracle: prove the embedded-test subprocesses are jail-wrapped
when sandbox is enabled.

RED on HEAD: the subprocess runs inside ``run_embedded_tests`` are dispatched
directly without bubblewrap, so the tests assert they start with bwrap and fail.

GREEN after: both subprocesses are wrapped via ``build_jail_argv`` and run jailely.
"""
import os
import sys
import shutil
import pathlib
import subprocess
import unittest.mock as mock
import pytest

from harness.embedded_test_runner import run_embedded_tests

_BWRAP = "/usr/bin/bwrap"


def test_h2c_embedded_tests_are_jailed_when_sandbox_enabled():
    """Prove that embedded-test subprocesses are jail-wrapped when sandbox is enabled."""
    cfg = {"agent_sandbox": {"bwrap": True}}
    run_calls = []

    def mock_run(cmd, *args, **kwargs):
        run_calls.append(cmd)
        proc = mock.MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        return proc

    # Source code with tests so should_run_embedded_tests passes
    src = "def test_dummy():\n    pass\n"

    with mock.patch("harness.orchestrator.load_config", return_value=cfg), \
         mock.patch("harness.embedded_test_runner.subprocess.run", side_effect=mock_run), \
         mock.patch("shutil.which", return_value=_BWRAP):
        
        run_embedded_tests("dummy_module", src)

    # We expect two subprocess runs: collect and run.
    assert len(run_calls) == 2, f"Expected 2 subprocess runs, got: {run_calls!r}"

    for i, cmd in enumerate(run_calls):
        assert isinstance(cmd, list), f"Command #{i} must be a list: {cmd!r}"
        assert cmd[0] == _BWRAP, f"Command #{i} must start with {_BWRAP!r}: {cmd!r}"
        assert "--ro-bind" in cmd, f"Command #{i} must contain '--ro-bind': {cmd!r}"
        assert "python3" in cmd, f"Command #{i} must run python3 instead of sys.executable: {cmd!r}"
        # Make sure sys.base_prefix is extra_ro bound
        assert sys.base_prefix in cmd, f"Command #{i} must bind sys.base_prefix: {cmd!r}"


def test_h2c_embedded_tests_run_unjailed_when_sandbox_disabled():
    """Prove that embedded-test subprocesses run unjailed when sandbox is disabled."""
    cfg = {"agent_sandbox": {"bwrap": False}}
    run_calls = []

    def mock_run(cmd, *args, **kwargs):
        run_calls.append(cmd)
        proc = mock.MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        return proc

    src = "def test_dummy():\n    pass\n"

    with mock.patch("harness.orchestrator.load_config", return_value=cfg), \
         mock.patch("harness.embedded_test_runner.subprocess.run", side_effect=mock_run), \
         mock.patch("shutil.which", return_value=_BWRAP):
        
        run_embedded_tests("dummy_module", src)

    assert len(run_calls) == 2, f"Expected 2 subprocess runs, got: {run_calls!r}"

    for i, cmd in enumerate(run_calls):
        assert isinstance(cmd, list), f"Command #{i} must be a list: {cmd!r}"
        assert cmd[0] == sys.executable, f"Command #{i} must start with sys.executable: {cmd!r}"
        assert "bwrap" not in " ".join(cmd), f"Command #{i} must not contain bwrap: {cmd!r}"


def test_h2c_embedded_tests_fail_closed_when_bwrap_unavailable_but_sandbox_enabled():
    """Prove that if bwrap is missing but sandbox is enabled, the run fails closed."""
    cfg = {"agent_sandbox": {"bwrap": True}}
    src = "def test_dummy():\n    pass\n"

    with mock.patch("harness.orchestrator.load_config", return_value=cfg), \
         mock.patch("shutil.which", return_value=None):
        
        with pytest.raises(FileNotFoundError, match="refusing to spawn an un-jailed agent"):
            run_embedded_tests("dummy_module", src)
