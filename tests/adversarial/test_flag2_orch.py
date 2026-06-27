"""FLAG2_ORCH oracle (REV22 §3 + CR-6 step-0): fail-closed gate on the four
UNJAILED ``shell=True`` verify/baseline/mutant spawn sites inside
``harness/orchestrator.py::_auto_commit_accepted``.

Final repo path: tests/adversarial/test_flag2_orch.py

THREAT (FLAG#2 / CR-11): when ``agent_sandbox`` is disabled,
``_auto_commit_accepted`` falls back to ``subprocess.run(..., shell=True,
executable='/bin/bash', env=_vcmd_scrubbed_env())`` on the HOST at four sites
(orchestrator.py ~:1964 verify, ~:2103 baseline-in-copy, ~:2142 mutant-apply,
~:2171 mutant-rerun). For an EXTERNAL task this runs an attacker-controlled
``verification_command`` UNJAILED with full host creds + network and a host-env
copy. The fix adds, at the TOP of the function, ``working_dir =
task.get('working_dir')`` (CR-6 reader) and, on EACH of the four sandbox-OFF
branches BEFORE the shell=True fallback, a guard::

    if not _target_is_self(working_dir):
        raise RuntimeError("... refusing unjailed external verify spawn ...")

RED on HEAD: no guard exists -> the external + sandbox-OFF task reaches the
shell=True ``subprocess.run`` (does NOT raise) -> the
``test_flag2_external_unjailed_spawn_is_refused`` assertion (RuntimeError raised
AND no shell=True host run dispatched) FAILS.

GREEN after fix: the verify-site guard fires first, raises RuntimeError, and NO
shell=True ``subprocess.run`` is ever dispatched (no unjailed host run, no
host-env leak). The SELF path (working_dir absent -> ``_target_is_self(None)``
== True) is INERT -> sandbox-OFF self tasks still reach the shell=True fallback
exactly as before (regression guard).

Mock-target notes (mirror tests/adversarial/test_h2a_jail_verify.py -- the body
re-imports several names lazily):
  * ``_auto_commit_accepted`` does ``from harness import git_integration`` and
    ``from harness._journal import write_jsonl_row`` and
    ``from harness.paths import _target_is_self`` INSIDE its body -> the REAL
    ``harness.paths._target_is_self`` is used (we do NOT stub it; we feed real
    paths so the classification is exercised end-to-end).
  * ``_resolve_files_touched`` / ``_resolve_verification_command`` are
    re-imported from ``harness.orchestrator`` -> patch on ``harness.orchestrator``.
  * ``subprocess`` is ``import subprocess`` (shared module) -> patch
    ``harness.orchestrator.subprocess.run``.
  * ``load_config``, ``_apply_approval_granted``, ``_rollback_rejected_commit``,
    ``_mark_processed`` are module-level globals -> patch on ``harness.orchestrator``.
"""
import os
import unittest.mock as mock

import pytest

from harness.orchestrator import _auto_commit_accepted
from harness.paths import _target_is_self


def _make_task(working_dir):
    task = {
        "verification_command": "pytest tests/test_dummy.py",
        # one declared mutant -> engages the Phase-B mutation gate so the
        # baseline-in-copy / mutant-apply / mutant-rerun sandbox branches are
        # reachable too (though the verify-site guard aborts before them on the
        # external path).
        "mutations": [{"apply": "true"}],
        "meta_task_type": "harness_self_fix",
    }
    if working_dir is not None:
        task["working_dir"] = working_dir
    return task


