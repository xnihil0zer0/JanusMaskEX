"""W81 adversarial — auto_commit ledger row.

After ``harness.orchestrator._auto_commit_accepted`` lands a successful
commit, an ``event=auto_commit`` row MUST appear in
``state_dir/impl_progress.jsonl``. A failed/no-op call MUST NOT emit a
row. Closes the META audit-trail divergence diagnosed in
``brief_hooks_meta_layer_freeze.md`` §6 (4 prior auto-commits landed
without ledger evidence: ecd75e6, 6ec6e29, d48bd8c, a260e30).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from harness.orchestrator import _auto_commit_accepted


ORIGINAL_MODULE = '''def existing():
    return 1
'''

OUTPUT_MODULE_DIVERGENT = '''def existing():
    return 1


def added():
    return 2
'''


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "JanusMask Test")
    env.setdefault("GIT_AUTHOR_EMAIL", "test@janusmask.local")
    env.setdefault("GIT_COMMITTER_NAME", "JanusMask Test")
    env.setdefault("GIT_COMMITTER_EMAIL", "test@janusmask.local")
    return subprocess.run(
        ["git", *args], cwd=str(cwd), env=env, check=True,
        capture_output=True, text=True, timeout=30,
    )


@pytest.fixture
def merge_harness(tmp_path: Path):
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    _git(worktree, "init", "-q", "-b", "main")
    _git(worktree, "config", "user.name", "JanusMask Test")
    _git(worktree, "config", "user.email", "test@janusmask.local")
    state_dir = worktree / "state"
    (state_dir / "output").mkdir(parents=True)
    (state_dir / "tasks" / "processed").mkdir(parents=True)
    target_rel = "module_w81.py"
    (worktree / target_rel).write_text(ORIGINAL_MODULE, encoding="utf-8")
    _git(worktree, "add", target_rel)
    _git(worktree, "commit", "-q", "-m", "initial")
    return state_dir, target_rel


def _read_rows(ledger: Path) -> list[dict]:
    if not ledger.exists():
        return []
    return [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]


def test_successful_auto_commit_appends_ledger_row(merge_harness):
    state_dir, target_rel = merge_harness
    task_id = "W81-LEDGER-OK"
    (state_dir / "output" / f"{task_id}.py").write_text(OUTPUT_MODULE_DIVERGENT, encoding="utf-8")
    task = {"task_id": task_id, "files_touched": [target_rel], "verification_command": "true"}

    committed = _auto_commit_accepted(state_dir, task, task_id)
    assert committed is True

    rows = _read_rows(state_dir / "impl_progress.jsonl")
    auto_commit_rows = [r for r in rows if r.get("event") == "auto_commit"]
    assert len(auto_commit_rows) == 1
    row = auto_commit_rows[0]
    assert row["task_id"] == task_id
    assert row["phase"] == "accepted"
    assert row["files"] == [target_rel]
    assert row["exit"] == 0
    assert isinstance(row["commit_sha"], str)
    assert len(row["commit_sha"]) >= 7
    assert "ts" in row


def test_no_op_commit_does_not_append_ledger_row(merge_harness):
    """When agent output matches baseline, no commit is produced and no
    ledger row should appear (R4 §F edge case)."""
    state_dir, target_rel = merge_harness
    task_id = "W81-LEDGER-NOOP"
    # Output identical to baseline -> no diff -> no commit.
    (state_dir / "output" / f"{task_id}.py").write_text(ORIGINAL_MODULE, encoding="utf-8")
    task = {"task_id": task_id, "files_touched": [target_rel]}

    committed = _auto_commit_accepted(state_dir, task, task_id)
    assert committed is False

    rows = _read_rows(state_dir / "impl_progress.jsonl")
    auto_commit_rows = [r for r in rows if r.get("event") == "auto_commit"]
    assert auto_commit_rows == [], (
        f"no-op auto-commit should not emit a ledger row, got: {auto_commit_rows}"
    )


def test_unresolvable_files_touched_does_not_append_row(merge_harness):
    """If files_touched cannot be resolved, _auto_commit_accepted returns
    False before invoking commit_accepted_output. No row should appear."""
    state_dir, _ = merge_harness
    task_id = "W81-LEDGER-NOFILES"
    task = {"task_id": task_id}  # no files_touched, no parent
    committed = _auto_commit_accepted(state_dir, task, task_id)
    assert committed is False
    rows = _read_rows(state_dir / "impl_progress.jsonl")
    assert [r for r in rows if r.get("event") == "auto_commit"] == []
