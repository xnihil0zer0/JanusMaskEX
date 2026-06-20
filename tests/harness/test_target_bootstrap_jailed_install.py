"""Oracle: ``harness/target_bootstrap.py::_ensure_venv`` must install external-target
deps inside a NETWORK-RESTRICTED, FS-scoped bwrap jail, from the target's OWN
lockfile only -- never a host ``pip install`` with the network on, and never a
package named by dependency-resolution stderr.

P0.2 (g8_dep_install_jailed_lockfile), JanusMask side. Final repo path:
``tests/harness/test_target_bootstrap_jailed_install.py``.

RED on HEAD: ``_ensure_venv`` runs ``subprocess.run([pip, 'install', ... '-r', req])``
directly on the host -- no jail, the host network is live, build hooks run on the host,
and there is no helper that constructs a jailed argv. Every assertion below fails:
``_jailed_install_argv`` does not exist; the recorded install argv is a bare ``pip``
list (argv[0] is the host pip, not bwrap, no ``--unshare-net``).

GREEN after fix: a pure helper ``_jailed_install_argv(...)`` builds the install command
via ``harness.agent_jail.build_jail_argv(..., bind_credentials=False)`` so the argv is a
bwrap wrapper carrying ``--unshare-net`` (no-net), the venv scratch is the ONLY writable
host bind (no ``~/.gemini``/``~/.claude``/``$HOME`` rw bind), the install reads ONLY the
lockfile (``-r <req>``) and NEVER a stderr-named package, and ``_ensure_venv`` dispatches
the real install through that argv.

Non-vacuity / no real network or bwrap needed: ``shutil.which`` is mocked to a fake bwrap
so ``build_jail_argv`` constructs a real argv on any host; the install subprocess is
stubbed (no network, no host writes) and we assert structurally on the constructed argv.
"""
import os
import unittest.mock as mock

import pytest

import harness.target_bootstrap as tb


_BWRAP = "/usr/bin/bwrap"


def _mk_target(tmp_path, *, req_lines="requests==2.31.0\n", py_version=None):
    """Create a minimal external target tree with a lockfile (+ optional pin)."""
    root = tmp_path / "target"
    root.mkdir()
    (root / "requirements.txt").write_text(req_lines, encoding="utf-8")
    if py_version is not None:
        (root / ".python-version").write_text(py_version + "\n", encoding="utf-8")
    return root


def test_jailed_install_argv_exists_and_is_pure():
    """The helper that constructs the install argv must exist (RED: AttributeError)."""
    assert hasattr(tb, "_jailed_install_argv"), (
        "_ensure_venv must build its install command through a "
        "_jailed_install_argv(...) helper so the argv is independently assertable"
    )


def _build_argv(tmp_path, **kw):
    root = _mk_target(tmp_path, **kw)
    venv = tmp_path / "scratch_venv"
    venv.mkdir()
    req = root / "requirements.txt"
    with mock.patch("shutil.which", return_value=_BWRAP):
        argv = tb._jailed_install_argv(
            root=root, venv=venv, req=req, pip=venv / "bin" / "pip"
        )
    return root, venv, req, argv


def test_install_runs_under_unshare_net(tmp_path):
    """RED: host pip install has the network ON. GREEN: jailed with --unshare-net."""
    _, _, _, argv = _build_argv(tmp_path)
    assert argv[0] == _BWRAP, f"install must run inside the bwrap jail, got argv[0]={argv[0]!r}"
    assert "--unshare-net" in argv, "the install jail MUST unshare the network (no-net)"


def test_lockfile_only_install(tmp_path):
    """The install reads ONLY the lockfile (-r <req>), not loose package names."""
    root, _, req, argv = _build_argv(tmp_path)
    assert "-r" in argv, "install must be lockfile-driven (-r <req>)"
    assert str(req) in argv, "the target's own lockfile must be the install source"


def test_never_installs_stderr_named_package(tmp_path):
    """A reactive/stderr-driven path would add 'evil-pkg'; the jailed argv never does.

    RED: HEAD has no argv helper at all; once it exists the lockfile-only argv must
    contain neither a package not in the lockfile nor anything an attacker could name
    via dependency-resolution stderr.
    """
    # lockfile names ONLY 'safe-pkg'; a malicious resolver would print 'evil-pkg' on stderr.
    _, _, _, argv = _build_argv(tmp_path, req_lines="safe-pkg==1.0.0\n")
    joined = " ".join(argv)
    assert "evil-pkg" not in joined, "a stderr-named package must NEVER reach the install argv"
    # the argv must not pass any bare package name as an install target -- only -r <req>.
    # (everything after 'install' is either a flag, the -r marker, or the lockfile path.)
    assert "safe-pkg" not in argv, (
        "the install must be lockfile-driven; no individual package name belongs in the argv"
    )


