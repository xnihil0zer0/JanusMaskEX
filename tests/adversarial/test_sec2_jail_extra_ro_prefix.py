"""SEC-2 oracle: Assert that all three jailed subprocesses in _auto_commit_accepted
pass sys.prefix in extra_ro alongside sys.base_prefix.

Target path: tests/adversarial/test_sec2_jail_extra_ro_prefix.py

RED on HEAD: the three subprocess calls pass extra_ro=[sys.base_prefix] and omit sys.prefix.
GREEN after fix: all three calls pass extra_ro=[sys.base_prefix, sys.prefix].
"""
import sys
import unittest.mock as mock
from pathlib import Path
import pytest

from harness.orchestrator import _auto_commit_accepted


def _make_task():
    return {
        "verification_command": "pytest tests/test_dummy.py",
        # one declared mutant -> engages the Phase-B mutation gate so the
        # mutant-apply and mutant-rerun subprocesses both fire.
        "mutations": [{"apply": "true"}],
        # harness_self_fix matches the real SEC-2 route + the proven H2A harness;
        # it drives the verify + both mutant-gate jailed subprocesses (all three
        # build_jail_argv calls fire).
        "meta_task_type": "harness_self_fix",
    }


def test_sec2_jail_extra_ro_prefix_in_all_subprocesses(tmp_path):
    """RED on HEAD, GREEN after fix: all three jailed subprocesses pass sys.prefix in extra_ro."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (tmp_path / "JanusMaskJR_staging").mkdir()

    task = _make_task()
    task_id = "sec2_jail_extra_ro"

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

    cfg = {"agent_sandbox": {"bwrap": True}, "synthesis": {}}

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
        _auto_commit_accepted(state_dir, task, task_id)

    # We expect exactly three calls to build_jail_argv:
    # 1. Verify run
    # 2. Mutant apply run
    # 3. Mutant rerun
    assert len(build_jail_calls) >= 3, f"Expected at least 3 build_jail_argv calls, got {len(build_jail_calls)}"

    # Check each call's extra_ro parameter
    for i, kw in enumerate(build_jail_calls[:3]):
        extra_ro = kw.get("extra_ro", ())
        extra_ro_list = list(extra_ro)
        
        # Non-vacuity assertions
        assert sys.base_prefix in extra_ro_list, (
            f"Call #{i}: sys.base_prefix ({sys.base_prefix!r}) must be present in extra_ro: {extra_ro_list}"
        )
        
        # Load-bearing assertion
        assert sys.prefix in extra_ro_list, (
            f"Call #{i}: sys.prefix ({sys.prefix!r}) is missing from extra_ro: {extra_ro_list}"
        )
        
        # Harmonize check
        assert extra_ro_list == [sys.base_prefix, sys.prefix], (
            f"Call #{i}: extra_ro list must be exactly [sys.base_prefix, sys.prefix], got: {extra_ro_list}"
        )
