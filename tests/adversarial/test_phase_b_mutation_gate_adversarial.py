"""Phase B adversarial — mutation / fix-detector acceptance gate.

Pins G-MUTATION-GATE: a ``meta_task_type == 'test_authoring'`` accept (or any
task declaring ``mutations`` / ``mutation_target``) must clear a non-vacuity
gate inside ``harness.orchestrator._auto_commit_accepted`` BEFORE the accepted
ledger row is written and the staging commit is merged to the parent.

The gate re-runs the task's ``verification_command`` in a throwaway COPY of the
staging worktree with each declared mutant applied. A genuine detector test
MUST fail against the mutant; if the test still passes despite the mutant the
test is VACUOUS -> the accept is rolled back, a ``mutation_gate_failed`` row is
appended, and the staging change is NOT merged to the parent. A
``test_authoring`` task that declares NO mutant fails closed
(``mutation_gate_missing``). All OTHER tasks are unaffected (no-op).

Driven END-TO-END through the REAL ``_auto_commit_accepted`` against a real
parent git repo + sibling staging worktree, reusing the W81 /
test_phase_m_merge_reliability fixture style (real temp git repos, no agents,
no worker).

HEAD MATRIX (gate absent on HEAD 9a993e9):
  (A) genuine detector  -> ACCEPT (passes pre+post; positive control, not discriminating)
  (B) vacuous test      -> REJECT (RED on HEAD: no gate -> vacuous test accepts; GREEN post-fix)
  (C) no-mutant fail-closed -> REJECT (RED on HEAD: no gate -> accepts; GREEN post-fix)
  (D) non-test_authoring no-op -> ACCEPT (passes pre+post; positive control)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from harness.orchestrator import _auto_commit_accepted


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "JanusMask Test")
    env.setdefault("GIT_AUTHOR_EMAIL", "test@janusmask.local")
    env.setdefault("GIT_COMMITTER_NAME", "JanusMask Test")
    env.setdefault("GIT_COMMITTER_EMAIL", "test@janusmask.local")
    return subprocess.run(
        ["git", *args], cwd=str(cwd), env=env, check=True,
        capture_output=True, text=True, timeout=60,
    )


def _read_rows(ledger: Path) -> list[dict]:
    if not ledger.exists():
        return []
    return [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]


# The module under verification. ``feature()`` returns the GOOD value; the
# authored test (genuine cases) pins it. A mutant rewrites GOOD->BAD so a real
# detector fails. Kept dependency-free so the gate's copied-tree re-run is fully
# self-contained (no real harness module needed).
_TARGET_REL = "feature_mod.py"
_MODULE_GOOD = '''def feature():
    return "GOOD"
'''
# A whole-file agent output that keeps feature()=="GOOD" (so a genuine authored
# test still passes against the staged code) but ADDS a new top-level symbol so
# the AST merge produces a real (non no-op) diff to commit. A trailing comment
# would be dropped by the AST re-render, so we add a function instead.
_MODULE_OUTPUT = '''def feature():
    return "GOOD"


def feature_touched():
    return "GOOD"
'''

# Authored test that is a GENUINE detector: passes on GOOD, fails on the mutant.
_TEST_GENUINE = '''from feature_mod import feature


def test_feature_returns_good():
    assert feature() == "GOOD"
'''

# Authored test that is VACUOUS: passes regardless of feature()'s value, so it
# survives the same mutant a genuine detector would catch.
_TEST_VACUOUS = '''def test_always_true():
    assert True
'''

# The mutant: rewrite the GOOD return value in the COPIED staging tree so a
# genuine detector fails but a vacuous test still passes. Operates on the
# relative path inside the copy (cwd == the copied staging root).
_MUTANT_APPLY = (
    'python -c "import pathlib; '
    "p=pathlib.Path('feature_mod.py'); "
    "p.write_text(p.read_text().replace('GOOD','BAD'))\""
)

# vcmd runs the authored test against the staged code, scoped to the test file
# so it is not rewritten by the orchestrator's unscoped-pytest guard.
_TEST_REL = "test_authored_feature.py"
_VCMD = f'python -m pytest -p no:cacheprovider -q {_TEST_REL}'


def _make_parent(tmp_path: Path, *, module_src: str, test_src: str | None):
    """Parent git repo with the target module (+ optional authored test)
    committed, plus a state_dir with output/ + tasks/processed/. The committed
    files appear in the staging worktree _auto_commit_accepted creates as a
    sibling, so vcmd can import/run them there.

    Returns (state_dir, worktree).
    """
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    _git(worktree, "init", "-q", "-b", "main")
    _git(worktree, "config", "user.name", "JanusMask Test")
    _git(worktree, "config", "user.email", "test@janusmask.local")
    state_dir = worktree / "state"
    (state_dir / "output").mkdir(parents=True)
    (state_dir / "tasks" / "processed").mkdir(parents=True)
    (worktree / _TARGET_REL).write_text(module_src, encoding="utf-8")
    _git(worktree, "add", _TARGET_REL)
    if test_src is not None:
        (worktree / _TEST_REL).write_text(test_src, encoding="utf-8")
        _git(worktree, "add", _TEST_REL)
    _git(worktree, "commit", "-q", "-m", "initial")
    return state_dir, worktree


# ---------------------------------------------------------------------------
# (A) GENUINE DETECTOR -> gate ACCEPTS  (positive control; passes pre+post)
# ---------------------------------------------------------------------------
def test_phase_b_genuine_detector_accepts(tmp_path):
    """A 'test_authoring' accept whose authored test PASSES against the staged
    code and FAILS against the declared mutant -> the gate passes, the accept
    lands, an event=auto_commit accepted row is written, and NO
    mutation_gate_failed row appears.

    Positive control: HEAD (no gate) also accepts, so this alone does NOT
    discriminate the fix. It guards against the gate over-rejecting genuine
    detectors post-fix.
    """
    state_dir, _ = _make_parent(tmp_path, module_src=_MODULE_GOOD, test_src=_TEST_GENUINE)
    task_id = "PHASE_B_GENUINE"
    (state_dir / "output" / f"{task_id}.py").write_text(_MODULE_OUTPUT, encoding="utf-8")
    task = {
        "task_id": task_id,
        "meta_task_type": "test_authoring",
        "files_touched": [_TARGET_REL],
        "verification_command": _VCMD,
        "mutations": [{"apply": _MUTANT_APPLY, "expect": "fail"}],
    }

    committed = _auto_commit_accepted(state_dir, task, task_id)
    assert committed is True, "genuine detector (test fails on the mutant) must be accepted"

    rows = _read_rows(state_dir / "impl_progress.jsonl")
    accepted = [r for r in rows if r.get("event") == "auto_commit"]
    assert len(accepted) == 1, f"expected one accepted row, got {accepted}"
    assert accepted[0]["phase"] == "accepted"
    assert [r for r in rows if r.get("event") == "mutation_gate_failed"] == [], (
        "a genuine detector must NOT emit mutation_gate_failed"
    )


# ---------------------------------------------------------------------------
# (B) VACUOUS TEST -> gate REJECTS  (THE discriminating fail-then-pass)
# ---------------------------------------------------------------------------
def test_phase_b_vacuous_test_rejected(tmp_path):
    """THE core detector. Same end-to-end accept, but the authored test is
    VACUOUS (``assert True``): it passes BOTH the correct staged code AND the
    mutant. The gate must REJECT -> return False, write a mutation_gate_failed
    rejected row, and NOT merge the staging change into the parent.

    RED on HEAD (no gate): the vacuous test passes verification, so
    _auto_commit_accepted returns True with an event=auto_commit row and no
    mutation_gate_failed row -> every assertion below fails.
    GREEN post-fix.
    """
    state_dir, worktree = _make_parent(tmp_path, module_src=_MODULE_GOOD, test_src=_TEST_VACUOUS)
    parent_head_before = _git(worktree, "rev-parse", "HEAD").stdout.strip()

    task_id = "PHASE_B_VACUOUS"
    (state_dir / "output" / f"{task_id}.py").write_text(_MODULE_OUTPUT, encoding="utf-8")
    task = {
        "task_id": task_id,
        "meta_task_type": "test_authoring",
        "files_touched": [_TARGET_REL],
        "verification_command": _VCMD,
        "mutations": [{"apply": _MUTANT_APPLY, "expect": "fail"}],
    }

    committed = _auto_commit_accepted(state_dir, task, task_id)
    assert committed is False, (
        "vacuous test (passes even against the mutant) must be REJECTED by the gate"
    )

    rows = _read_rows(state_dir / "impl_progress.jsonl")
    gate_failed = [r for r in rows if r.get("event") == "mutation_gate_failed"]
    assert len(gate_failed) >= 1, (
        f"a mutation_gate_failed rejected row must be written; rows={rows}"
    )
    assert gate_failed[0]["phase"] == "rejected"
    assert [r for r in rows if r.get("event") == "auto_commit"] == [], (
        "a vacuous-test accept must NOT emit an auto_commit accepted row"
    )

    # The staging change must NOT have been merged into the parent.
    parent_head_after = _git(worktree, "rev-parse", "HEAD").stdout.strip()
    assert parent_head_after == parent_head_before, (
        "parent HEAD must be unchanged: a rejected accept must not merge to parent"
    )
    assert (worktree / _TARGET_REL).read_text(encoding="utf-8") == _MODULE_GOOD, (
        "parent target file must be untouched on a gate rejection"
    )


# ---------------------------------------------------------------------------
# (C) FAIL-CLOSED: 'test_authoring' with NO mutant -> REJECT
# ---------------------------------------------------------------------------
def test_phase_b_test_authoring_without_mutant_fails_closed(tmp_path):
    """A 'test_authoring' task that declares NEITHER mutations NOR
    mutation_target must fail closed: return False + a mutation_gate_missing
    rejected row, with no merge to parent.

    RED on HEAD (no gate): such a task is accepted (returns True, auto_commit
    row, no mutation_gate_missing row). GREEN post-fix.
    """
    state_dir, worktree = _make_parent(tmp_path, module_src=_MODULE_GOOD, test_src=_TEST_GENUINE)
    parent_head_before = _git(worktree, "rev-parse", "HEAD").stdout.strip()

    task_id = "PHASE_B_NOMUTANT"
    (state_dir / "output" / f"{task_id}.py").write_text(_MODULE_OUTPUT, encoding="utf-8")
    task = {
        "task_id": task_id,
        "meta_task_type": "test_authoring",
        "files_touched": [_TARGET_REL],
        "verification_command": _VCMD,
        # NO mutations, NO mutation_target -> fail closed.
    }

    committed = _auto_commit_accepted(state_dir, task, task_id)
    assert committed is False, "test_authoring task with no mutant must fail closed"

    rows = _read_rows(state_dir / "impl_progress.jsonl")
    missing = [r for r in rows if r.get("event") == "mutation_gate_missing"]
    assert len(missing) >= 1, (
        f"a mutation_gate_missing rejected row must be written; rows={rows}"
    )
    assert missing[0]["phase"] == "rejected"
    assert [r for r in rows if r.get("event") == "auto_commit"] == [], (
        "a fail-closed test_authoring task must NOT emit an auto_commit row"
    )
    parent_head_after = _git(worktree, "rev-parse", "HEAD").stdout.strip()
    assert parent_head_after == parent_head_before, (
        "parent HEAD must be unchanged on a fail-closed rejection"
    )


# ---------------------------------------------------------------------------
# (C2) un-appliable mutant -> REJECT fail-closed (also RED on HEAD: gate absent)
# ---------------------------------------------------------------------------
def test_phase_b_unappliable_mutant_fails_closed(tmp_path):
    """If a declared mutant cannot be applied (the ``apply`` command exits
    non-zero), the gate cannot prove non-vacuity, so it must reject fail-closed
    (mutation_gate_failed). RED on HEAD (gate absent -> accept); GREEN post-fix.
    """
    state_dir, worktree = _make_parent(tmp_path, module_src=_MODULE_GOOD, test_src=_TEST_GENUINE)
    parent_head_before = _git(worktree, "rev-parse", "HEAD").stdout.strip()

    task_id = "PHASE_B_BADMUTANT"
    (state_dir / "output" / f"{task_id}.py").write_text(_MODULE_OUTPUT, encoding="utf-8")
    task = {
        "task_id": task_id,
        "meta_task_type": "test_authoring",
        "files_touched": [_TARGET_REL],
        "verification_command": _VCMD,
        # An apply command that always fails -> mutant cannot be applied.
        "mutations": [{"apply": "exit 7", "expect": "fail"}],
    }

    committed = _auto_commit_accepted(state_dir, task, task_id)
    assert committed is False, "an un-appliable mutant must reject fail-closed"

    rows = _read_rows(state_dir / "impl_progress.jsonl")
    assert [r for r in rows if r.get("event") == "mutation_gate_failed"], (
        f"un-appliable mutant must emit mutation_gate_failed; rows={rows}"
    )
    assert [r for r in rows if r.get("event") == "auto_commit"] == []
    assert _git(worktree, "rev-parse", "HEAD").stdout.strip() == parent_head_before


# ---------------------------------------------------------------------------
# (D) NO-OP REGRESSION: a normal task (no test_authoring, no mutant) accepts
#     exactly as before  (positive control; passes pre+post)
# ---------------------------------------------------------------------------
def test_phase_b_normal_task_unaffected(tmp_path):
    """A normal accept (NOT test_authoring, NO mutations/mutation_target) must
    behave exactly as before the gate: it accepts, writes an auto_commit row,
    and merges to parent. Guards against the gate engaging for ordinary tasks.

    Passes on HEAD AND post-fix (the gate is a no-op here).
    """
    state_dir, worktree = _make_parent(tmp_path, module_src=_MODULE_GOOD, test_src=None)
    task_id = "PHASE_B_NORMAL"
    (state_dir / "output" / f"{task_id}.py").write_text(_MODULE_OUTPUT, encoding="utf-8")
    task = {
        "task_id": task_id,
        "files_touched": [_TARGET_REL],
        "verification_command": "true",
    }

    committed = _auto_commit_accepted(state_dir, task, task_id)
    assert committed is True, "a normal accept must be unaffected by the gate"

    rows = _read_rows(state_dir / "impl_progress.jsonl")
    accepted = [r for r in rows if r.get("event") == "auto_commit"]
    assert len(accepted) == 1 and accepted[0]["phase"] == "accepted"
    assert [r for r in rows if r.get("event") in ("mutation_gate_failed", "mutation_gate_missing")] == []
    # The accept was merged to the parent: the new symbol from the agent output
    # is now present in the parent target file (AST merge may re-render quoting/
    # whitespace, so assert on the added symbol rather than byte equality).
    merged = (worktree / _TARGET_REL).read_text(encoding="utf-8")
    assert "feature_touched" in merged, (
        "the normal accept must merge the agent's added symbol into the parent"
    )


# ---------------------------------------------------------------------------
# (H1-1) MALFORMED mutation_target -> REJECT mutation_gate_error (no raise)
# ---------------------------------------------------------------------------
def test_phase_b_malformed_mutation_target_rejected(tmp_path):
    """RED on current HEAD (no target validation → the malformed
    target either crashes or is mis-handled, so no `mutation_gate_error` row);
    GREEN post-H1.
    """
    state_dir, worktree = _make_parent(tmp_path, module_src=_MODULE_GOOD, test_src=_TEST_GENUINE)
    parent_head_before = _git(worktree, "rev-parse", "HEAD").stdout.strip()

    task_id = "PHASE_B_MALFORMED_TARGET"
    (state_dir / "output" / f"{task_id}.py").write_text(_MODULE_OUTPUT, encoding="utf-8")
    task = {
        "task_id": task_id,
        "meta_task_type": "test_authoring",
        "files_touched": [_TARGET_REL],
        "verification_command": _VCMD,
        "mutation_target": "feature_mod.py",
    }

    try:
        committed = _auto_commit_accepted(state_dir, task, task_id)
    except Exception as e:
        pytest.fail(f"the H1 gate must catch target validation errors and return False, not raise: {e}")

    assert committed is False, "malformed mutation_target must be rejected fail-closed"

    rows = _read_rows(state_dir / "impl_progress.jsonl")
    err_rows = [r for r in rows if r.get("event") == "mutation_gate_error"]
    assert len(err_rows) >= 1, f"expected mutation_gate_error event, got rows={rows}"
    assert err_rows[0]["phase"] == "rejected"
    assert [r for r in rows if r.get("event") == "auto_commit"] == []

    parent_head_after = _git(worktree, "rev-parse", "HEAD").stdout.strip()
    assert parent_head_after == parent_head_before, "parent HEAD must be unchanged on target rejection"
    assert (worktree / _TARGET_REL).read_text(encoding="utf-8") == _MODULE_GOOD, (
        "parent target file must be untouched on target rejection"
    )


# ---------------------------------------------------------------------------
# (H1-2) UNEXPECTED gate exception -> caught, rolled back, return False (no raise)
# ---------------------------------------------------------------------------
def test_phase_b_gate_exception_rolls_back_and_does_not_raise(tmp_path, monkeypatch):
    """RED on current HEAD (no try/except → the OSError propagates and
    the test errors / the staging commit is left un-rolled-back, and there is no
    `mutation_gate_error` row); GREEN post-H1 (caught, rolled back, returns False).
    """
    state_dir, worktree = _make_parent(tmp_path, module_src=_MODULE_GOOD, test_src=_TEST_GENUINE)
    parent_head_before = _git(worktree, "rev-parse", "HEAD").stdout.strip()

    task_id = "PHASE_B_GATE_EXC"
    (state_dir / "output" / f"{task_id}.py").write_text(_MODULE_OUTPUT, encoding="utf-8")
    task = {
        "task_id": task_id,
        "meta_task_type": "test_authoring",
        "files_touched": [_TARGET_REL],
        "verification_command": _VCMD,
        "mutations": [{"apply": _MUTANT_APPLY, "expect": "fail"}],
    }

    def _boom(*args, **kwargs):
        raise OSError("simulated ENOSPC")

    monkeypatch.setattr(shutil, "copytree", _boom)

    try:
        committed = _auto_commit_accepted(state_dir, task, task_id)
    except Exception as e:
        pytest.fail(f"the H1 gate must catch the exception and return False, not raise: {e}")

    assert committed is False

    rows = _read_rows(state_dir / "impl_progress.jsonl")
    err_rows = [r for r in rows if r.get("event") == "mutation_gate_error"]
    assert len(err_rows) >= 1, f"expected mutation_gate_error event, got rows={rows}"
    assert err_rows[0]["phase"] == "rejected"
    assert [r for r in rows if r.get("event") == "auto_commit"] == []

    parent_head_after = _git(worktree, "rev-parse", "HEAD").stdout.strip()
    assert parent_head_after == parent_head_before, "parent HEAD must be unchanged on exception"
    assert (worktree / _TARGET_REL).read_text(encoding="utf-8") == _MODULE_GOOD, (
        "parent target file must be untouched on exception"
    )
