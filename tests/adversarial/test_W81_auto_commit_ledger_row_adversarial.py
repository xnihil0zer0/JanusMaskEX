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



# --- Phase L: multi-file partial-edit accept ledger fidelity ------------------

_L_MODULE_A_ORIGINAL = '''def alpha():
    return 1
'''

_L_MODULE_A_PATCHED = '''def alpha():
    return 11
'''

_L_MODULE_B_ORIGINAL = '''def beta():
    return 2
'''

_L_MODULE_B_PATCHED = '''def beta():
    return 22
'''


@pytest.fixture
def multifile_patch_harness(tmp_path: Path):
    """A parent git worktree with TWO tracked .py modules, ready for a
    multi-file __JANUSMASK_PATCHES__ accept driven through _auto_commit_accepted.

    Mirrors the W81 ``merge_harness`` setup but commits two files so a partial
    edit can touch both. Returns (state_dir, [rel_a, rel_b]).
    """
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    _git(worktree, "init", "-q", "-b", "main")
    _git(worktree, "config", "user.name", "JanusMask Test")
    _git(worktree, "config", "user.email", "test@janusmask.local")
    state_dir = worktree / "state"
    (state_dir / "output").mkdir(parents=True)
    (state_dir / "tasks" / "processed").mkdir(parents=True)
    rel_a = "module_a_w81L.py"
    rel_b = "module_b_w81L.py"
    (worktree / rel_a).write_text(_L_MODULE_A_ORIGINAL, encoding="utf-8")
    (worktree / rel_b).write_text(_L_MODULE_B_ORIGINAL, encoding="utf-8")
    _git(worktree, "add", rel_a, rel_b)
    _git(worktree, "commit", "-q", "-m", "initial two-file")
    return state_dir, [rel_a, rel_b]


def test_multifile_partial_edit_ledger_records_all_committed_files(multifile_patch_harness):
    """FIX-DETECTOR (G-M-MULTIFILE-LEDGER): the accepted ledger row must list
    EVERY file committed by a multi-file __JANUSMASK_PATCHES__ accept, not just
    files_touched[0].

    Pre-fix harness/orchestrator.py:1672 writes 'files': [target_rel] (a single
    file), so the second committed module is invisible in the audit trail. The
    fix writes 'files': files_touched. This test commits a 2-file partial edit
    and asserts both files appear; it FAILS on the old single-element row and
    PASSES on the fixed full-list row.
    """
    state_dir, (rel_a, rel_b) = multifile_patch_harness
    task_id = "W81-L-MULTIFILE-LEDGER"

    # Two-entry partial-edit sidecar: one symbol patch per file.
    patches = [
        {"file": rel_a, "kind": "symbol", "name": "alpha", "code": _L_MODULE_A_PATCHED},
        {"file": rel_b, "kind": "symbol", "name": "beta", "code": _L_MODULE_B_PATCHED},
    ]
    (state_dir / "output" / f"{task_id}.patches.json").write_text(
        json.dumps(patches), encoding="utf-8")

    task = {
        "task_id": task_id,
        "partial_edit": True,
        "files_touched": [rel_a, rel_b],
        "verification_command": "true",
    }

    committed = _auto_commit_accepted(state_dir, task, task_id)
    assert committed is True, "multi-file partial-edit accept should commit"

    rows = _read_rows(state_dir / "impl_progress.jsonl")
    accepted_rows = [r for r in rows if r.get("event") == "auto_commit"]
    assert len(accepted_rows) == 1, f"expected one accept row, got {accepted_rows}"
    row = accepted_rows[0]
    assert row["phase"] == "accepted"
    assert row["exit"] == 0

    files = row["files"]
    assert isinstance(files, list)
    # The core fix-detector: BOTH committed files must be recorded, not just
    # files_touched[0]. Pre-fix this is exactly [rel_a] and the assertion fails.
    assert set(files) == {rel_a, rel_b}, (
        "accepted ledger row must list ALL committed files for a multi-file "
        f"partial edit (G-M-MULTIFILE-LEDGER); got {files!r}, expected both "
        f"{rel_a!r} and {rel_b!r}"
    )


def test_single_file_accept_ledger_row_still_lists_exactly_that_file(merge_harness):
    """Regression guard for the Phase L fix: a single-file whole-file accept's
    ledger row must STILL record exactly the one committed file.

    The fix ('files': files_touched) must degrade to the single-element case
    identically to the old 'files': [target_rel] for a one-file task. Reuses the
    W81 single-file ``merge_harness``.
    """
    state_dir, target_rel = merge_harness
    task_id = "W81-L-SINGLE-LEDGER"
    (state_dir / "output" / f"{task_id}.py").write_text(
        OUTPUT_MODULE_DIVERGENT, encoding="utf-8")
    task = {"task_id": task_id, "files_touched": [target_rel], "verification_command": "true"}

    committed = _auto_commit_accepted(state_dir, task, task_id)
    assert committed is True

    rows = _read_rows(state_dir / "impl_progress.jsonl")
    accepted_rows = [r for r in rows if r.get("event") == "auto_commit"]
    assert len(accepted_rows) == 1
    assert accepted_rows[0]["files"] == [target_rel], (
        "single-file accept must record exactly the one committed file"
    )
