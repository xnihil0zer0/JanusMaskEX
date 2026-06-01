"""Phase B MUT-MASK adversarial — mutant INFRA-fail vs genuine assertion-fail.

Pins the MUT-MASK masking defect in ``harness.orchestrator._auto_commit_accepted``.

The Phase-B mutation gate runs the BASELINE verify in the FULL ``staging_path``
worktree, but applies+reruns each mutant inside ``_mcopy`` -- a ``shutil.copytree``
that DROPS ``state``/``samples``/``.pytest_cache``/``*.egg-info`` (the H1-widened
ignore set). The mutant rerun's result is read as ``_mvacuous =
(_mproc.returncode == 0)``: a nonzero exit is credited as "mutant caught" -> accept.

THE DEFECT: a mutant rerun can exit NONZERO for an INFRA reason -- the authored
``verification_command`` touches a path the copytree DROPPED -- even though the
test is actually VACUOUS (it would NOT catch a real mutant). On HEAD that infra
failure is MISREAD as "mutant caught" and the vacuous test is silently ACCEPTED.

THE FIX (Option A, baseline-in-copy): before applying the mutant, re-run the
UNMUTATED vcmd inside ``_mcopy``. If it does not pass (exit != 0) the copy
environment itself is broken (a dropped path) -> raise -> the existing H1
gate try/except rejects fail-closed as ``mutation_gate_error``. The mutant
rerun's nonzero exit is never credited as a catch.

HEAD MATRIX:
  (A) genuine detector (no dropped-path dependency) -> ACCEPT  (positive control;
      passes pre+post; guards against a fix that just rejects everything)
  (B) vacuous test that ALSO touches samples/ (dropped by copytree) -> on HEAD the
      mutant rerun fails for the INFRA reason and is misread as a catch -> ACCEPT
      (RED for this oracle, which expects rejection); after the fix the gate
      rejects with mutation_gate_error -> GREEN.

Driven END-TO-END through the REAL ``_auto_commit_accepted`` against a real
parent git repo + sibling staging worktree (reuses the existing Phase-B /
W81 fixture style: real temp git repos, no agents, no worker).
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


_TARGET_REL = "feature_mod.py"
_MODULE_GOOD = '''def feature():
    return "GOOD"
'''
# Whole-file agent output: keeps feature()=="GOOD" so a genuine authored test
# still passes the staged code, but ADDS a top-level symbol so the AST merge
# produces a real (non no-op) diff to commit.
_MODULE_OUTPUT = '''def feature():
    return "GOOD"


def feature_touched():
    return "GOOD"
'''

# Genuine detector: passes on GOOD, fails on the mutant; NO dropped-path dependency.
_TEST_GENUINE = '''from feature_mod import feature


def test_feature_returns_good():
    assert feature() == "GOOD"
'''

# VACUOUS-with-INFRA: test_always_true is vacuous (passes regardless of the
# mutant). test_infra_dependency asserts a samples/ path that EXISTS in the full
# staging baseline but is DROPPED by the mutant copytree -> the mutant rerun
# (and any rerun) fails for an INFRA reason. On HEAD that nonzero exit is misread
# as "mutant caught" -> the vacuous test is accepted.
_TEST_VACUOUS_WITH_INFRA = '''import os


def test_always_true():
    assert True


def test_infra_dependency():
    assert os.path.exists("samples/needed_data.txt")
'''

# Mutant: rewrite GOOD->BAD in the copied tree. A genuine detector catches it;
# the vacuous test does not depend on feature() so the mutant has no effect on it.
_MUTANT_APPLY = (
    'python -c "import pathlib; '
    "p=pathlib.Path('feature_mod.py'); "
    "p.write_text(p.read_text().replace('GOOD','BAD'))\""
)

_TEST_REL = "test_authored_feature.py"
_VCMD = f'python -m pytest -p no:cacheprovider -q {_TEST_REL}'


def _make_parent(tmp_path: Path, *, module_src: str, test_src: str | None):
    """Parent git repo with the target module (+ optional authored test)
    committed, plus a state_dir with output/ + tasks/processed/. Returns
    (state_dir, worktree)."""
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


def _make_parent_with_infra(tmp_path: Path, *, module_src: str, test_src: str):
    """As _make_parent, plus a committed samples/needed_data.txt so the path is
    present in the full staging baseline but dropped by the mutant copytree."""
    state_dir, worktree = _make_parent(tmp_path, module_src=module_src, test_src=test_src)
    samples_dir = worktree / "samples"
    samples_dir.mkdir()
    (samples_dir / "needed_data.txt").write_text("some data", encoding="utf-8")
    _git(worktree, "add", "samples/needed_data.txt")
    _git(worktree, "commit", "-q", "-m", "add infra dependency")
    return state_dir, worktree


# ---------------------------------------------------------------------------
# (A) GENUINE DETECTOR -> gate ACCEPTS  (positive control; passes pre+post)
# ---------------------------------------------------------------------------
def test_phase_b_genuine_detector_accepts(tmp_path):
    """A genuine detector (no dropped-path dependency) catches the mutant and is
    ACCEPTED. Non-vacuity guard: a fix that simply rejects everything (or that
    treats every mutant-rerun failure as infra) would fail this control."""
    state_dir, worktree = _make_parent(tmp_path, module_src=_MODULE_GOOD, test_src=_TEST_GENUINE)

    task_id = "PHASE_MUTMASK_GENUINE"
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
    assert [r for r in rows if r.get("event") in ("mutation_gate_failed", "mutation_gate_error")] == [], (
        "a genuine detector must NOT emit mutation_gate_failed/error"
    )


# ---------------------------------------------------------------------------
# (B) VACUOUS TEST WITH INFRA FAILURE -> gate REJECTS  (THE fail-then-pass)
# ---------------------------------------------------------------------------
def test_phase_b_vacuous_test_infra_rejected(tmp_path):
    """A VACUOUS test whose authored test ALSO touches samples/ (dropped by the
    mutant copytree). On HEAD the mutant rerun fails for the INFRA reason and is
    misread as a mutant catch -> the vacuous test is ACCEPTED (RED here). After
    the baseline-in-copy fix the gate detects the copy environment is broken and
    rejects fail-closed with mutation_gate_error (GREEN)."""
    state_dir, worktree = _make_parent_with_infra(
        tmp_path, module_src=_MODULE_GOOD, test_src=_TEST_VACUOUS_WITH_INFRA
    )
    parent_head_before = _git(worktree, "rev-parse", "HEAD").stdout.strip()

    task_id = "PHASE_MUTMASK_VACUOUS_INFRA"
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
        "vacuous test whose mutant rerun fails for an INFRA reason (dropped path) "
        "must be REJECTED, not credited as a mutant catch"
    )

    rows = _read_rows(state_dir / "impl_progress.jsonl")
    err_rows = [r for r in rows if r.get("event") == "mutation_gate_error"]
    assert len(err_rows) >= 1, f"expected a mutation_gate_error rejected row; rows={rows}"
    assert err_rows[0]["phase"] == "rejected"
    assert [r for r in rows if r.get("event") == "auto_commit"] == [], (
        "an infra-masked vacuous accept must NOT emit an auto_commit accepted row"
    )

    # The staging change must NOT have merged to the parent.
    parent_head_after = _git(worktree, "rev-parse", "HEAD").stdout.strip()
    assert parent_head_after == parent_head_before, (
        "parent HEAD must be unchanged: a rejected accept must not merge to parent"
    )
    assert (worktree / _TARGET_REL).read_text(encoding="utf-8") == _MODULE_GOOD, (
        "parent target file must be untouched on a gate rejection"
    )
