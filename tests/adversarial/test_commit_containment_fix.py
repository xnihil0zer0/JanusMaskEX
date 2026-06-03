"""Pytest oracle for COMMIT_CONTAINMENT_FIX.

RED on HEAD: _commit_accepted_output_multi and _commit_accepted_output_patches
unconditionally call target_path.relative_to(worktree_root) immediately after the
union containment guard passes, raising ValueError for external-contained targets.
After the fix: the functions resolve relative to the containing root, completing
the execution or returning a committed dict without raising ValueError.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import pytest

import harness.paths
from harness.git_integration import (
    _commit_accepted_output_multi,
    _commit_accepted_output_patches,
)


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


def test_external_multi_commit_containment_no_value_error(tmp_path, monkeypatch):
    """External multi commit resolves the containment path relative to external root.

    On HEAD, this raises an unhandled ValueError when calling relative_to(worktree_root).
    """
    external_root = (tmp_path / "external_root").resolve()
    external_root.mkdir()
    worktree_root = (tmp_path / "staging_repo").resolve()
    worktree_root.mkdir()

    # Initialize staging_repo as a git repository so git commands inside it succeed
    _git(worktree_root, "init", "-b", "main")
    _git(worktree_root, "config", "user.name", "t")
    _git(worktree_root, "config", "user.email", "t@example.com")

    seed_file = worktree_root / "mod.py"
    seed_file.write_text("def foo():\n    pass\n", encoding="utf-8")
    _git(worktree_root, "add", "mod.py")
    _git(worktree_root, "commit", "-m", "seed")

    # Create target file under external_root
    ext_file = external_root / "mod.py"
    ext_file.write_text("def foo():\n    pass\n", encoding="utf-8")

    # Monkeypatch to force classification as external and set external root
    monkeypatch.setattr(harness.paths, "_target_is_self", lambda wd=None: False)
    monkeypatch.setattr(harness.paths, "effective_target_root", lambda wd=None: external_root)

    state_dir = tmp_path / "state"
    output_dir = state_dir / "output"
    output_dir.mkdir(parents=True)
    sidecar_path = output_dir / "task_multi.files.json"

    # Manifest with a key pointing to external_root (worktree_root/rel resolves to external_root)
    sidecar_path.write_text(
        json.dumps({"../external_root/mod.py": "def foo():\n    return 99\n"}),
        encoding="utf-8"
    )

    result = {"committed": False, "sha": None, "error": None}

    # Call directly. On HEAD the unconditional rel_str =
    # str(target_path.relative_to(worktree_root)) at git_integration.py:915
    # raises an UNHANDLED ValueError for the external-contained case (path
    # under effective_target_root but NOT under worktree_root). After the fix
    # rel_str is computed against the containing (external) root, so NO
    # ValueError propagates and the function returns the result dict.
    try:
        res = _commit_accepted_output_multi(
            task_id="task_multi",
            sidecar_path=sidecar_path,
            state_dir=state_dir,
            worktree_root=worktree_root,
            result=result,
            allowed_files={"mod.py"},
            working_dir=str(external_root),
        )
    except ValueError as exc:
        pytest.fail(
            "_commit_accepted_output_multi raised an unhandled ValueError on the "
            "external-contained case (union guard accepted the path under "
            "effective_target_root, then relative_to(worktree_root) at "
            f"git_integration.py:915 raised): {exc}"
        )

    # After the fix the external commit is rejected cleanly (the staging git add
    # cannot stage a path outside worktree_root) or committed cleanly; either way
    # the function returns the dict shape WITHOUT raising.
    assert isinstance(res, dict), "Result must be a dictionary"
    assert "error" in res and "committed" in res


def test_external_patches_commit_containment_no_value_error(tmp_path, monkeypatch):
    """External patches commit resolves the containment path relative to external root.

    On HEAD, this raises an unhandled ValueError when calling relative_to(worktree_root).
    """
    external_root = (tmp_path / "external_root").resolve()
    external_root.mkdir()
    worktree_root = (tmp_path / "staging_repo").resolve()
    worktree_root.mkdir()

    # Initialize staging_repo as a git repository
    _git(worktree_root, "init", "-b", "main")
    _git(worktree_root, "config", "user.name", "t")
    _git(worktree_root, "config", "user.email", "t@example.com")

    seed_file = worktree_root / "mod.py"
    seed_file.write_text("def foo():\n    pass\n", encoding="utf-8")
    _git(worktree_root, "add", "mod.py")
    _git(worktree_root, "commit", "-m", "seed")

    # Create target file under external_root
    ext_file = external_root / "mod.py"
    ext_file.write_text("def foo():\n    pass\n", encoding="utf-8")

    # Monkeypatch to force classification as external and set external root
    monkeypatch.setattr(harness.paths, "_target_is_self", lambda wd=None: False)
    monkeypatch.setattr(harness.paths, "effective_target_root", lambda wd=None: external_root)

    state_dir = tmp_path / "state"
    output_dir = state_dir / "output"
    output_dir.mkdir(parents=True)
    sidecar_path = output_dir / "task_patches.patches.json"

    # Manifest with a key pointing to external_root (worktree_root/rel resolves to external_root)
    sidecar_path.write_text(
        json.dumps([
            {
                "file": "../external_root/mod.py",
                "kind": "symbol",
                "name": "foo",
                "code": "def foo():\n    return 42\n"
            }
        ]),
        encoding="utf-8"
    )

    result = {"committed": False, "sha": None, "error": None}

    # Call directly. On HEAD the unconditional rel_str =
    # str(target_path.relative_to(worktree_root)) at git_integration.py:1265
    # raises an UNHANDLED ValueError for the external-contained case. After the
    # fix rel_str is computed against the containing (external) root, so NO
    # ValueError propagates.
    try:
        res = _commit_accepted_output_patches(
            task_id="task_patches",
            patches_sidecar_path=sidecar_path,
            state_dir=state_dir,
            worktree_root=worktree_root,
            result=result,
            allowed_files={"mod.py"},
            working_dir=str(external_root),
        )
    except ValueError as exc:
        pytest.fail(
            "_commit_accepted_output_patches raised an unhandled ValueError on the "
            "external-contained case (union guard accepted the path under "
            "effective_target_root, then relative_to(worktree_root) at "
            f"git_integration.py:1265 raised): {exc}"
        )

    assert isinstance(res, dict), "Result must be a dictionary"
    assert "error" in res and "committed" in res


def test_self_multi_commit_regression(tmp_path):
    """SELF multi commit regression test.

    A normal in-worktree manifest commits fine. Green pre+post.
    """
    worktree_root = (tmp_path / "worktree").resolve()
    worktree_root.mkdir()

    _git(worktree_root, "init", "-b", "main")
    _git(worktree_root, "config", "user.name", "t")
    _git(worktree_root, "config", "user.email", "t@example.com")

    seed_file = worktree_root / "mod.py"
    seed_file.write_text("def foo():\n    pass\n", encoding="utf-8")
    _git(worktree_root, "add", "mod.py")
    _git(worktree_root, "commit", "-m", "seed")

    state_dir = tmp_path / "state"
    output_dir = state_dir / "output"
    output_dir.mkdir(parents=True)
    sidecar_path = output_dir / "task_self.files.json"

    sidecar_path.write_text(
        json.dumps({"mod.py": "def foo():\n    return 100\n"}),
        encoding="utf-8"
    )

    result = {"committed": False, "sha": None, "error": None}

    res = _commit_accepted_output_multi(
        task_id="task_self",
        sidecar_path=sidecar_path,
        state_dir=state_dir,
        worktree_root=worktree_root,
        result=result,
        allowed_files={"mod.py"}
    )

    assert isinstance(res, dict)
    assert res.get("committed") is True, f"Failed: {res.get('error')}"
    assert res.get("error") is None
    assert isinstance(res.get("sha"), str) and len(res["sha"]) == 40
    assert "return 100" in (worktree_root / "mod.py").read_text()


def test_self_patches_commit_regression(tmp_path):
    """SELF patches commit regression test.

    A normal in-worktree patches manifest commits fine. Green pre+post.
    """
    worktree_root = (tmp_path / "worktree").resolve()
    worktree_root.mkdir()

    _git(worktree_root, "init", "-b", "main")
    _git(worktree_root, "config", "user.name", "t")
    _git(worktree_root, "config", "user.email", "t@example.com")

    seed_file = worktree_root / "mod.py"
    seed_file.write_text("def foo():\n    pass\n", encoding="utf-8")
    _git(worktree_root, "add", "mod.py")
    _git(worktree_root, "commit", "-m", "seed")

    state_dir = tmp_path / "state"
    output_dir = state_dir / "output"
    output_dir.mkdir(parents=True)
    sidecar_path = output_dir / "task_self_patches.patches.json"

    sidecar_path.write_text(
        json.dumps([
            {
                "file": "mod.py",
                "kind": "symbol",
                "name": "foo",
                "code": "def foo():\n    return 200\n"
            }
        ]),
        encoding="utf-8"
    )

    result = {"committed": False, "sha": None, "error": None}

    res = _commit_accepted_output_patches(
        task_id="task_self_patches",
        patches_sidecar_path=sidecar_path,
        state_dir=state_dir,
        worktree_root=worktree_root,
        result=result,
        allowed_files={"mod.py"}
    )

    assert isinstance(res, dict)
    assert res.get("committed") is True, f"Failed: {res.get('error')}"
    assert res.get("error") is None
    assert isinstance(res.get("sha"), str) and len(res["sha"]) == 40
    assert "return 200" in (worktree_root / "mod.py").read_text()
