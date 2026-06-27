"""SEC-1c-ORCHACC oracle: route the FOUR jailed verification subprocesses inside
``harness.orchestrator._auto_commit_accepted`` through the FILTERED D-Bus proxy
when sandboxing is enabled.

Final repo path: tests/adversarial/test_sec1c_orchacc_proxy_wrap.py

The four sandboxed ``subprocess.run(agent_jail.build_jail_argv(...), ...)`` spawns are:
  * the verify spawn (``vproc``),
  * the mutation-gate baseline-in-copy spawn (``_bproc``),
  * the mutation-gate mutant-apply spawn (``_ap``),
  * the mutation-gate mutant-rerun spawn (``_mproc``).

RED on HEAD: on HEAD none of these spawns enter ``proxied_session_bus`` and each
passes ``dbus_proxy_socket`` defaulted to ``None`` (the kwarg is not supplied) --
so the fake proxy CM is never entered AND every captured ``dbus_proxy_socket`` is
``None``. The assertions fail as REAL ``assert`` failures, not import/collection
errors.

GREEN after the wrap: each sandboxed spawn enters ``proxied_session_bus`` and
threads the yielded sentinel socket into ``build_jail_argv`` as
``dbus_proxy_socket``. The fail-open ``try/except`` keeps the unsandboxed path
unchanged (regression guard below).

Determinism: this oracle NEVER spawns a real ``xdg-dbus-proxy``, ``bwrap`` or git.
``harness.dbus_proxy.proxied_session_bus`` is replaced with a recording fake CM
yielding a sentinel socket; ``harness.agent_jail.build_jail_argv`` is replaced
with a recorder capturing the ``dbus_proxy_socket`` kwarg; ``subprocess.run`` in
the orchestrator module is mocked so no real child spawns; ``sandbox_enabled`` is
forced True via an injected config + a direct patch.

Mock-target / control-flow notes (load-bearing -- the body re-imports several
names lazily, so patching ``harness.orchestrator.X`` is NOT always correct;
mirrors tests/adversarial/test_h2a_jail_verify.py):
  * ``_auto_commit_accepted`` does ``from harness import git_integration`` and
    ``from harness._journal import write_jsonl_row`` INSIDE its body, so those are
    patched at their SOURCE modules.
  * ``proxied_session_bus`` and ``build_jail_argv`` are imported/called via the
    ``harness.dbus_proxy`` / ``harness.agent_jail`` modules, so patching the
    attribute on those modules covers the in-body lazy import.
  * ``subprocess`` is re-imported ``import subprocess`` but ``subprocess.run`` is
    an attribute on the shared real module, so patching
    ``harness.orchestrator.subprocess.run`` patches the call sites correctly.
  * One declared mutant engages the Phase-B mutation gate so the baseline +
    mutant-apply + mutant-rerun spawns all fire (alongside the verify spawn);
    the gate then rejects the staging commit as vacuous and returns False -- that
    rejection is irrelevant here, we only assert the four spawns' proxy sockets.
"""
from __future__ import annotations

import os
import shutil
import subprocess  # noqa: F401  (kept for parity / explicitness; not directly used)
import unittest.mock as mock
from pathlib import Path

import pytest

import harness.agent_jail as agent_jail
import harness.dbus_proxy as dbus_proxy
import harness.git_integration as git_integration
import harness._journal as journal
from harness.orchestrator import _auto_commit_accepted


_SENTINEL_SOCK = "/tmp/sec1c-orchacc-sentinel/proxy.sock"


class _FakeProxyCM:
    """Fake D-Bus proxy context manager: records enter/exit, yields a sentinel socket."""

    def __init__(self, recorder):
        self._recorder = recorder

    def __enter__(self):
        self._recorder["entered"] += 1
        return _SENTINEL_SOCK

    def __exit__(self, *exc):
        self._recorder["exited"] += 1
        return False


