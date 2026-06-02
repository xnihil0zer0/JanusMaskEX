"""Adversarial oracle for KEYRING-GATE (REV22 §1a).

The XDG keyring socket (``<xdg>/keyring``) is bound into the jail INDEPENDENT
of ``bind_credentials``. On the EXECUTE path (``bind_credentials=False``) the
credential surface -- ``~/.gemini`` / ``~/.claude`` / ``~/.claude.json`` and the
global-config overlays -- is dropped, but the keyring socket is still bound.
The fix gates the keyring bind by ``bind_credentials`` (defense-in-depth: the
execute path already gets ``--unshare-net``/``--unshare-ipc``).

RED on HEAD: the keyring bind is emitted unconditionally, so the
bind_credentials=False assertion below fails.
GREEN after the fix: keyring is bound ONLY when bind_credentials=True.

The bus socket is INTENTIONALLY out of scope here -- the bus is the path to the
(filtering) D-Bus proxy and its handling is unchanged by this task; the oracle
asserts only on the keyring token.
"""

from __future__ import annotations

import shutil

from harness.agent_jail import build_jail_argv


def _pairs(argv: list[str], flag: str) -> list[tuple[str, str]]:
    """All (src, dst) pairs following occurrences of ``flag`` in argv."""
    out = []
    for i, tok in enumerate(argv):
        if tok == flag and i + 2 < len(argv):
            out.append((argv[i + 1], argv[i + 2]))
    return out


def _make_tree(tmp_path):
    """Build a minimal jail call surface + an on-disk mock XDG with bus+keyring.

    Returns (kwargs, keyring_path) where kwargs are the common build_jail_argv
    keyword args (bind_credentials still to be supplied by the caller).
    """
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    (home_dir / ".nvm").mkdir()
    (home_dir / ".gemini").mkdir()
    (home_dir / ".claude").mkdir()

    repo_root = tmp_path / "repo"
    work_dir = tmp_path / "work"
    state_dir = tmp_path / "state"
    repo_root.mkdir()
    work_dir.mkdir()
    state_dir.mkdir()

    mock_xdg = tmp_path / "run_user_mock"
    mock_xdg.mkdir()
    (mock_xdg / "bus").touch()
    keyring = mock_xdg / "keyring"
    keyring.mkdir()

    kwargs = dict(
        cmd=["python", "-c", "print(1)"],
        repo_root=repo_root,
        work_dir=work_dir,
        state_dir=state_dir,
        home=home_dir,
    )
    return kwargs, mock_xdg, keyring


def test_execute_spawn_does_not_bind_keyring(tmp_path, monkeypatch):
    """bind_credentials=False (the execute path): the keyring socket must NOT be
    bound into the jail. This is the RED-detecting assertion -- on unfixed HEAD
    the keyring is bound unconditionally."""
    kwargs, mock_xdg, keyring = _make_tree(tmp_path)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(mock_xdg))
    monkeypatch.setattr(
        shutil, "which",
        lambda cmd: "/usr/bin/bwrap" if cmd == "bwrap" else None,
    )

    argv = build_jail_argv(bind_credentials=False, **kwargs)

    # Sanity: the execute-path exfil control is present (so we are genuinely on
    # the bind_credentials=False branch).
    assert "--unshare-net" in argv, f"execute spawn must --unshare-net: {argv}"

    rw = _pairs(argv, "--bind")
    ro = _pairs(argv, "--ro-bind")
    assert (str(keyring), str(keyring)) not in rw, (
        f"keyring must NOT be bound on the execute path (bind_credentials=False): {argv}"
    )
    assert (str(keyring), str(keyring)) not in ro, (
        f"keyring must NOT be ro-bound on the execute path: {argv}"
    )
    # Robust flat-argv check: the keyring socket path must not appear as a bind
    # target token at all on the execute path.
    assert str(keyring) not in argv, (
        f"keyring socket path leaked into execute-spawn argv: {argv}"
    )


def test_synthesis_spawn_still_binds_keyring(tmp_path, monkeypatch):
    """bind_credentials=True (the synthesis path, default): the keyring socket is
    still bound rw -- agy's OAuth refresh needs it. Guards against an over-broad
    fix that drops keyring on BOTH paths."""
    kwargs, mock_xdg, keyring = _make_tree(tmp_path)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(mock_xdg))
    monkeypatch.setattr(
        shutil, "which",
        lambda cmd: "/usr/bin/bwrap" if cmd == "bwrap" else None,
    )

    argv = build_jail_argv(bind_credentials=True, **kwargs)

    assert "--unshare-net" not in argv, (
        f"synthesis spawn must NOT --unshare-net (agy OAuth needs the net): {argv}"
    )
    rw = _pairs(argv, "--bind")
    assert (str(keyring), str(keyring)) in rw, (
        f"keyring must STILL be bound on the synthesis path (bind_credentials=True): {argv}"
    )


def test_default_call_binds_keyring(tmp_path, monkeypatch):
    """bind_credentials defaults to True -- a call that omits it must bind keyring
    (byte-for-byte the prior synthesis behavior)."""
    kwargs, mock_xdg, keyring = _make_tree(tmp_path)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(mock_xdg))
    monkeypatch.setattr(
        shutil, "which",
        lambda cmd: "/usr/bin/bwrap" if cmd == "bwrap" else None,
    )

    argv = build_jail_argv(**kwargs)  # bind_credentials omitted -> default True

    rw = _pairs(argv, "--bind")
    assert (str(keyring), str(keyring)) in rw, (
        f"default (bind_credentials=True) call must bind keyring: {argv}"
    )
