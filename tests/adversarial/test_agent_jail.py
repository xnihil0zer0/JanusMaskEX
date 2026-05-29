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
    # CONTAIN C-HARDEN M-1: state/ is READ-ONLY; only state/sessions/ is writable.
    sessions = state / "sessions"
    assert (str(state), str(state)) in ro, "state root must be ro-bind (C-HARDEN M-1)"
    assert (str(state), str(state)) not in rw, "state root must NOT be rw (M-1)"
    assert (str(sessions), str(sessions)) in rw, "state/sessions must be rw (ledger + submission)"
    # work_dir is writable.
    assert (str(work), str(work)) in rw, "work_dir must be rw-bind"
    # No namespace unsharing: --unshare-all/--unshare-pid both break agy's OAuth
    # (cred read / token refresh). The mount-ns binds alone enforce repo-RO. chdir work_dir.
    assert "--unshare-all" not in argv, "must not --unshare-all (breaks agy OAuth cred read)"
    assert "--unshare-pid" not in argv, "must not --unshare-pid (breaks agy OAuth token refresh)"
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


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap not installed")
def test_real_bwrap_M1_state_control_readonly_sessions_writable(tmp_path):
    """C-HARDEN M-1: under the jail, state/control/** (full_stop, allowlist,
    decisions self-approval) is READ-ONLY, but state/sessions/ (the hook ledger +
    canonical submission) is writable -- the only legitimate state write surface."""
    repo = tmp_path / "repo"
    state = repo / "state"
    control = state / "control" / "autowork"
    sessions = state / "sessions"
    work = tmp_path / "work"
    for d in (repo, control, sessions, work):
        d.mkdir(parents=True, exist_ok=True)
    (control / "full_stop").write_text("halted\n")

    # (i) overwrite state/control/.../full_stop (un-halt) -> DENIED
    argv = aj.build_jail_argv(
        ["/bin/sh", "-c", f"echo '' > {control}/full_stop"],
        repo_root=repo, work_dir=work, state_dir=state, home=tmp_path / "home",
    )
    r = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    assert r.returncode != 0, "un-halting full_stop must be denied (M-1)"
    assert (control / "full_stop").read_text() == "halted\n", "full_stop untouched"

    # (ii) append the FORBIDDEN EX_fix to auto_promote.allowlist -> DENIED
    argv2 = aj.build_jail_argv(
        ["/bin/sh", "-c", f"echo EX_fix >> {control}/auto_promote.allowlist"],
        repo_root=repo, work_dir=work, state_dir=state, home=tmp_path / "home",
    )
    r2 = subprocess.run(argv2, capture_output=True, text=True, timeout=30)
    assert r2.returncode != 0, "appending auto_promote.allowlist must be denied (M-1)"
    assert not (control / "auto_promote.allowlist").exists()

    # (iii) write the hook ledger under state/sessions/ -> ALLOWED
    argv3 = aj.build_jail_argv(
        ["/bin/sh", "-c", f"echo row > {sessions}/claude_x.ledger.jsonl"],
        repo_root=repo, work_dir=work, state_dir=state, home=tmp_path / "home",
    )
    r3 = subprocess.run(argv3, capture_output=True, text=True, timeout=30)
    assert r3.returncode == 0, f"write to state/sessions must succeed: {r3.stderr}"
    assert (sessions / "claude_x.ledger.jsonl").read_text().strip() == "row"


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap not installed")
def test_real_bwrap_M2_claude_memory_readonly_rest_writable(tmp_path):
    """C-HARDEN M-2: under the jail, ~/.claude/projects/*/memory is READ-ONLY (an
    agent cannot poison the session-memory that steers future Claude runs), while
    the rest of ~/.claude stays writable (claude-code session/project state)."""
    repo = tmp_path / "repo"
    state = repo / "state"
    home = tmp_path / "home"
    proj = home / ".claude" / "projects" / "proj1"
    mem = proj / "memory"
    work = tmp_path / "work"
    for d in (repo, state, mem, work):
        d.mkdir(parents=True, exist_ok=True)
    (mem / "MEMORY.md").write_text("trusted\n")

    # (i) poison ~/.claude/.../memory/MEMORY.md -> DENIED
    argv = aj.build_jail_argv(
        ["/bin/sh", "-c", f"echo poison > {mem}/MEMORY.md"],
        repo_root=repo, work_dir=work, state_dir=state, home=home,
    )
    r = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    assert r.returncode != 0, "write to ~/.claude/.../memory must be denied (M-2)"
    assert (mem / "MEMORY.md").read_text() == "trusted\n", "memory untouched"

    # (ii) write a sibling under the SAME project dir (non-memory) -> ALLOWED
    argv2 = aj.build_jail_argv(
        ["/bin/sh", "-c", f"echo ok > {proj}/session.json"],
        repo_root=repo, work_dir=work, state_dir=state, home=home,
    )
    r2 = subprocess.run(argv2, capture_output=True, text=True, timeout=30)
    assert r2.returncode == 0, f"write to ~/.claude (non-memory) must succeed: {r2.stderr}"
    assert (proj / "session.json").read_text().strip() == "ok"


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap not installed")
def test_real_bwrap_M2_unbound_home_subdir_denied(tmp_path):
    """C-HARDEN M-2: a HOME subdir that is NOT one of {.nvm,.gemini,.claude} is
    not bound at all -- e.g. the <repo>_agentwork residue or ~/.bashrc. A write to
    an unbound home path must fail (no mount exists)."""
    repo = tmp_path / "repo"
    state = repo / "state"
    home = tmp_path / "home"
    for d in (repo, state, home, tmp_path / "work"):
        d.mkdir(parents=True, exist_ok=True)
    work = tmp_path / "work"
    (home / ".bashrc").write_text("export X=1\n")
    argv = aj.build_jail_argv(
        ["/bin/sh", "-c", f"echo evil >> {home}/.bashrc"],
        repo_root=repo, work_dir=work, state_dir=state, home=home,
    )
    r = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    assert r.returncode != 0, "write to an unbound HOME path must fail (M-2)"
    assert (home / ".bashrc").read_text() == "export X=1\n"
