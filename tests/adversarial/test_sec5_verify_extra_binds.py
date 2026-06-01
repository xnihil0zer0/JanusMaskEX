"""SEC-5 oracle: Assert that config-driven verify_extra_ro and verify_extra_rw allowlists
are consumed and passed to all jailed verify/mutant subprocesses.

Target path: tests/adversarial/test_sec5_verify_extra_binds.py

RED on HEAD:
  1. build_jail_argv does not accept extra_rw keyword argument or emit --bind for it.
  2. _auto_commit_accepted and run_embedded_tests do not load agent_sandbox.verify_extra_ro/rw
     or pass them to build_jail_argv.

GREEN after fix:
  1. build_jail_argv accepts extra_rw and generates --bind flags.
  2. _auto_commit_accepted and run_embedded_tests consume config and pass lists to build_jail_argv.
"""
import os
import sys
import shutil
import unittest.mock as mock
from pathlib import Path
import pytest

import harness.agent_jail as aj
import harness.orchestrator as orch
import harness.embedded_test_runner as etr


def _make_task():
    return {
        "verification_command": "pytest tests/test_dummy.py",
        "mutations": [{"apply": "true"}],
        "meta_task_type": "harness_self_fix",
    }


def test_build_jail_argv_extra_rw(tmp_path):
    """Assert build_jail_argv supports extra_rw and outputs correct --bind options."""
    ro_dir = tmp_path / "extra_ro_dir"
    ro_dir.mkdir()
    rw_dir = tmp_path / "extra_rw_dir"
    rw_dir.mkdir()

    # Mock bwrap on PATH so build_jail_argv does not fail-close
    original_which = shutil.which
    def mock_which(cmd):
        if cmd == "bwrap":
            return "/usr/bin/bwrap"
        return original_which(cmd)

    with mock.patch("shutil.which", mock_which):
        argv = aj.build_jail_argv(
            ["python3", "-c", "pass"],
            repo_root=tmp_path,
            work_dir=tmp_path,
            state_dir=tmp_path,
            home=tmp_path,
            extra_ro=[ro_dir],
            extra_rw=[rw_dir],
        )

    # Check for --ro-bind ro_dir ro_dir
    ro_bind_found = False
    for i in range(len(argv) - 2):
        if argv[i] == "--ro-bind" and argv[i+1] == str(ro_dir) and argv[i+2] == str(ro_dir):
            ro_bind_found = True
            break
    assert ro_bind_found, "extra_ro bind not found in jail argv"

    # Check for --bind rw_dir rw_dir
    rw_bind_found = False
    for i in range(len(argv) - 2):
        if argv[i] == "--bind" and argv[i+1] == str(rw_dir) and argv[i+2] == str(rw_dir):
            rw_bind_found = True
            break
    assert rw_bind_found, "extra_rw bind not found in jail argv"


