"""H2A oracle: Route the verify + mutant-gate subprocesses inside
``_auto_commit_accepted`` (harness/orchestrator.py) through the bubblewrap jail
(``harness.agent_jail.build_jail_argv``) when ``agent_sandbox.bwrap`` is enabled.

Final repo path: tests/adversarial/test_h2a_jail_verify.py

RED on HEAD: the three subprocess runs (verify ~1704, mutant apply ~1803, mutant
rerun ~1808) are dispatched as ``shell=True`` STRING commands ``set -o pipefail; ...``
and never touch the jail -> ``test_jail_wrapping`` asserts each recorded command is a
bwrap *argv list* and FAILS (the recorded commands are strings).

GREEN after fix: when sandbox is enabled the same three commands are wrapped via
``agent_jail.build_jail_argv`` -> recorded as a list whose argv[0] is the bwrap
binary and that contains ``--ro-bind`` (the load-bearing repo barrier). The fix
must NOT add a module-level import or a new top-level symbol (lazy in-body import
of ``agent_jail`` only -- ``load_config`` is already module-level).

NON-vacuity / no silent-skip without bwrap: the test mocks ``shutil.which`` ->
``/usr/bin/bwrap`` so ``build_jail_argv`` constructs a real argv WITHOUT bwrap being
installed on the host; it then inspects the argv STRUCTURALLY (argv[0] == the mocked
bwrap path, ``--ro-bind`` present). No ``pytest.skip``; the wrapping/fallback
behaviour is asserted directly.

Control-flow / mock-target notes (these are load-bearing -- the body re-imports
several names lazily, so patching ``harness.orchestrator.X`` is NOT always correct):
  * ``_auto_commit_accepted`` does ``from harness import git_integration`` and
    ``from harness._journal import write_jsonl_row`` INSIDE its body, so those names
    must be patched at their SOURCE modules (``harness.git_integration.*``,
    ``harness._journal.write_jsonl_row``) -- patching the orchestrator attribute is
    silently defeated by the in-body re-import.
  * ``_resolve_files_touched`` / ``_resolve_verification_command`` are re-imported
    ``from harness.orchestrator import ...`` -> patching ``harness.orchestrator.X``
    DOES take effect (same module).
  * ``subprocess`` is re-imported ``import subprocess`` but ``subprocess.run`` is an
    attribute on the shared real module, so ``harness.orchestrator.subprocess.run``
    patches the call sites correctly.
  * ``load_config``, ``_apply_approval_granted``, ``_rollback_rejected_commit``,
    ``_mark_processed`` are module-level globals -> patch on ``harness.orchestrator``.
The mutant gate runs the mutant-apply + mutant-rerun subprocesses; with a mocked
returncode of 0 the gate then rejects the staging commit as vacuous and returns
False. That rejection is irrelevant to this oracle -- we only assert the THREE
subprocess argvs that were dispatched on the way (verify + 2 mutant runs).
"""
import os
import unittest.mock as mock

import pytest

from harness.orchestrator import _auto_commit_accepted


_BWRAP = "/usr/bin/bwrap"


def _make_task():
    return {
        "verification_command": "pytest tests/test_dummy.py",
        # one declared mutant -> engages the Phase-B mutation gate so the
        # mutant-apply (~1803) and mutant-rerun (~1808) subprocesses both fire.
        "mutations": [{"apply": "true"}],
        "meta_task_type": "harness_self_fix",
    }


