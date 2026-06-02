"""Adversarial/regression oracle for the MERGE_REROOT task.

Pins signature and source-level changes to merge_staging_to_parent and its
call site in harness/orchestrator.py, and provides a regression test.
"""
from __future__ import annotations

import inspect
import re
import subprocess
import pathlib
import pytest

from harness.git_integration import merge_staging_to_parent
from harness.orchestrator import _auto_commit_accepted
from harness import git_integration


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True)


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q", "-b", "main"], path)
    _git(["config", "user.name", "Test User"], path)
    _git(["config", "user.email", "test@janusmask.local"], path)


def test_merge_staging_to_parent_signature():
    """Assert a keyword-only working_dir parameter exists on merge_staging_to_parent."""
    sig = inspect.signature(merge_staging_to_parent)
    assert 'working_dir' in sig.parameters, "Keyword-only parameter 'working_dir' is missing."
    param = sig.parameters['working_dir']
    assert param.kind == inspect.Parameter.KEYWORD_ONLY, "working_dir must be a keyword-only parameter."


def test_merge_staging_to_parent_source():
    """Assert merge_staging_to_parent references _target_is_self, janusmask/work, and HEAD:refs/heads/janusmask/work."""
    src = inspect.getsource(merge_staging_to_parent)
    assert "_target_is_self" in src, "merge_staging_to_parent must reference '_target_is_self'."
    assert "janusmask/work" in src, "merge_staging_to_parent must reference the string 'janusmask/work'."
    assert "HEAD:refs/heads/janusmask/work" in src, "merge_staging_to_parent must reference the string 'HEAD:refs/heads/janusmask/work'."


def test_orchestrator_call_threads_working_dir():
    """Assert the merge_staging_to_parent CALL specifically threads working_dir=working_dir.

    RED on HEAD: the merge call is ``merge_staging_to_parent(staging_path, worktree_root)``
    with no working_dir. COMMIT_REROOT already threads working_dir into the *commit* call,
    so a plain ``"working_dir=working_dir" in src`` check is a false positive — this test
    targets the merge_staging_to_parent invocation itself.
    """
    src = inspect.getsource(_auto_commit_accepted)
    # Find the merge_staging_to_parent(...) call argument list and assert it carries working_dir.
    m = re.search(r"merge_staging_to_parent\s*\((?P<args>[^)]*)\)", src)
    assert m is not None, "could not locate the merge_staging_to_parent call in _auto_commit_accepted"
    assert "working_dir=working_dir" in m.group("args"), (
        "_auto_commit_accepted must thread working_dir=working_dir into the "
        "merge_staging_to_parent(...) call so the merge can re-root external tasks"
    )


def test_merge_staging_self_regression(tmp_path):
    """Regression test (negative control): self tasks (default None working_dir) still perform fast-forward merge and clean up staging."""
    parent = tmp_path / "parent"
    _init_repo(parent)
    
    (parent / "target.txt").write_text("base content\n", encoding="utf-8")
    _git(["add", "target.txt"], parent)
    _git(["commit", "-q", "-m", "initial commit"], parent)
    
    staging = tmp_path / "parent_staging"
    git_integration.create_staging_worktree(str(staging), parent_root=parent)
    
    (staging / "target.txt").write_text("staging edit\n", encoding="utf-8")
    _git(["add", "target.txt"], staging)
    _git(["commit", "-q", "-m", "staging edit"], staging)
    
    merge_staging_to_parent(staging, parent_root=parent)
    
    head_content = _git(["show", "HEAD:target.txt"], parent).stdout
    assert head_content == "staging edit\n"
    assert not staging.exists()