def test_sec5_verify_extra_binds_orchestrator(tmp_path):
    """Assert orchestrator's verification & mutant runs receive config-driven ro/rw allowlists."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (tmp_path / "JanusMaskJR_staging").mkdir()

    task = _make_task()
    task_id = "sec5_jail_extra_binds_orch"

    build_jail_calls = []

    def mock_build_jail_argv(cmd, **kwargs):
        build_jail_calls.append(kwargs)
        return ["/usr/bin/bwrap"] + list(cmd)

    def mock_run(cmd, *args, **kwargs):
        proc = mock.MagicMock()
        proc.returncode = 0
        if isinstance(cmd, list) and cmd[:2] == ["git", "rev-parse"]:
            proc.stdout = str(tmp_path / "JanusMaskJR")
            proc.stderr = ""
        else:
            proc.stdout = ""
            proc.stderr = ""
        return proc

    git_stub = mock.MagicMock()
    git_stub.commit_accepted_output.return_value = {"committed": True, "sha": "deadbeef"}

    cfg = {
        "agent_sandbox": {
            "bwrap": True,
            "verify_extra_ro": ["/mock/extra_ro1", "/mock/extra_ro2"],
            "verify_extra_rw": ["/mock/extra_rw1"],
        },
        "synthesis": {},
    }

    with mock.patch("harness.orchestrator.subprocess.run", side_effect=mock_run), \
         mock.patch("harness.orchestrator._resolve_files_touched", return_value=["dummy.py"]), \
         mock.patch("harness.orchestrator._resolve_verification_command", return_value="pytest tests/test_dummy.py"), \
         mock.patch("harness.orchestrator._apply_approval_granted", return_value=True), \
         mock.patch("harness.orchestrator._rollback_rejected_commit"), \
         mock.patch("harness.orchestrator._mark_processed"), \
         mock.patch("harness.orchestrator.load_config", return_value=cfg), \
         mock.patch("harness.git_integration", git_stub), \
         mock.patch("harness._journal.write_jsonl_row"), \
         mock.patch("harness.agent_jail.build_jail_argv", side_effect=mock_build_jail_argv), \
         mock.patch("shutil.copytree"), \
         mock.patch("shutil.rmtree"), \
         mock.patch("os.symlink"):
        (tmp_path / "JanusMaskJR").mkdir(exist_ok=True)
        orch._auto_commit_accepted(state_dir, task, task_id)

    # We expect exactly three calls to build_jail_argv under mutation gate:
    # 1. Main verification
    # 2. Mutant baseline verification
    # 3. Mutant application
    # 4. Mutant rerun
    assert len(build_jail_calls) >= 3, f"Expected at least 3 build_jail_argv calls, got {len(build_jail_calls)}"

    for i, kw in enumerate(build_jail_calls):
        extra_ro = list(kw.get("extra_ro", ()))
        extra_rw = list(kw.get("extra_rw", ()))

        # Verify defaults (sys.base_prefix, sys.prefix) are still present
        assert sys.base_prefix in extra_ro, f"Call #{i}: sys.base_prefix missing"
        assert sys.prefix in extra_ro, f"Call #{i}: sys.prefix missing"

        # Verify config allowlists are present
        assert "/mock/extra_ro1" in extra_ro, f"Call #{i}: extra_ro1 missing"
        assert "/mock/extra_ro2" in extra_ro, f"Call #{i}: extra_ro2 missing"
        assert "/mock/extra_rw1" in extra_rw, f"Call #{i}: extra_rw1 missing"


def test_sec5_verify_extra_binds_embedded_runner(tmp_path):
    """Assert embedded test runner's collect/run stages receive config-driven ro/rw allowlists."""
    build_jail_calls = []

    def mock_build_jail_argv(cmd, **kwargs):
        build_jail_calls.append(kwargs)
        return ["/usr/bin/bwrap"] + list(cmd)

    def mock_run(cmd, *args, **kwargs):
        proc = mock.MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        return proc

    cfg = {
        "agent_sandbox": {
            "bwrap": True,
            "verify_extra_ro": ["/mock/extra_ro1", "/mock/extra_ro2"],
            "verify_extra_rw": ["/mock/extra_rw1"],
        },
        "synthesis": {},
    }

    # NB: run_embedded_tests imports load_config + build_jail_argv + sandbox_enabled
    # LAZILY in-body (from harness.orchestrator / harness.agent_jail), so the patch
    # targets must be the SOURCE modules, not harness.embedded_test_runner.* (which
    # lacks those attributes). subprocess IS a module-level import here, so
    # harness.embedded_test_runner.subprocess.run is patchable directly.
    with mock.patch("harness.embedded_test_runner.subprocess.run", side_effect=mock_run), \
         mock.patch("harness.orchestrator.load_config", return_value=cfg), \
         mock.patch("harness.agent_jail.build_jail_argv", side_effect=mock_build_jail_argv):
        etr.run_embedded_tests(module_name="test_dummy", module_src="def test_pass(): pass")

    # We expect 2 calls to build_jail_argv (collect-only and actual test run)
    assert len(build_jail_calls) == 2, f"Expected 2 build_jail_argv calls, got {len(build_jail_calls)}"

    for i, kw in enumerate(build_jail_calls):
        extra_ro = list(kw.get("extra_ro", ()))
        extra_rw = list(kw.get("extra_rw", ()))

        # Verify defaults (sys.base_prefix, sys.prefix) are still present
        assert sys.base_prefix in extra_ro, f"Call #{i}: sys.base_prefix missing"
        assert sys.prefix in extra_ro, f"Call #{i}: sys.prefix missing"

        # Verify config allowlists are present
        assert "/mock/extra_ro1" in extra_ro, f"Call #{i}: extra_ro1 missing"
        assert "/mock/extra_ro2" in extra_ro, f"Call #{i}: extra_ro2 missing"
        assert "/mock/extra_rw1" in extra_rw, f"Call #{i}: extra_rw1 missing"


