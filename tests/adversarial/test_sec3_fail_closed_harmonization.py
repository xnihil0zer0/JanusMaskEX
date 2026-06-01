"""SEC-3 oracle: fail-CLOSED harmonization across the four jailed call sites.

Final repo path: tests/adversarial/test_sec3_fail_closed_harmonization.py
(confirmed NO collision at HEAD fb73017.)

DEFECT (plan REV15 SEC-3): when ``agent_sandbox.bwrap`` is ENABLED but the
``bwrap`` binary is ABSENT on PATH, the four jailed call sites behave
INCONSISTENTLY -- two fail-OPEN (run the untrusted candidate UNJAILED), two
fail-CRASH (uncaught ``FileNotFoundError`` from ``build_jail_argv`` kills the
worker):

  * smoke_import          harness/sandbox_smoke.py        fail-OPEN  (FileNotFoundError -> unjailed sys.executable fallback, :134-137)
  * _exec_module          harness/narrow_fuzz/validation   fail-OPEN  (gate keys on bwrap_available() not sandbox_enabled(); :255 else-branch spawns unjailed)
  * _auto_commit_accepted harness/orchestrator.py          fail-CRASH (verify-run try/except catches TimeoutExpired only; :1788-1804)
  * run_embedded_tests    harness/embedded_test_runner.py  fail-CRASH (build_jail_argv built OUTSIDE the TimeoutExpired-only try; :154/:192)

SEC-3 HARMONIZES all four to fail-CLOSED when sandbox ENABLED + bwrap ABSENT:
reject the run cleanly -- NEVER spawn unjailed, NEVER crash the worker. When
sandbox is DISABLED, behaviour is unchanged (unjailed is fine).

One RED case + a sandbox-DISABLED control per site. Case -> sub-task map:
  test_sec3_smoke_*    -> PHASE_SEC3_SMOKE     (harness/sandbox_smoke.py)
  test_sec3_fuzz_*     -> PHASE_SEC3_FUZZ      (harness/narrow_fuzz/validation.py)
  test_sec3_orch_*     -> PHASE_SEC3_ORCH      (harness/orchestrator.py)
  test_sec3_embedded_* -> PHASE_SEC3_EMBEDDED  (harness/embedded_test_runner.py)

NON-VACUITY: bwrap IS installed on this host (/usr/bin/bwrap), so "bwrap absent"
is SIMULATED by patching ``shutil.which`` -> None. Every fail-closed RED case is
paired with a sandbox-DISABLED control that drives the same code unjailed and
passes on HEAD, so no case can pass vacuously.

MOCK-TARGET notes (load-bearing -- these modules import lazily IN-BODY):
  * ``subprocess`` is imported lazily inside ``_exec_module`` and inside
    ``smoke_import``/``run_embedded_tests`` it is module-level. We patch
    ``subprocess.Popen`` / ``subprocess.run`` GLOBALLY where the binding is
    lazy, and the module attribute where it is module-level.
  * The sandbox config is read via ``from harness.orchestrator import
    load_config`` lazily in-body at every site; inject by patching
    ``harness.orchestrator.load_config`` -> a 0-arg-or-any lambda.
  * ``build_jail_argv`` calls ``shutil.which('bwrap')``; patch ``shutil.which``
    -> None to simulate bwrap-absent without uninstalling it on the host.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest.mock as mock
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Site 1: smoke_import (harness/sandbox_smoke.py)  -> PHASE_SEC3_SMOKE
# ---------------------------------------------------------------------------
def test_sec3_smoke_fail_closed_sandbox_enabled_bwrap_absent(monkeypatch):
    """RED on HEAD: smoke_import catches FileNotFoundError and FALLS BACK to an
    unjailed ``[sys.executable, '-S', '-c', 'import <mod>']`` run (fail-OPEN),
    so it returns None (import "succeeded" unjailed). SEC-3 must fail closed:
    NOT run unjailed, and return a clear non-None rejection string."""
    from harness.sandbox_smoke import smoke_import

    cfg = {"agent_sandbox": {"bwrap": True}}
    run_calls = []

    def mock_run(cmd, *a, **k):
        run_calls.append(cmd)
        proc = mock.MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        return proc

    monkeypatch.setattr("harness.orchestrator.load_config", lambda *a, **k: cfg)
    monkeypatch.setattr(shutil, "which", lambda _c: None)
    monkeypatch.setattr("harness.sandbox_smoke.subprocess.run", mock_run)

    res = smoke_import("test_sec3_smoke_closed", "x = 1")

    # Fail-closed contract: a clear rejection string (str|None contract), and
    # NO unjailed candidate subprocess dispatched.
    assert res is not None, (
        "FAIL-OPEN: smoke_import returned None (treated the unjailed fallback as "
        "success) while sandbox enabled + bwrap absent; SEC-3 requires a clean "
        "rejection string."
    )
    assert not any(str(c[0]) == sys.executable for c in run_calls), (
        f"FAIL-OPEN: smoke_import dispatched an unjailed sys.executable run: {run_calls!r}"
    )


def test_sec3_smoke_control_sandbox_disabled(monkeypatch):
    """Non-vacuity control: sandbox DISABLED -> unjailed sys.executable run, returns None."""
    from harness.sandbox_smoke import smoke_import

    cfg = {"agent_sandbox": {"bwrap": False}}
    run_calls = []

    def mock_run(cmd, *a, **k):
        run_calls.append(cmd)
        proc = mock.MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        return proc

    monkeypatch.setattr("harness.orchestrator.load_config", lambda *a, **k: cfg)
    monkeypatch.setattr(shutil, "which", lambda _c: None)
    monkeypatch.setattr("harness.sandbox_smoke.subprocess.run", mock_run)

    res = smoke_import("test_sec3_smoke_control", "x = 1")
    assert res is None, "control: sandbox-disabled smoke must pass (return None)"
    assert len(run_calls) == 1, f"control: expected one unjailed run, got {run_calls!r}"
    assert run_calls[0][0] == sys.executable, (
        f"control: expected unjailed sys.executable, got {run_calls[0]!r}"
    )


# ---------------------------------------------------------------------------
# Site 2: _exec_module / fuzz (harness/narrow_fuzz/validation.py) -> PHASE_SEC3_FUZZ
#
# HEAD: the gate at ~:255 keys on ``bwrap_available()``; with sandbox ENABLED
# but bwrap ABSENT it falls to ``else: argv = ['python3','driver.py']`` and
# spawns the candidate driver UNJAILED. SEC-3: gate on ``sandbox_enabled(cfg)``
# (lazy in-body import) and fail closed -- NO unjailed ['python3','driver.py']
# spawn. The natural harmonization is for _exec_module to return None (candidate
# is NOT fuzzed and crucially NOT run unjailed); fuzz then returns None too, so
# the load-bearing assertion is "no unjailed driver dispatched", NOT a string.
# ---------------------------------------------------------------------------
_FUZZ_SRC = "def validate_x(x: int):\n    return True\n"


def _drive_fuzz(monkeypatch, *, bwrap_enabled, which_return):
    from harness.narrow_fuzz import validation

    popen_calls = []

    class _FakeProc:
        def __init__(self, argv):
            self.argv = argv
            self.stdin = mock.MagicMock()
            self.stdout = mock.MagicMock()
            # 'ready' so _exec_module builds a namespace (control path); the
            # fuzzers are stubbed to None so no real candidate work happens.
            self.stdout.readline.return_value = (
                '{"status": "ready", "functions": {"validate_x": {}}}'
            )

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    def fake_popen(argv, *a, **k):
        popen_calls.append(argv)
        return _FakeProc(argv)

    cfg = {"agent_sandbox": {"bwrap": bool(bwrap_enabled)}}
    monkeypatch.setattr("harness.orchestrator.load_config", lambda *a, **k: cfg)
    monkeypatch.setattr(shutil, "which", lambda _c: which_return)
    # subprocess is imported lazily inside _exec_module -> patch globally.
    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr("harness.narrow_fuzz.validation._fuzz_one", lambda *a, **k: None)

    res = validation.fuzz("candmod", _FUZZ_SRC)
    return res, popen_calls


def test_sec3_fuzz_fail_closed_sandbox_enabled_bwrap_absent(monkeypatch):
    """RED on HEAD: the H-FUZZ gate keys on bwrap_available(), so sandbox ENABLED
    + bwrap ABSENT spawns the candidate driver UNJAILED (['python3','driver.py'])."""
    _res, popen_calls = _drive_fuzz(monkeypatch, bwrap_enabled=True, which_return=None)
    # Load-bearing: NO unjailed driver may be dispatched while sandbox enabled.
    assert not any(list(a[:2]) == ["python3", "driver.py"] for a in popen_calls), (
        "FAIL-OPEN: _exec_module spawned the candidate driver UNJAILED "
        f"(['python3','driver.py']) while sandbox enabled + bwrap absent: {popen_calls!r}"
    )


def test_sec3_fuzz_control_sandbox_disabled(monkeypatch):
    """Non-vacuity control: sandbox DISABLED -> unjailed ['python3','driver.py']."""
    # bwrap absent here too: sandbox-disabled means the candidate runs unjailed
    # regardless of bwrap presence on HEAD (HEAD gates on bwrap_available, so we
    # keep bwrap absent to get the unjailed branch) AND after the fix (gates on
    # sandbox_enabled -> disabled -> unjailed). GREEN both before and after.
    res, popen_calls = _drive_fuzz(monkeypatch, bwrap_enabled=False, which_return=None)
    assert res is None
    assert len(popen_calls) == 1, f"control: expected one driver spawn, got {popen_calls!r}"
    assert list(popen_calls[0][:2]) == ["python3", "driver.py"], (
        f"control: expected unjailed ['python3','driver.py'], got {popen_calls[0]!r}"
    )


# ---------------------------------------------------------------------------
# Site 3: _auto_commit_accepted verify-run (harness/orchestrator.py) -> PHASE_SEC3_ORCH
#
# The genuine fail-CRASH site is the VERIFY run (orchestrator.py ~:1788-1804):
# its try/except catches subprocess.TimeoutExpired ONLY, so sandbox ENABLED +
# bwrap ABSENT raises FileNotFoundError from build_jail_argv that is UNCAUGHT
# and crashes the worker. (The mutation-gate jailed calls below it are already
# wrapped in a broad ``except Exception`` that fails closed -- NOT the defect.)
# SEC-3 must catch the FileNotFoundError at the verify run and reject cleanly
# (roll back staging, return False), never crash.
#
# We drive the REAL orchestrator end-to-end with a git worktree so the verify
# branch executes. RED on HEAD = an UNCAUGHT FileNotFoundError escapes
# _auto_commit_accepted. GREEN after = returns False (clean rejection), parent
# HEAD unchanged.
# ---------------------------------------------------------------------------
def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "JanusMask Test")
    env.setdefault("GIT_AUTHOR_EMAIL", "test@janusmask.local")
    env.setdefault("GIT_COMMITTER_NAME", "JanusMask Test")
    env.setdefault("GIT_COMMITTER_EMAIL", "test@janusmask.local")
    return subprocess.run(["git", *args], cwd=str(cwd), env=env, check=True,
                          capture_output=True, text=True, timeout=60)


_TARGET_REL = "feature_mod.py"


def _make_parent(tmp_path: Path, *, module_src: str):
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    _git(worktree, "init", "-q", "-b", "main")
    _git(worktree, "config", "user.name", "JanusMask Test")
    _git(worktree, "config", "user.email", "test@janusmask.local")
    state_dir = worktree / "state"
    (state_dir / "output").mkdir(parents=True)
    (state_dir / "tasks" / "processed").mkdir(parents=True)
    (worktree / _TARGET_REL).write_text(module_src, encoding="utf-8")
    _git(worktree, "add", _TARGET_REL)
    _git(worktree, "commit", "-q", "-m", "initial")
    return state_dir, worktree


def _orch_task(task_id: str):
    return {
        "task_id": task_id,
        "meta_task_type": "harness_self_fix",
        "files_touched": [_TARGET_REL],
        "verification_command": "python -c 'print(1)'",
    }


def test_sec3_orch_verify_fail_closed_sandbox_enabled_bwrap_absent(tmp_path, monkeypatch):
    """RED on HEAD: the verify-run try/except catches TimeoutExpired ONLY, so a
    missing-bwrap-while-enabled raises FileNotFoundError UNCAUGHT and crashes the
    worker. SEC-3 must reject cleanly (return False), never let it escape."""
    from harness.orchestrator import _auto_commit_accepted

    state_dir, worktree = _make_parent(tmp_path, module_src="x = 1")
    head_before = _git(worktree, "rev-parse", "HEAD").stdout.strip()

    task_id = "PHASE_SEC3_ORCH_FC"
    (state_dir / "output" / f"{task_id}.py").write_text("x = 2", encoding="utf-8")

    cfg = {"agent_sandbox": {"bwrap": True}}
    monkeypatch.setattr("harness.orchestrator.load_config", lambda *a, **k: cfg)
    monkeypatch.setattr(shutil, "which", lambda _c: None)

    try:
        committed = _auto_commit_accepted(state_dir, _orch_task(task_id), task_id)
    except FileNotFoundError as exc:
        pytest.fail(
            "FAIL-CRASH (RED on HEAD): _auto_commit_accepted let FileNotFoundError "
            f"escape uncaught while sandbox enabled + bwrap absent: {exc}"
        )

    assert committed is False, "SEC-3: must reject cleanly (return False) when fail-closed"
    head_after = _git(worktree, "rev-parse", "HEAD").stdout.strip()
    assert head_after == head_before, "parent HEAD must be unchanged on fail-closed rejection"


def test_sec3_orch_control_sandbox_disabled(tmp_path, monkeypatch):
    """Non-vacuity control: sandbox DISABLED + bwrap absent -> unjailed verify runs,
    the trivial change is accepted (committed True)."""
    from harness.orchestrator import _auto_commit_accepted

    state_dir, worktree = _make_parent(tmp_path, module_src="x = 1")

    task_id = "PHASE_SEC3_ORCH_CTRL"
    (state_dir / "output" / f"{task_id}.py").write_text("x = 2", encoding="utf-8")

    cfg = {"agent_sandbox": {"bwrap": False}}
    monkeypatch.setattr("harness.orchestrator.load_config", lambda *a, **k: cfg)
    monkeypatch.setattr(shutil, "which", lambda _c: None)

    committed = _auto_commit_accepted(state_dir, _orch_task(task_id), task_id)
    assert committed is True, "control: unjailed verification should accept the change"


# ---------------------------------------------------------------------------
# Site 4: run_embedded_tests (harness/embedded_test_runner.py) -> PHASE_SEC3_EMBEDDED
#
# HEAD: build_jail_argv (collect_argv / run_argv, :154/:192) is built OUTSIDE
# the TimeoutExpired-only try, so sandbox ENABLED + bwrap ABSENT raises
# FileNotFoundError that propagates and CRASHES. SEC-3: catch it and return a
# clean rejection STRING (str|None contract), never crash, never run unjailed.
# ---------------------------------------------------------------------------
def test_sec3_embedded_fail_closed_sandbox_enabled_bwrap_absent(monkeypatch):
    """RED on HEAD: run_embedded_tests builds build_jail_argv outside the
    TimeoutExpired-only try, so missing-bwrap-while-enabled crashes with an
    uncaught FileNotFoundError. SEC-3 must return a clean rejection string."""
    from harness.embedded_test_runner import run_embedded_tests

    cfg = {"agent_sandbox": {"bwrap": True}}
    run_calls = []

    def mock_run(cmd, *a, **k):
        run_calls.append(cmd)
        proc = mock.MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        return proc

    monkeypatch.setattr("harness.orchestrator.load_config", lambda *a, **k: cfg)
    monkeypatch.setattr(shutil, "which", lambda _c: None)
    monkeypatch.setattr("harness.embedded_test_runner.subprocess.run", mock_run)

    src = "def test_dummy():\n    assert True\n"
    try:
        res = run_embedded_tests("dummy_module_sec3", src)
    except FileNotFoundError as exc:
        pytest.fail(
            "FAIL-CRASH (RED on HEAD): run_embedded_tests let FileNotFoundError "
            f"escape uncaught while sandbox enabled + bwrap absent: {exc}"
        )

    assert isinstance(res, str) and res, (
        f"SEC-3: expected a non-empty clean rejection string, got {res!r}"
    )
    assert not any(str(c[0]) == sys.executable or str(c[0]) == "python3" for c in run_calls), (
        f"FAIL-OPEN: embedded ran unjailed while sandbox enabled + bwrap absent: {run_calls!r}"
    )


def test_sec3_embedded_control_sandbox_disabled(monkeypatch):
    """Non-vacuity control: sandbox DISABLED -> unjailed sys.executable pytest runs."""
    from harness.embedded_test_runner import run_embedded_tests

    cfg = {"agent_sandbox": {"bwrap": False}}
    run_calls = []

    def mock_run(cmd, *a, **k):
        run_calls.append(cmd)
        proc = mock.MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        return proc

    monkeypatch.setattr("harness.orchestrator.load_config", lambda *a, **k: cfg)
    monkeypatch.setattr(shutil, "which", lambda _c: None)
    monkeypatch.setattr("harness.embedded_test_runner.subprocess.run", mock_run)

    src = "def test_dummy():\n    assert True\n"
    res = run_embedded_tests("dummy_module_sec3_ctrl", src)
    assert res is None, "control: sandbox-disabled embedded run should pass (None)"
    assert len(run_calls) == 2, f"control: expected collect+run, got {run_calls!r}"
    for cmd in run_calls:
        assert cmd[0] == sys.executable, f"control: expected unjailed sys.executable, got {cmd!r}"