def test_no_host_rw_bind_beyond_scratch(tmp_path):
    """A malicious build hook must not write outside the venv scratch.

    Assert the ONLY read-WRITE host binds are the venv scratch (and the bwrap
    work_dir, which IS the scratch here) -- no ~/.gemini / ~/.claude / $HOME rw bind.
    """
    root, venv, _, argv = _build_argv(tmp_path)
    rw_targets = [argv[i + 1] for i, a in enumerate(argv) if a == "--bind"]
    home = os.path.realpath(os.environ.get("HOME", "/home"))
    for t in rw_targets:
        rt = os.path.realpath(t)
        assert not rt.startswith(os.path.join(home, ".gemini")), f"unexpected rw bind of creds: {t}"
        assert not rt.startswith(os.path.join(home, ".claude")), f"unexpected rw bind of creds: {t}"
    # the venv scratch must itself be a writable bind so pip can install into it.
    assert any(os.path.realpath(t) == os.path.realpath(str(venv)) for t in rw_targets), (
        "the venv scratch must be a read-WRITE bind so the jailed pip can install into it"
    )
    # the target repo must be present READ-ONLY (so pip reads the lockfile, can't tamper).
    ro_targets = [argv[i + 1] for i, a in enumerate(argv) if a == "--ro-bind"]
    assert any(os.path.realpath(t) == os.path.realpath(str(root)) for t in ro_targets), (
        "the target repo must be ro-bound (lockfile readable, source untamperable)"
    )


def test_abi_uses_pinned_interpreter(tmp_path):
    """ABI: the venv interpreter resolves the target's pinned .python-version.

    A target pinning 3.11 must drive venv creation with a 3.11 interpreter request
    (README §2 ABI caveat). RED: HEAD ignores .python-version entirely.
    """
    root = _mk_target(tmp_path, py_version="3.11")
    chosen = tb._resolve_target_interpreter(root)
    assert chosen is not None
    # the resolver returns either an explicit interpreter path/name encoding 3.11,
    # or a (interpreter, version) signal naming the pin.
    assert "3.11" in str(chosen), f"pinned .python-version 3.11 must steer the interpreter, got {chosen!r}"


def test_ensure_venv_dispatches_through_jail_no_host_write(tmp_path):
    """End-to-end: _ensure_venv runs its dep install through the jailed argv only.

    The install subprocess is stubbed: assert (a) the recorded install argv is the
    bwrap-jailed --unshare-net command, NOT a bare host ``pip install``, and (b) no
    host write happened outside the captured argv (host FS unchanged -- the stub
    performs no real install).
    """
    root = _mk_target(tmp_path)
    recorded = []

    real_run = tb.subprocess.run

    def fake_run(argv, *a, **kw):
        recorded.append(list(argv) if isinstance(argv, (list, tuple)) else argv)
        # let the `python -m venv` call run for real (creates the scratch venv +
        # its bin/pip) but stub the actual dependency INSTALL (no network).
        if isinstance(argv, (list, tuple)) and any("venv" == str(x) for x in argv):
            return real_run(argv, *a, **kw)

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        return _R()

    with mock.patch("shutil.which", return_value=_BWRAP), \
         mock.patch.object(tb.subprocess, "run", side_effect=fake_run):
        tb._ensure_venv(root)

    install_cmds = [c for c in recorded if isinstance(c, list) and any("install" == str(x) for x in c)]
    assert install_cmds, "an install command must have been dispatched"
    for cmd in install_cmds:
        assert cmd[0] == _BWRAP, f"dep install must be bwrap-jailed, got argv[0]={cmd[0]!r}"
        assert "--unshare-net" in cmd, "dep install must run with the network unshared"


def test_no_lockfile_is_a_noop(tmp_path):
    """NEGATIVE/regression: a target with no lockfile installs nothing (no crash)."""
    root = tmp_path / "nolock"
    root.mkdir()
    with mock.patch.object(tb.subprocess, "run") as run:
        tb._ensure_venv(root)
    # no requirements file -> early return -> zero subprocesses.
    assert run.call_count == 0
