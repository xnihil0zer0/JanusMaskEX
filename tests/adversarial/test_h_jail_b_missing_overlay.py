"""H_JAIL_B oracle: verify that missing sensitive settings/config files
are bound read-only to /dev/null under the bwrap jail if their parent directory exists.

Repo path: tests/adversarial/test_h_jail_b_missing_overlay.py

RED on HEAD: missing sensitive config files under ~/.claude/ or ~/.gemini/ are not bound, leaving them writable under the parent rw binds.
GREEN after the fix: missing files are ro-bound to /dev/null, preventing their creation inside the jail.
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


def test_h_jail_b_missing_overlays_robound():
    """Assert that missing sensitive settings/config paths are ro-bound to /dev/null
    when their parent directories exist on the host. RED on HEAD."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create parent directories but not the files themselves
        claude_dir = os.path.join(tmp_dir, ".claude")
        gemini_dir = os.path.join(tmp_dir, ".gemini")
        os.makedirs(claude_dir)
        os.makedirs(gemini_dir)

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

            ro_binds = _pairs(argv, "--ro-bind")

            sensitive_files = [
                os.path.join(claude_dir, "settings.json"),
                os.path.join(claude_dir, "settings.local.json"),
                os.path.join(claude_dir, "skills"),
                os.path.join(claude_dir, "plugins"),
                os.path.join(gemini_dir, "GEMINI.md"),
                os.path.join(gemini_dir, "config"),
            ]

            for path in sensitive_files:
                assert ("/dev/null", path) in ro_binds, (
                    f"Missing sensitive path {path} must be bound to /dev/null, but was not. "
                    f"Current ro-binds: {ro_binds}"
                )


def test_h_jail_b_missing_overlays_parent_missing_skipped():
    """Assert that if parent directories (~/.claude, ~/.gemini) do not exist,
    missing overlay files are skipped to avoid bwrap mount errors. REGRESSION."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Parent directories .claude and .gemini do NOT exist here

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

            # Flatten argv for quick searching
            argv_str = " ".join(argv)
            
            sensitive_basenames = ["settings.json", "settings.local.json", "skills", "plugins", "GEMINI.md", "config"]
            for name in sensitive_basenames:
                assert name not in argv_str, (
                    f"Sensitive target {name} should be skipped when parent directory does not exist, "
                    f"but was found in argv: {argv}"
                )


def test_h_jail_b_existing_overlays_preserved():
    """Assert that if sensitive settings/config files exist, they are ro-bound to themselves
    rather than /dev/null. REGRESSION."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create parent directories
        claude_dir = os.path.join(tmp_dir, ".claude")
        gemini_dir = os.path.join(tmp_dir, ".gemini")
        os.makedirs(claude_dir)
        os.makedirs(gemini_dir)

        # Create all sensitive files as dummy files
        sensitive_files = [
            os.path.join(claude_dir, "settings.json"),
            os.path.join(claude_dir, "settings.local.json"),
            os.path.join(claude_dir, "skills"),
            os.path.join(claude_dir, "plugins"),
            os.path.join(gemini_dir, "GEMINI.md"),
            os.path.join(gemini_dir, "config"),
        ]
        for path in sensitive_files:
            with open(path, "w") as f:
                f.write("{}")

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

            ro_binds = _pairs(argv, "--ro-bind")

            for path in sensitive_files:
                assert (path, path) in ro_binds, (
                    f"Existing sensitive path {path} must be bound to itself, "
                    f"but was not. Current ro-binds: {ro_binds}"
                )
                assert ("/dev/null", path) not in ro_binds, (
                    f"Existing sensitive path {path} must NOT be bound to /dev/null. "
                    f"Current ro-binds: {ro_binds}"
                )
