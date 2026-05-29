"""CONTAIN C2 — bwrap jail wraps agent spawns with the repo read-only.

Asserts the argv shape (repo ro-bind, work_dir + state rw-bind, cmd after --),
the config gate, fail-closed behaviour when bwrap is absent, and -- when a real
bwrap is present -- that a write to a ro-bound path is actually denied by the
kernel.
"""
from __future__ import annotations

import shutil
import subprocess

import pytest

import harness.agent_jail as aj


def _pairs(argv, flag):
    """All (src, dst) pairs following occurrences of ``flag`` in argv."""
    out = []
    for i, tok in enumerate(argv):
        if tok == flag and i + 2 < len(argv):
            out.append((argv[i + 1], argv[i + 2]))
    return out


def test_sandbox_enabled_gate():
    assert aj.sandbox_enabled({"agent_sandbox": {"bwrap": True}}) is True
    assert aj.sandbox_enabled({"agent_sandbox": {"bwrap": False}}) is False
    assert aj.sandbox_enabled({}) is False
    assert aj.sandbox_enabled(None) is False


def test_argv_repo_readonly_workdir_writable(tmp_path, monkeypatch):
    monkeypatch.setattr(aj.shutil, "which", lambda _x: "/usr/bin/bwrap")
    repo = tmp_path / "repo"
    state = repo / "state"
    work = tmp_path / "wr" / "claude" / "sess"
    home = tmp_path / "home"
    for d in (repo, state, work, home):
        d.mkdir(parents=True, exist_ok=True)

    argv = aj.build_jail_argv(
        ["/agent/bin", "-p", "do-it"],
        repo_root=repo, work_dir=work, state_dir=state, home=home,
    )

    assert argv[0] == "/usr/bin/bwrap"
    # Repo is read-only, NOT read-write.
    ro = _pairs(argv, "--ro-bind")
    rw = _pairs(argv, "--bind")
    assert (str(repo), str(repo)) in ro, "repo must be ro-bind"
    assert (str(repo), str(repo)) not in rw, "repo must NOT be writable"
    # state + work_dir are writable.
    assert (str(state), str(state)) in rw, "state must be rw-bind"
    assert (str(work), str(work)) in rw, "work_dir must be rw-bind"
    # Network shared (agents call model APIs); chdir into work_dir.
    assert "--share-net" in argv
    assert argv[argv.index("--chdir") + 1] == str(work)
    # The agent command is appended verbatim after the bwrap '--' terminator.
    dd = len(argv) - 1 - argv[::-1].index("--")
    assert argv[dd + 1:] == ["/agent/bin", "-p", "do-it"]


def test_fail_closed_when_bwrap_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(aj.shutil, "which", lambda _x: None)
    with pytest.raises(FileNotFoundError):
        aj.build_jail_argv(["x"], repo_root=tmp_path, work_dir=tmp_path,
                           state_dir=tmp_path)


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap not installed")
def test_real_bwrap_denies_write_to_ro_repo(tmp_path):
    """A tiny real bwrap run: a write to the ro-bound repo must fail; a write to
    the rw-bound work_dir must succeed."""
    repo = tmp_path / "repo"
    state = repo / "state"
    work = tmp_path / "work"
    for d in (repo, state, work):
        d.mkdir(parents=True, exist_ok=True)
    (repo / "guarded.py").write_text("original\n")

    # Attempt to overwrite a ro-bound repo file -> must be denied.
    argv = aj.build_jail_argv(
        ["/bin/sh", "-c", f"echo tampered > {repo}/guarded.py"],
        repo_root=repo, work_dir=work, state_dir=state, home=tmp_path,
    )
    r = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    assert r.returncode != 0, "write to ro-bound repo must fail"
    assert (repo / "guarded.py").read_text() == "original\n", "repo file untouched"

    # A write to the rw-bound work_dir must succeed.
    argv_ok = aj.build_jail_argv(
        ["/bin/sh", "-c", f"echo ok > {work}/out.txt"],
        repo_root=repo, work_dir=work, state_dir=state, home=tmp_path,
    )
    r2 = subprocess.run(argv_ok, capture_output=True, text=True, timeout=30)
    assert r2.returncode == 0, f"write to work_dir must succeed: {r2.stderr}"
    assert (work / "out.txt").read_text().strip() == "ok"