def _drive_auto_commit(tmp_path, *, working_dir):
    """Drive _auto_commit_accepted with sandbox DISABLED toward the verify spawn.

    Returns (raised_exc_or_None, list_of_all_subprocess_run_calls). Each entry of
    the list is the (cmd, kwargs) tuple seen by the patched ``subprocess.run``.
    """
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (tmp_path / "JanusMaskEX_staging").mkdir()
    (tmp_path / "JanusMaskEX").mkdir(exist_ok=True)

    task = _make_task(working_dir)
    task_id = "flag2_probe"

    run_calls = []

    def mock_run(cmd, *args, **kwargs):
        run_calls.append((cmd, kwargs))
        proc = mock.MagicMock()
        proc.returncode = 0
        if isinstance(cmd, list) and cmd[:2] == ["git", "rev-parse"]:
            proc.stdout = str(tmp_path / "JanusMaskEX")
            proc.stderr = ""
        else:
            proc.stdout = ""
            proc.stderr = ""
        return proc

    git_stub = mock.MagicMock()
    git_stub.commit_accepted_output.return_value = {"committed": True, "sha": "deadbeef"}

    # sandbox DISABLED -> the shell=True fallback branch is selected at every site.
    cfg = {"agent_sandbox": {"bwrap": False}, "synthesis": {}}

    raised = None
    with mock.patch("harness.orchestrator.subprocess.run", side_effect=mock_run), \
         mock.patch("harness.orchestrator._resolve_files_touched", return_value=["dummy.py"]), \
         mock.patch("harness.orchestrator._resolve_verification_command", return_value="pytest tests/test_dummy.py"), \
         mock.patch("harness.orchestrator._apply_approval_granted", return_value=True), \
         mock.patch("harness.orchestrator._rollback_rejected_commit"), \
         mock.patch("harness.orchestrator._mark_processed"), \
         mock.patch("harness.orchestrator.load_config", return_value=cfg), \
         mock.patch("harness.git_integration", git_stub), \
         mock.patch("harness._journal.write_jsonl_row"), \
         mock.patch("shutil.copytree"), \
         mock.patch("shutil.rmtree"), \
         mock.patch("os.symlink"):
        try:
            _auto_commit_accepted(state_dir, task, task_id)
        except RuntimeError as exc:
            raised = exc

    return raised, run_calls


def _shell_true_calls(run_calls):
    """The subset of subprocess.run calls dispatched with shell=True (host runs)."""
    return [(cmd, kw) for (cmd, kw) in run_calls if kw.get("shell") is True]


def test_external_working_dir_classifies_as_not_self(tmp_path):
    """Sanity: an out-of-tree working_dir is classified external by the REAL
    predicate (so the gate is genuinely exercised, not vacuously self)."""
    external = tmp_path / "totally_outside_repo"
    external.mkdir()
    assert _target_is_self(str(external)) is False, (
        "fixture working_dir must classify as EXTERNAL for this oracle to be "
        "non-vacuous"
    )
    assert _target_is_self(None) is True


def test_flag2_external_unjailed_spawn_is_refused(tmp_path):
    """RED on HEAD, GREEN after fix.

    External target + sandbox DISABLED -> _auto_commit_accepted MUST raise
    RuntimeError (refusal) and MUST NOT dispatch any shell=True host run.
    On HEAD there is no guard: the function reaches the shell=True fallback and
    does NOT raise -> both assertions fail.
    """
    external = tmp_path / "external_target_repo"
    external.mkdir()
    # belt-and-suspenders: confirm the predicate sees this as external.
    assert _target_is_self(str(external)) is False

    raised, run_calls = _drive_auto_commit(tmp_path, working_dir=str(external))

    shell_calls = _shell_true_calls(run_calls)
    assert raised is not None, (
        "external target + sandbox-OFF MUST raise (fail-closed); on HEAD the "
        "missing guard lets it fall through to the unjailed shell=True host run. "
        f"shell=True calls observed: {shell_calls!r}"
    )
    assert "FLAG2_ORCH" in str(raised) or "refus" in str(raised).lower(), (
        f"refusal RuntimeError must be the FLAG2 gate, got: {raised!r}"
    )
    assert shell_calls == [], (
        "NO unjailed shell=True host run may be dispatched on the external "
        f"sandbox-OFF path (host-env leak via _vcmd_scrubbed_env). Got: {shell_calls!r}"
    )


def test_flag2_self_path_unchanged_runs_unjailed_shell(tmp_path):
    """Regression / inert-for-self guard.

    working_dir absent -> _target_is_self(None) == True -> the gate is a no-op.
    Sandbox DISABLED -> the verify run still goes out as a shell=True host run
    exactly as before the fix (no spurious refusal).
    """
    raised, run_calls = _drive_auto_commit(tmp_path, working_dir=None)

    assert raised is None, (
        f"self path (working_dir=None) must NOT be refused; got raise: {raised!r}"
    )
    shell_calls = _shell_true_calls(run_calls)
    assert shell_calls, (
        "self + sandbox-OFF must still reach the historical shell=True verify "
        f"fallback; observed subprocess.run calls: {run_calls!r}"
    )
    # the first shell=True call carries the pipefail-wrapped verification_command.
    first_cmd = shell_calls[0][0]
    assert isinstance(first_cmd, str) and "set -o pipefail;" in first_cmd, (
        f"self verify run lost the pipefail shell-string contract: {first_cmd!r}"
    )
