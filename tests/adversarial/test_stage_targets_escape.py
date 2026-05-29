"""Adversarial plan 01 — T7: _stage_targets path-escape guard.

_stage_targets copies each resolved files_touched into inbox/targets/<rel> for
the relocated-CWD agent. The src.relative_to(repo_root) guard (orchestrator.py
:2523) must skip any rel that resolves outside repo_root (../.., absolute, or a
symlink escape) and never raise (best-effort).

  T7a — ../../etc/passwd, /etc/hostname (absolute), and a symlink that resolves
        outside the repo are all SKIPPED; an in-repo regular file IS copied.
  T7b — the escape guard still applies to the _resolve_files_touched exception
        fallback (raw task['files_touched']).

No agy/claude spawned. Pure filesystem.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import harness.orchestrator as orch


@pytest.fixture
def repo(tmp_path):
    """A tmp 'repo' whose state_dir is repo/state (repo_root = state.parent)."""
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "state").mkdir(parents=True)
    (repo / "pkg" / "inside.py").write_text("x = 1\n")
    # an outside-repo secret to attempt to exfiltrate
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET\n")
    return repo


def test_T7a_escapes_skipped_inrepo_copied(repo, tmp_path, monkeypatch):
    state_dir = repo / "state"
    inbox = repo / "wd" / "inbox"
    inbox.mkdir(parents=True)
    task_json = inbox / "task.json"

    # craft a symlink inside the repo that points OUTSIDE
    link = repo / "pkg" / "escape_link.py"
    try:
        link.symlink_to(tmp_path / "secret.txt")
        symlink_ok = True
    except OSError:
        symlink_ok = False

    touched = ["pkg/inside.py", "../../etc/passwd", "/etc/hostname"]
    if symlink_ok:
        touched.append("pkg/escape_link.py")

    task = {"task_id": "T7", "files_touched": touched}
    task_json.write_text(json.dumps(task))

    monkeypatch.setattr(orch, "_resolve_files_touched", lambda sd, t, tid: touched)

    # must not raise
    orch._stage_targets(inbox, state_dir, task_json)

    targets = inbox / "targets"
    assert (targets / "pkg" / "inside.py").is_file(), "in-repo target must be staged"
    # escapes never copied:
    assert not (targets / ".." / ".." / "etc" / "passwd").exists()
    assert not (targets / "etc" / "hostname").exists()
    # the symlink resolves outside repo_root -> skipped (no secret leaked)
    staged_blobs = list(targets.rglob("*"))
    leaked = [p for p in staged_blobs if p.is_file() and p.read_text(errors="replace").strip() == "TOPSECRET"]
    assert not leaked, f"symlink escape leaked secret into {leaked}"


def test_T7b_guard_applies_to_resolve_exception_fallback(repo, monkeypatch):
    """When _resolve_files_touched raises, the raw task list is used and the
    escape guard still applies (no copy from outside the repo)."""
    state_dir = repo / "state"
    inbox = repo / "wd2" / "inbox"
    inbox.mkdir(parents=True)
    task_json = inbox / "task.json"
    task = {"task_id": "T7b", "files_touched": ["../../secret.txt", "pkg/inside.py"]}
    task_json.write_text(json.dumps(task))

    def _boom(*a, **k):
        raise RuntimeError("resolve failed")

    monkeypatch.setattr(orch, "_resolve_files_touched", _boom)

    orch._stage_targets(inbox, state_dir, task_json)  # must not raise

    targets = inbox / "targets"
    assert (targets / "pkg" / "inside.py").is_file()
    # the ../../secret.txt escape must be skipped even on the fallback list
    leaked = [p for p in targets.rglob("*")
              if p.is_file() and p.read_text(errors="replace").strip() == "TOPSECRET"]
    assert not leaked, "escape guard failed on the _resolve_files_touched fallback path"


def test_T7c_corrupt_task_json_is_noop(repo):
    """Best-effort: corrupt/missing task.json never raises."""
    state_dir = repo / "state"
    inbox = repo / "wd3" / "inbox"
    inbox.mkdir(parents=True)
    bad = inbox / "task.json"
    bad.write_text("{not json")
    orch._stage_targets(inbox, state_dir, bad)  # must simply return
    assert not (inbox / "targets").exists() or not list((inbox / "targets").rglob("*"))
