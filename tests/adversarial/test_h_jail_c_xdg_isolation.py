"""H_JAIL_C oracle: verify that XDG_RUNTIME_DIR bind is isolated to minimal keyring/bus paths.

Repo path: tests/adversarial/test_h_jail_c_xdg_isolation.py

RED on HEAD: the current build_jail_argv binds the entire XDG_RUNTIME_DIR read-write.
GREEN after the fix: only the minimal bus and keyring sockets/paths are bound inside a tmpfs.
"""
import os
import tempfile
from unittest.mock import patch
from harness.agent_jail import build_jail_argv


def _pairs(argv, flag):
    """All (src, dst) pairs following occurrences of ``flag`` in argv."""
    out = []
    for i, tok in enumerate(argv):
        if tok == flag and i + 2 < len(argv):
            out.append((argv[i + 1], argv[i + 2]))
    return out


def test_h_jail_c_xdg_isolated_binds():
    """Assert that XDG_RUNTIME_DIR is not bound wholesale, and minimal paths are isolated. RED on HEAD."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create dummy dirs for nvm, gemini, claude to avoid skipping them
        os.makedirs(os.path.join(tmp_dir, ".nvm"))
        os.makedirs(os.path.join(tmp_dir, ".gemini"))
        os.makedirs(os.path.join(tmp_dir, ".claude"))

        repo_root = os.path.join(tmp_dir, "repo")
        work_dir = os.path.join(tmp_dir, "work")
        state_dir = os.path.join(tmp_dir, "state")
        os.makedirs(repo_root)
        os.makedirs(work_dir)
        os.makedirs(state_dir)

        # Mock XDG_RUNTIME_DIR on disk
        mock_xdg = os.path.join(tmp_dir, "run_user_mock")
        os.makedirs(mock_xdg)
        os.makedirs(os.path.join(mock_xdg, "keyring"))
        with open(os.path.join(mock_xdg, "bus"), "w") as f:
            f.write("")

        with patch("shutil.which", return_value="/usr/bin/bwrap"), \
             patch.dict(os.environ, {"XDG_RUNTIME_DIR": mock_xdg}):
            
            argv = build_jail_argv(
                cmd=["python", "-c", "print(1)"],
                repo_root=repo_root,
                work_dir=work_dir,
                state_dir=state_dir,
                home=tmp_dir,
            )

            # 1. Whole XDG must not be bound RW
            rw_binds = _pairs(argv, "--bind")
            assert (mock_xdg, mock_xdg) not in rw_binds, f"Whole XDG dir {mock_xdg} must NOT be bound RW: {argv}"

            # 2. Whole XDG must not be bound RO
            ro_binds = _pairs(argv, "--ro-bind")
            assert (mock_xdg, mock_xdg) not in ro_binds, f"Whole XDG dir {mock_xdg} must NOT be bound RO: {argv}"

            # 3. A tmpfs must be mounted at mock_xdg
            tmpfs_mounts = []
            for i, arg in enumerate(argv):
                if arg == "--tmpfs" and i + 1 < len(argv):
                    tmpfs_mounts.append(argv[i + 1])
            assert mock_xdg in tmpfs_mounts, f"A tmpfs must be mounted at {mock_xdg}: {argv}"

            # 4. Minimal sockets/paths must be bound RW
            assert (os.path.join(mock_xdg, "bus"), os.path.join(mock_xdg, "bus")) in rw_binds, f"bus socket must be bound RW: {argv}"
            assert (os.path.join(mock_xdg, "keyring"), os.path.join(mock_xdg, "keyring")) in rw_binds, f"keyring must be bound RW: {argv}"


def test_h_jail_c_xdg_absent_sockets_skipped():
    """Assert that if keyring/bus are absent, their binds are skipped. REGRESSION."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.makedirs(os.path.join(tmp_dir, ".nvm"))
        os.makedirs(os.path.join(tmp_dir, ".gemini"))
        os.makedirs(os.path.join(tmp_dir, ".claude"))

        repo_root = os.path.join(tmp_dir, "repo")
        work_dir = os.path.join(tmp_dir, "work")
        state_dir = os.path.join(tmp_dir, "state")
        os.makedirs(repo_root)
        os.makedirs(work_dir)
        os.makedirs(state_dir)

        # Mock XDG_RUNTIME_DIR on disk but leave keyring and bus absent
        mock_xdg = os.path.join(tmp_dir, "run_user_mock")
        os.makedirs(mock_xdg)

        with patch("shutil.which", return_value="/usr/bin/bwrap"), \
             patch.dict(os.environ, {"XDG_RUNTIME_DIR": mock_xdg}):
            
            argv = build_jail_argv(
                cmd=["python", "-c", "print(1)"],
                repo_root=repo_root,
                work_dir=work_dir,
                state_dir=state_dir,
                home=tmp_dir,
            )

            rw_binds = _pairs(argv, "--bind")
            assert (mock_xdg, mock_xdg) not in rw_binds
            
            # tmpfs should still be mounted
            tmpfs_mounts = []
            for i, arg in enumerate(argv):
                if arg == "--tmpfs" and i + 1 < len(argv):
                    tmpfs_mounts.append(argv[i + 1])
            assert mock_xdg in tmpfs_mounts

            # bus and keyring must not be bound since they don't exist
            assert not any(arg == os.path.join(mock_xdg, "bus") for arg in argv)
            assert not any(arg == os.path.join(mock_xdg, "keyring") for arg in argv)


def test_h_jail_c_xdg_missing_entirely_skipped():
    """Assert that if XDG_RUNTIME_DIR itself does not exist, everything is skipped. REGRESSION."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.makedirs(os.path.join(tmp_dir, ".nvm"))
        os.makedirs(os.path.join(tmp_dir, ".gemini"))
        os.makedirs(os.path.join(tmp_dir, ".claude"))

        repo_root = os.path.join(tmp_dir, "repo")
        work_dir = os.path.join(tmp_dir, "work")
        state_dir = os.path.join(tmp_dir, "state")
        os.makedirs(repo_root)
        os.makedirs(work_dir)
        os.makedirs(state_dir)

        # mock_xdg does not exist on disk
        mock_xdg = os.path.join(tmp_dir, "run_user_mock_nonexistent")

        with patch("shutil.which", return_value="/usr/bin/bwrap"), \
             patch.dict(os.environ, {"XDG_RUNTIME_DIR": mock_xdg}):
            
            argv = build_jail_argv(
                cmd=["python", "-c", "print(1)"],
                repo_root=repo_root,
                work_dir=work_dir,
                state_dir=state_dir,
                home=tmp_dir,
            )

            # Nothing relating to mock_xdg should be in argv
            argv_str = " ".join(argv)
            assert mock_xdg not in argv_str, f"No reference to nonexistent XDG should be present: {argv}"