def _drive_auto_commit(tmp_path, monkeypatch, *, sandbox_enabled):
    """Drive ``_auto_commit_accepted`` to (and through) the four jailed spawns.

    Returns ``(rec, captured, run_calls)`` where ``rec`` counts proxy CM
    enter/exit, ``captured`` is the ordered list of ``dbus_proxy_socket`` kwargs
    passed to the (recorded) ``build_jail_argv``, and ``run_calls`` is every
    argv handed to the mocked ``subprocess.run``.
    """
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    # mutant work_dir / staging sibling + worktree root must be real dirs:
    (tmp_path / "JanusMaskEX_staging").mkdir()
    (tmp_path / "JanusMaskEX").mkdir(exist_ok=True)

    task = {
        "verification_command": "pytest tests/test_dummy.py",
        # one declared mutant -> engages the Phase-B mutation gate so the
        # baseline (_bproc), mutant-apply (_ap) and mutant-rerun (_mproc)
        # spawns all fire alongside the verify spawn (vproc).
        "mutations": [{"apply": "true"}],
        "meta_task_type": "harness_self_fix",
    }
    task_id = "sec1c_orchacc_probe"

    rec = {"entered": 0, "exited": 0}

    def _proxy_factory(*args, **kwargs):
        return _FakeProxyCM(rec)

    monkeypatch.setattr(dbus_proxy, "proxied_session_bus", _proxy_factory)

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
    monkeypatch.setattr(git_integration, "commit_accepted_output", git_stub.commit_accepted_output)
    monkeypatch.setattr(git_integration, "create_staging_worktree", mock.MagicMock())
    monkeypatch.setattr(git_integration, "remove_staging_worktree", mock.MagicMock())
    monkeypatch.setattr(git_integration, "merge_staging_to_parent", mock.MagicMock())
    monkeypatch.setattr(journal, "write_jsonl_row", mock.MagicMock())
    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/bwrap")
    monkeypatch.setattr(shutil, "copytree", mock.MagicMock())
    monkeypatch.setattr(shutil, "rmtree", mock.MagicMock())
    monkeypatch.setattr(os, "symlink", mock.MagicMock())

    _auto_commit_accepted(state_dir, task, task_id)
    return rec, captured, run_calls


def test_sec1c_orchacc_all_four_spawns_thread_proxy_socket(tmp_path, monkeypatch):
    """RED on HEAD, GREEN after wrap: all four sandboxed spawns route the proxy socket."""
    rec, captured, _ = _drive_auto_commit(tmp_path, monkeypatch, sandbox_enabled=True)

    # build_jail_argv must have been reached (otherwise the test never exercised
    # the spawn path -- guard against a vacuous pass).
    assert len(captured) >= 1, (
        "build_jail_argv was never called -- the function did not reach any "
        "sandboxed spawn; the oracle did not exercise the wrap path"
    )

    # PRIMARY RED signal: every sandboxed spawn must have received the proxy
    # sentinel socket. On HEAD dbus_proxy_socket defaults to None -> this fails.
    for i, sock in enumerate(captured):
        assert sock is not None, (
            f"sandboxed spawn #{i} passed dbus_proxy_socket=None -- it did not "
            f"route through the filtered D-Bus proxy (captured={captured!r})"
        )
        assert sock == _SENTINEL_SOCK, (
            f"sandboxed spawn #{i} passed dbus_proxy_socket={sock!r}, expected the "
            f"proxy sentinel {_SENTINEL_SOCK!r}"
        )

    # CORROBORATING signal: the proxy CM was entered once per spawn.
    assert rec["entered"] >= 1, "proxied_session_bus was never entered"
    assert rec["entered"] == len(captured), (
        f"proxy CM entered {rec['entered']} time(s) but {len(captured)} jailed "
        f"spawn(s) fired -- each spawn must wrap its own proxied_session_bus"
    )

    # All four verification spawns (verify + baseline + mutant-apply +
    # mutant-rerun) must fire when one mutant engages the mutation gate.
    assert len(captured) == 4, (
        f"expected all FOUR jailed spawns (verify, baseline, mutant-apply, "
        f"mutant-rerun) to thread the proxy, got {len(captured)}: {captured!r}"
    )


def test_sec1c_orchacc_unsandboxed_path_unchanged(tmp_path, monkeypatch):
    """Regression guard: sandbox OFF -> shell-string spawns, proxy never entered."""
    rec, captured, run_calls = _drive_auto_commit(tmp_path, monkeypatch, sandbox_enabled=False)

    # No jailed spawn => build_jail_argv never called => proxy never entered.
    assert captured == [], (
        f"build_jail_argv must not be called when sandbox is disabled, got {captured!r}"
    )
    assert rec["entered"] == 0, (
        "proxied_session_bus must NOT be entered on the unsandboxed path"
    )
    # The verification command still runs as a shell string (set -o pipefail; ...).
    shell_runs = [c for c in run_calls if isinstance(c, str) and "set -o pipefail;" in c]
    assert shell_runs, (
        f"expected at least one shell-string verification run when sandbox is "
        f"disabled, got run_calls={run_calls!r}"
    )
