"""Security Hardening Oracle: Restrict credentials and network access on execute-path spawns.

Target path: tests/security/test_cred_exfil_execpath.py

RED on HEAD: TypeError is raised when calling build_jail_argv with bind_credentials=False.
GREEN after fix: build_jail_argv accepts bind_credentials=False, skips .gemini/.claude binds, and includes --unshare-net/--unshare-ipc.
"""
import os
import shutil
import pytest
import harness.agent_jail as aj


def _pairs(argv, flag):
    """All (src, dst) pairs following occurrences of ``flag`` in argv."""
    out = []
    for i, tok in enumerate(argv):
        if tok == flag and i + 2 < len(argv):
            out.append((argv[i + 1], argv[i + 2]))
    return out


def test_cred_exfil_restricted_on_execute_path(tmp_path, monkeypatch):
    # Hermetic setup: monkeypatch shutil.which so bwrap is "present"
    monkeypatch.setattr(aj.shutil, "which", lambda _x: "/usr/bin/bwrap")

    repo = tmp_path / "repo"
    state = repo / "state"
    work = tmp_path / "work"
    home = tmp_path / "home"
    for d in (repo, state, work, home):
        d.mkdir(parents=True, exist_ok=True)

    # Create fake home dirs .gemini, .claude, and .nvm
    (home / ".gemini").mkdir()
    (home / ".claude").mkdir()
    (home / ".nvm").mkdir()

    # On HEAD, build_jail_argv doesn't have the bind_credentials parameter.
    # Therefore, calling with bind_credentials=False will raise a TypeError.
    # We catch TypeError and raise AssertionError so it asserts cleanly.
    try:
        argv_exec = aj.build_jail_argv(
            ["/bin/true"],
            repo_root=repo,
            work_dir=work,
            state_dir=state,
            home=home,
            bind_credentials=False
        )
    except TypeError as e:
        raise AssertionError("TypeError raised (expected on HEAD): bind_credentials not supported: " + str(e))

    # Assertions for EXECUTE argv (bind_credentials=False):
    ro = _pairs(argv_exec, "--ro-bind")
    rw = _pairs(argv_exec, "--bind")

    gemini_bind = (str(home / ".gemini"), str(home / ".gemini"))
    claude_bind = (str(home / ".claude"), str(home / ".claude"))
    nvm_bind = (str(home / ".nvm"), str(home / ".nvm"))

    # * assert ("--bind", "<home>/.gemini") pair NOT present and ("--bind","<home>/.claude") NOT present
    assert gemini_bind not in rw, "EXECUTE path must NOT bind ~/.gemini read-write"
    assert claude_bind not in rw, "EXECUTE path must NOT bind ~/.claude read-write"
    assert gemini_bind not in ro, "EXECUTE path must NOT bind ~/.gemini read-only"
    assert claude_bind not in ro, "EXECUTE path must NOT bind ~/.claude read-only"

    # * assert "--unshare-net" in argv and "--unshare-ipc" in argv
    assert "--unshare-net" in argv_exec, "EXECUTE path must contain --unshare-net"
    assert "--unshare-ipc" in argv_exec, "EXECUTE path must contain --unshare-ipc"

    # * assert (".nvm" ro-bind STILL present)
    assert nvm_bind in ro, "EXECUTE path must STILL ro-bind ~/.nvm"
    assert nvm_bind not in rw, "EXECUTE path must NOT rw-bind ~/.nvm"


def test_cred_exfil_synthesis_path_default(tmp_path, monkeypatch):
    # Hermetic setup: monkeypatch shutil.which so bwrap is "present"
    monkeypatch.setattr(aj.shutil, "which", lambda _x: "/usr/bin/bwrap")

    repo = tmp_path / "repo"
    state = repo / "state"
    work = tmp_path / "work"
    home = tmp_path / "home"
    for d in (repo, state, work, home):
        d.mkdir(parents=True, exist_ok=True)

    # Create fake home dirs .gemini, .claude, and .nvm
    (home / ".gemini").mkdir()
    (home / ".claude").mkdir()
    (home / ".nvm").mkdir()

    # Build a SYNTHESIS argv with bind_credentials=True (default/explicit):
    for argv_synth in (
        aj.build_jail_argv(["/bin/true"], repo_root=repo, work_dir=work, state_dir=state, home=home),
        aj.build_jail_argv(["/bin/true"], repo_root=repo, work_dir=work, state_dir=state, home=home, bind_credentials=True)
    ):
        ro = _pairs(argv_synth, "--ro-bind")
        rw = _pairs(argv_synth, "--bind")

        gemini_bind = (str(home / ".gemini"), str(home / ".gemini"))
        claude_bind = (str(home / ".claude"), str(home / ".claude"))
        nvm_bind = (str(home / ".nvm"), str(home / ".nvm"))

        # * assert .gemini and .claude binds ARE present
        assert gemini_bind in rw, "SYNTHESIS path must bind ~/.gemini read-write"
        assert claude_bind in rw, "SYNTHESIS path must bind ~/.claude read-write"
        assert nvm_bind in ro, "SYNTHESIS path must bind ~/.nvm read-only"

        # * assert "--unshare-net" NOT in argv
        assert "--unshare-net" not in argv_synth, "SYNTHESIS path must NOT contain --unshare-net"
        assert "--unshare-ipc" not in argv_synth, "SYNTHESIS path must NOT contain --unshare-ipc"
