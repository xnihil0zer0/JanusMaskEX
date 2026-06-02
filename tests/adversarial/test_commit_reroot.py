"""Pytest oracle for COMMIT_REROOT (REV23 §3-3 + §3-6 + §2a/b).

RED on HEAD: the auto-commit path does not yet thread ``working_dir`` into
``commit_accepted_output`` and therefore cannot re-root parent_root, skip the
JM sensitive globs, force ``untracked_files=[]``, or re-point write-containment
at ``effective_target_root(working_dir)`` for EXTERNAL targets. The behavioral
detector below FAILS on HEAD (the ``working_dir`` param / source threading is
absent) and PASSES once the fix lands. The SELF smoke is a regression guard
that stays GREEN both before and after.

Copied to tests/adversarial/test_commit_reroot.py by the brief.
"""

from __future__ import annotations

import inspect
import os
import pathlib
import subprocess

import pytest

from harness.git_integration import commit_accepted_output
from harness.orchestrator import _auto_commit_accepted


def _git(cwd: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "t")
    env.setdefault("GIT_AUTHOR_EMAIL", "t@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "t")
    env.setdefault("GIT_COMMITTER_EMAIL", "t@example.com")
    return subprocess.run(
        ["git", *args], cwd=str(cwd), env=env, check=True,
        capture_output=True, text=True,
    )


def test_working_dir_param_threaded():
    """commit_accepted_output must accept a ``working_dir`` kw param (RED on HEAD).

    On HEAD the signature has no ``working_dir`` and calling with it raises
    TypeError. After the fix the param exists and is keyword-only.
    """
    sig = inspect.signature(commit_accepted_output)
    assert "working_dir" in sig.parameters, (
        "commit_accepted_output must expose a working_dir parameter so the "
        "orchestrator can classify the target tree (self vs external)"
    )
    param = sig.parameters["working_dir"]
    assert param.kind == inspect.Parameter.KEYWORD_ONLY, (
        "working_dir must be keyword-only (after the * in the signature)"
    )


def test_external_retarget_and_globs_skip_source():
    """commit_accepted_output re-roots parent_root + skips sensitive globs for external (RED on HEAD).

    On HEAD the function only derives parent_root from git rev-parse and always
    passes the default _SENSITIVE_APPLY_GLOBS to _enforce_apply_scope -> neither
    ``effective_target_root`` nor an explicit ``sensitive_globs=`` argument
    appears in the source. After the fix both are present in the external branch.
    """
    src = inspect.getsource(commit_accepted_output)
    assert "effective_target_root" in src, (
        "external parent_root / containment must derive from "
        "harness.paths.effective_target_root(working_dir)"
    )
    assert "_target_is_self" in src, (
        "the self/external classification predicate must be referenced"
    )
    assert "sensitive_globs" in src, (
        "external commits must pass an explicit (empty) sensitive_globs to "
        "_enforce_apply_scope so the JM globs do not spuriously gate a foreign repo"
    )


def test_orchestrator_passes_working_dir_to_commit():
    """_auto_commit_accepted's commit_accepted_output call must pass working_dir (RED on HEAD).

    On HEAD the call site omits working_dir; after the fix it threads the
    already-read working_dir into the commit.
    """
    src = inspect.getsource(_auto_commit_accepted)
    assert "working_dir=working_dir" in src, (
        "_auto_commit_accepted must pass working_dir=working_dir into "
        "git_integration.commit_accepted_output"
    )


def test_self_regression_smoke(tmp_path: pathlib.Path) -> None:
    """SELF commit (no working_dir) still commits a normal file. Green pre+post fix."""
    root = tmp_path / "wt"
    root.mkdir()
    _git(root, "init", "-b", "main", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "commit", "--allow-empty", "-m", "root")

    target = root / "mod.py"
    target.write_text("def foo():\n    return 1\n")
    _git(root, "add", "mod.py")
    _git(root, "commit", "-m", "seed")

    sd = root / "state"
    (sd / "output").mkdir(parents=True)
    (sd / "output" / "T.py").write_text("def foo():\n    return 2\n")

    result = commit_accepted_output("T", str(target), sd)
    assert result["committed"] is True, result
    assert result["error"] is None
    assert isinstance(result["sha"], str) and len(result["sha"]) == 40
    assert "return 2" in target.read_text()
