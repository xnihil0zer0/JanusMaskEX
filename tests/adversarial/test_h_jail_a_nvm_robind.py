"""H_JAIL_A oracle: verify that ~/.nvm is bound read-only in the bwrap jail.

Repo path: tests/adversarial/test_h_jail_a_nvm_robind.py

RED on HEAD: the current build_jail_argv binds ~/.nvm as read-write using --bind.
GREEN after the fix: ~/.nvm is bound read-only using --ro-bind.

PURELY STRUCTURAL: this test mocks shutil.which so the bwrap path-check passes and
inspects the CONSTRUCTED argv list directly. It does NOT invoke bwrap and does NOT
require bwrap to be installed (so it can never silently skip / pass vacuously). It
uses a temporary home directory so it does not depend on the host's actual HOME.
"""
import os
import tempfile
from unittest.mock import patch
from harness.agent_jail import build_jail_argv


def test_h_jail_a_nvm_read_only():
    """Assert that ~/.nvm is bound read-only. RED on HEAD."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create dummy HOME directories to trigger the binds
        os.makedirs(os.path.join(tmp_dir, ".nvm"))
        os.makedirs(os.path.join(tmp_dir, ".gemini"))
        os.makedirs(os.path.join(tmp_dir, ".claude"))

        # Create dummy repo, work, and state dirs
        repo_root = os.path.join(tmp_dir, "repo")
        work_dir = os.path.join(tmp_dir, "work")
        state_dir = os.path.join(tmp_dir, "state")
        os.makedirs(repo_root)
        os.makedirs(work_dir)
        os.makedirs(state_dir)

        # Mock shutil.which so bwrap path check passes
        with patch("shutil.which", return_value="/usr/bin/bwrap"):
            argv = build_jail_argv(
                cmd=["python", "-c", "print(1)"],
                repo_root=repo_root,
                work_dir=work_dir,
                state_dir=state_dir,
                home=tmp_dir,
            )

            nvm_path = os.path.join(tmp_dir, ".nvm")

            # Check that ~/.nvm is bound with --ro-bind and NOT --bind
            ro_binds = []
            for i, arg in enumerate(argv):
                if arg == nvm_path:
                    if i >= 1 and argv[i - 1] in ("--ro-bind", "--bind"):
                        ro_binds.append(argv[i - 1])
                    elif i >= 2 and argv[i - 2] in ("--ro-bind", "--bind"):
                        ro_binds.append(argv[i - 2])

            assert "--ro-bind" in ro_binds, f"~/.nvm must be ro-bound: {argv}"
            assert "--bind" not in ro_binds, f"~/.nvm must NOT be rw-bound: {argv}"


def test_h_jail_a_other_binds_preserved():
    """Assert ~/.gemini and ~/.claude remain read-write binds. REGRESSION."""
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

        with patch("shutil.which", return_value="/usr/bin/bwrap"):
            argv = build_jail_argv(
                cmd=["python", "-c", "print(1)"],
                repo_root=repo_root,
                work_dir=work_dir,
                state_dir=state_dir,
                home=tmp_dir,
            )

            gemini_path = os.path.join(tmp_dir, ".gemini")
            claude_path = os.path.join(tmp_dir, ".claude")

            gemini_mode = None
            claude_mode = None

            for i, arg in enumerate(argv):
                if arg == gemini_path:
                    if i >= 1 and argv[i - 1] in ("--ro-bind", "--bind"):
                        gemini_mode = argv[i - 1]
                    elif i >= 2 and argv[i - 2] in ("--ro-bind", "--bind"):
                        gemini_mode = argv[i - 2]

                if arg == claude_path:
                    if i >= 1 and argv[i - 1] in ("--ro-bind", "--bind"):
                        claude_mode = argv[i - 1]
                    elif i >= 2 and argv[i - 2] in ("--ro-bind", "--bind"):
                        claude_mode = argv[i - 2]

            assert gemini_mode == "--bind", f"~/.gemini must remain rw-bound: {argv}"
            assert claude_mode == "--bind", f"~/.claude must remain rw-bound: {argv}"