def _run_auto_commit(tmp_path, *, bwrap_enabled):
    """Drive _auto_commit_accepted to (and through) the verify + mutant subprocesses.

    Returns the list of non-git subprocess argvs that were dispatched, in order
    (verify, mutant-apply, mutant-rerun).
    """
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    # mutant work_dir / state sessions makedir targets must be real dirs:
    (tmp_path / "JanusMaskJR_staging").mkdir()

    task = _make_task()
    task_id = "h2a_probe_jail" if bwrap_enabled else "h2a_probe_fallback"

    run_calls = []

    def mock_run(cmd, *args, **kwargs):
        run_calls.append(cmd)
        proc = mock.MagicMock()
        proc.returncode = 0
        if isinstance(cmd, list) and cmd[:2] == ["git", "rev-parse"]:
            # worktree_root resolves to tmp_path; staging sibling is
            # tmp_path/JanusMaskJR_staging (created above).
            proc.stdout = str(tmp_path / "JanusMaskJR")
            proc.stderr = ""
        else:
            proc.stdout = ""
            proc.stderr = ""
        return proc

    git_stub = mock.MagicMock()
    git_stub.commit_accepted_output.return_value = {"committed": True, "sha": "deadbeef"}

    cfg = {"agent_sandbox": {"bwrap": bool(bwrap_enabled)}, "synthesis": {}}

    with mock.patch("harness.orchestrator.subprocess.run", side_effect=mock_run), \
         mock.patch("harness.orchestrator._resolve_files_touched", return_value=["dummy.py"]), \
         mock.patch("harness.orchestrator._resolve_verification_command", return_value="pytest tests/test_dummy.py"), \
         mock.patch("harness.orchestrator._apply_approval_granted", return_value=True), \
         mock.patch("harness.orchestrator._rollback_rejected_commit"), \
         mock.patch("harness.orchestrator._mark_processed"), \
         mock.patch("harness.orchestrator.load_config", return_value=cfg), \
         mock.patch("harness.git_integration", git_stub), \
         mock.patch("harness._journal.write_jsonl_row"), \
         mock.patch("shutil.which", return_value=_BWRAP), \
         mock.patch("shutil.copytree"), \
         mock.patch("shutil.rmtree"), \
         mock.patch("os.symlink"):
        # JanusMaskJR worktree root (rev-parse stdout) must exist so the .venv
        # symlink check + path resolves behave; staging sibling already created.
        (tmp_path / "JanusMaskJR").mkdir(exist_ok=True)
        _auto_commit_accepted(state_dir, task, task_id)

    non_git = [c for c in run_calls if not (isinstance(c, list) and c[:1] == ["git"])]
    return non_git


def test_h2a_verify_and_mutant_subprocesses_are_jailed_when_sandbox_enabled(tmp_path):
    """RED on HEAD, GREEN after fix: all three subprocess argvs are bwrap-wrapped."""
    non_git = _run_auto_commit(tmp_path, bwrap_enabled=True)

    assert len(non_git) >= 3, (
        f"expected verify + mutant-apply + mutant-rerun subprocess runs, got: {non_git!r}"
    )
    for i, cmd in enumerate(non_git[:3]):
        assert isinstance(cmd, list), (
            f"subprocess #{i} must be a bwrap argv LIST when sandbox is enabled, "
            f"got {type(cmd).__name__}: {cmd!r}"
        )
        assert cmd and cmd[0] == _BWRAP, (
            f"subprocess #{i} must begin with the bwrap binary, got argv[0]={cmd[0]!r}"
        )
        assert "--ro-bind" in cmd, (
            f"subprocess #{i} must ro-bind the repo (load-bearing barrier), got: {cmd!r}"
        )
        # the original bash command must still be the tail payload (contract preserved)
        assert "/bin/bash" in cmd, f"subprocess #{i} lost the /bin/bash payload: {cmd!r}"
        joined = " ".join(str(x) for x in cmd)
        assert "set -o pipefail;" in joined, (
            f"subprocess #{i} lost the pipefail wrapper: {cmd!r}"
        )


def test_h2a_subprocesses_run_unjailed_when_sandbox_disabled(tmp_path):
    """Regression guard: sandbox off -> original shell=True string commands, no bwrap."""
    non_git = _run_auto_commit(tmp_path, bwrap_enabled=False)

    assert len(non_git) >= 3, (
        f"expected verify + mutant-apply + mutant-rerun subprocess runs, got: {non_git!r}"
    )
    for i, cmd in enumerate(non_git[:3]):
        assert isinstance(cmd, str), (
            f"subprocess #{i} must stay a shell string when sandbox is disabled, "
            f"got {type(cmd).__name__}: {cmd!r}"
        )
        assert "set -o pipefail;" in cmd, (
            f"subprocess #{i} lost the pipefail contract: {cmd!r}"
        )
        assert "bwrap" not in cmd, f"subprocess #{i} must NOT be jailed: {cmd!r}"