def test_sec5_verify_extra_binds_default_config(tmp_path):
    """Assert that when allowlists are omitted, defaults are cleanly used and no extra binds occur."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (tmp_path / "JanusMaskJR_staging").mkdir()

    task = _make_task()
    task_id = "sec5_jail_extra_binds_default"

    build_jail_calls = []

    def mock_build_jail_argv(cmd, **kwargs):
        build_jail_calls.append(kwargs)
        return ["/usr/bin/bwrap"] + list(cmd)

    def mock_run(cmd, *args, **kwargs):
        proc = mock.MagicMock()
        proc.returncode = 0
        if isinstance(cmd, list) and cmd[:2] == ["git", "rev-parse"]:
            proc.stdout = str(tmp_path / "JanusMaskJR")
            proc.stderr = ""
        else:
            proc.stdout = ""
            proc.stderr = ""
        return proc

    git_stub = mock.MagicMock()
    git_stub.commit_accepted_output.return_value = {"committed": True, "sha": "deadbeef"}

    # Default configuration omitting verify_extra_ro/rw
    cfg = {
        "agent_sandbox": {
            "bwrap": True
        },
        "synthesis": {},
    }

    with mock.patch("harness.orchestrator.subprocess.run", side_effect=mock_run), \
         mock.patch("harness.orchestrator._resolve_files_touched", return_value=["dummy.py"]), \
         mock.patch("harness.orchestrator._resolve_verification_command", return_value="pytest tests/test_dummy.py"), \
         mock.patch("harness.orchestrator._apply_approval_granted", return_value=True), \
         mock.patch("harness.orchestrator._rollback_rejected_commit"), \
         mock.patch("harness.orchestrator._mark_processed"), \
         mock.patch("harness.orchestrator.load_config", return_value=cfg), \
         mock.patch("harness.git_integration", git_stub), \
         mock.patch("harness._journal.write_jsonl_row"), \
         mock.patch("harness.agent_jail.build_jail_argv", side_effect=mock_build_jail_argv), \
         mock.patch("shutil.copytree"), \
         mock.patch("shutil.rmtree"), \
         mock.patch("os.symlink"):
        (tmp_path / "JanusMaskJR").mkdir(exist_ok=True)
        orch._auto_commit_accepted(state_dir, task, task_id)

    assert len(build_jail_calls) >= 3, f"Expected at least 3 build_jail_argv calls, got {len(build_jail_calls)}"

    for i, kw in enumerate(build_jail_calls):
        extra_ro = list(kw.get("extra_ro", ()))
        extra_rw = list(kw.get("extra_rw", ()))

        # Verify only sys.base_prefix and sys.prefix are in extra_ro
        assert extra_ro == [sys.base_prefix, sys.prefix]
        # Verify extra_rw is empty (or defaults to empty sequence)
        assert not extra_rw
