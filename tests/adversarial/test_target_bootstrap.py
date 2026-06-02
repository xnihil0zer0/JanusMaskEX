"""Adversarial oracle for harness/target_bootstrap.py (REV22 §4-7).

Idempotent external-repo bootstrap. RED on HEAD (module absent → ImportError),
GREEN after the module lands.

Covers:
* greenfield dir → git init + janusmask/work branch + marker + .gitignore
  + external-staging root, returns resolved root,
* .resolve() happens (symlink to greenfield resolves through),
* idempotent re-run on a JM-owned tree → no-op (no raise, marker preserved),
* DIRTY pre-existing repo → BootstrapRefused,
* FOREIGN .git (no JM marker) → BootstrapRefused,
* SELF working_dir is classified not-bootstrappable by the caller predicate
  (paths._target_is_self stays True for the repo root).

Uses a real ``git`` subprocess in tmp dirs (mirrors create_staging_worktree
tests) and an isolated $JANUSMASK_AGENT_WORKROOT so the staging root lands
in tmp, never the real sibling dir.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from harness import target_bootstrap as tb
from harness import paths


@pytest.fixture(autouse=True)
def _isolated_workroot(tmp_path, monkeypatch):
    wr = tmp_path / "agentwork"
    wr.mkdir()
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(wr))
    allow = tmp_path / "external_roots.allow"
    allow.write_text(str(tmp_path) + "\n", encoding="utf-8")
    monkeypatch.setenv("JANUSMASK_EXTERNAL_ROOTS_ALLOW", str(allow))
    yield wr


def _git(args, cwd, check=True):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=check
    )


def _branch_exists(root: Path, name: str) -> bool:
    res = _git(
        ["show-ref", "--verify", "--quiet", f"refs/heads/{name}"], cwd=root, check=False
    )
    return res.returncode == 0


def _make_foreign_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(["init"], cwd=root)
    _git(["config", "user.email", "u@example.com"], cwd=root)
    _git(["config", "user.name", "User"], cwd=root)
    (root / "README.md").write_text("user code\n", encoding="utf-8")
    _git(["add", "-A"], cwd=root)
    _git(["commit", "-m", "user initial"], cwd=root)


def test_greenfield_bootstrap_provisions_everything(tmp_path):
    target = tmp_path / "ext"
    target.mkdir()

    returned = tb.bootstrap_target(str(target))

    assert returned == target.resolve()
    assert (target / ".git").exists(), "git init should have run"
    assert _branch_exists(target, "janusmask/work"), "janusmask/work branch (CR-10)"
    marker = target / ".janusmask" / "bootstrap.json"
    assert marker.is_file(), "JM ownership marker written"
    obj = json.loads(marker.read_text(encoding="utf-8"))
    assert obj.get("owner") == "janusmask"
    gi = target / ".gitignore"
    assert gi.is_file() and ".janusmask/" in gi.read_text(encoding="utf-8")
    # CR-3: external staging root under agent_workroot()
    assert tb.external_staging_root().is_dir()


def test_resolve_happens_before_marker_check(tmp_path):
    real = tmp_path / "realext"
    real.mkdir()
    link = tmp_path / "linkext"
    link.symlink_to(real, target_is_directory=True)

    returned = tb.bootstrap_target(str(link))
    # resolved through the symlink to the real dir
    assert returned == real.resolve()
    assert (real / ".janusmask" / "bootstrap.json").is_file()


def test_idempotent_rerun_is_noop(tmp_path):
    target = tmp_path / "ext"
    target.mkdir()
    tb.bootstrap_target(str(target))
    marker = target / ".janusmask" / "bootstrap.json"
    first = marker.read_text(encoding="utf-8")

    # second run must NOT raise and must NOT clobber user content
    (target / "user_added.txt").write_text("work\n", encoding="utf-8")
    returned = tb.bootstrap_target(str(target))

    assert returned == target.resolve()
    assert marker.read_text(encoding="utf-8") == first
    assert (target / "user_added.txt").read_text(encoding="utf-8") == "work\n"
    assert _branch_exists(target, "janusmask/work")


def test_dirty_tree_is_refused(tmp_path):
    target = tmp_path / "ext"
    target.mkdir()
    tb.bootstrap_target(str(target))  # JM-owned now
    # introduce an uncommitted change, then strip the marker so it is
    # re-evaluated as a non-owned dirty repo
    (target / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
    (target / ".janusmask" / "bootstrap.json").unlink()

    with pytest.raises(tb.BootstrapRefused):
        tb.bootstrap_target(str(target))


def test_foreign_git_without_marker_is_refused(tmp_path):
    target = tmp_path / "userrepo"
    _make_foreign_repo(target)

    with pytest.raises(tb.BootstrapRefused):
        tb.bootstrap_target(str(target))
    # untouched: no marker, no JM branch
    assert not (target / ".janusmask" / "bootstrap.json").exists()
    assert not _branch_exists(target, "janusmask/work")


def test_self_working_dir_classified_self_by_predicate():
    # The caller gate: a self path must classify as self so bootstrap is
    # never invoked against the harness's own repo.
    assert paths._target_is_self(str(paths.PROJECT_ROOT)) is True
    assert paths._target_is_self(None) is True
