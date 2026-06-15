"""Bootstrap RED oracle — factory acceptance of a NEW-MODULE RED-by-absence oracle.

Pins G-NEW-MODULE-ORACLE: a ``meta_task_type == 'test_authoring'`` accept whose
``mutation_target`` names a module that DOES NOT EXIST on disk yet (the TDD
"author the RED oracle before the module is built" case) must be ACCEPTED by
``harness.orchestrator._auto_commit_accepted`` when the authored oracle is
RED-BY-ABSENCE -- i.e. it imports the target module and its verification_command
fails specifically with ModuleNotFoundError / ImportError / AttributeError
referencing the target. For such a task the vcmd-exit-0 gate and the mutant
non-vacuity gate are INAPPLICABLE (you cannot make a test pass against, nor
mutate, a module that does not exist), so they must be bypassed for this case
ONLY -- the oracle's non-vacuity is established by construction (it cannot pass
without the real module).

This is the ONE hand-committed bootstrap oracle that breaks the catch-22: the
factory cannot author a RED oracle until this fix lands, and this fix's own
oracle is RED on HEAD. After it lands, the factory authors new-module RED
oracles itself.

Driven END-TO-END through the REAL ``_auto_commit_accepted`` against a real
parent git repo + sibling staging worktree (real temp git repos, no agents, no
worker), mirroring tests/adversarial/test_phase_b_mutation_gate_adversarial.py.

HEAD MATRIX (fix absent on HEAD):
  (A) new-module RED-by-absence oracle -> ACCEPT
        RED on HEAD: the vcmd fails (ModuleNotFoundError) -> verification_failed
        -> rejected. GREEN post-fix: accepted via the new-module-oracle branch.
  (B) absent module, failure NOT absence-of-target (vacuous/unrelated) -> REJECT
        GREEN on HEAD and post-fix (narrowness guard: the branch must not
        blanket-accept any failing test_authoring).
  (C) EXISTING module + RED oracle -> REJECT
        GREEN on HEAD and post-fix (the fix must NOT broadly accept RED oracles
        for modules that DO exist -- those still owe a green vcmd + mutant gate).
"""
from __future__ import annotations

import json
import os
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


# The target module is NEVER created in the parent/worktree for cases (A)/(B):
# importing it raises ModuleNotFoundError, which is the whole point.
_ABSENT_TARGET = "newpkg.newmod"
_ABSENT_TEST_REL = "test_newmod.py"

# (A) A genuine RED-by-absence oracle: imports the absent target and makes a real
# assertion about its contract. Cannot pass without the real module.
_ORACLE_RED_BY_ABSENCE = '''from newpkg.newmod import compute


def test_compute_returns_marker():
    assert compute("payload") == "MARKER"
'''

# (B) An oracle whose vcmd fails for an UNRELATED reason (it never imports the
# target, so its failure is NOT "the target module is absent"). Must stay
# rejected -- the new-module branch is for RED-by-absence ONLY.
_ORACLE_UNRELATED_FAIL = '''def test_unrelated():
    assert 1 == 2
'''

# (C) An EXISTING module + a RED oracle that asserts the wrong thing. Because the
# module exists, the new-module branch must NOT trigger; the normal vcmd gate
# must still reject it.
_EXISTING_MODULE_REL = "feature_mod.py"
_EXISTING_MODULE_SRC = '''def feature():
    return "GOOD"
'''
_EXISTING_TEST_REL = "test_feature.py"
_ORACLE_EXISTING_RED = '''from feature_mod import feature


def test_feature_wrong():
    assert feature() == "WRONG"
'''


def _vcmd(test_rel: str) -> str:
    return f"python -m pytest -p no:cacheprovider -q {test_rel}"


def _make_parent(tmp_path: Path, *, extra_committed: dict[str, str] | None = None):
    """Parent git repo with a placeholder commit (so a tree exists) + a state_dir
    with output/ and tasks/processed/. ``extra_committed`` maps rel-path -> source
    for any files that should pre-exist in the worktree (e.g. an EXISTING module
    for case C). The new-module target is deliberately NOT created.

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
    (worktree / "README.md").write_text("placeholder\n", encoding="utf-8")
    _git(worktree, "add", "README.md")
    for rel, src in (extra_committed or {}).items():
        (worktree / rel).write_text(src, encoding="utf-8")
        _git(worktree, "add", rel)
    _git(worktree, "commit", "-q", "-m", "initial")
    return state_dir, worktree


# ---------------------------------------------------------------------------
# (A) NEW-MODULE RED-BY-ABSENCE ORACLE -> ACCEPT  (THE discriminating fail-then-pass)
# ---------------------------------------------------------------------------
def test_new_module_red_by_absence_oracle_is_accepted(tmp_path):
    state_dir, _ = _make_parent(tmp_path)
    task_id = "NEWMOD_RED_OK"
    (state_dir / "output" / f"{task_id}.py").write_text(_ORACLE_RED_BY_ABSENCE, encoding="utf-8")
    task = {
        "task_id": task_id,
        "meta_task_type": "test_authoring",
        "files_touched": [_ABSENT_TEST_REL],
        "mutation_target": _ABSENT_TARGET,
        "verification_command": _vcmd(_ABSENT_TEST_REL),
    }

    committed = _auto_commit_accepted(state_dir, task, task_id)
    assert committed is True, (
        "a RED-by-absence test_authoring oracle for a not-yet-built module must be accepted"
    )

    rows = _read_rows(state_dir / "impl_progress.jsonl")
    accepted = [r for r in rows if r.get("event") == "auto_commit"]
    assert len(accepted) == 1, f"expected one accepted row, got {accepted}"
    assert accepted[0]["phase"] == "accepted"
    assert [r for r in rows if r.get("event") == "verification_failed"] == [], (
        "a RED-by-absence new-module oracle must NOT be rejected as verification_failed"
    )
    assert [r for r in rows if str(r.get("event", "")).startswith("mutation_gate")] == [], (
        "the mutant gate is inapplicable to an absent module and must be skipped"
    )


# ---------------------------------------------------------------------------
# (B) ABSENT MODULE, FAILURE NOT ABSENCE-OF-TARGET -> REJECT  (narrowness guard)
# ---------------------------------------------------------------------------
def test_absent_module_but_unrelated_failure_is_rejected(tmp_path):
    state_dir, _ = _make_parent(tmp_path)
    task_id = "NEWMOD_UNRELATED"
    (state_dir / "output" / f"{task_id}.py").write_text(_ORACLE_UNRELATED_FAIL, encoding="utf-8")
    task = {
        "task_id": task_id,
        "meta_task_type": "test_authoring",
        "files_touched": [_ABSENT_TEST_REL],
        "mutation_target": _ABSENT_TARGET,
        "verification_command": _vcmd(_ABSENT_TEST_REL),
    }

    committed = _auto_commit_accepted(state_dir, task, task_id)
    assert committed is False, (
        "an oracle that fails for a reason OTHER than the target module being "
        "absent must NOT be accepted by the new-module branch"
    )


# ---------------------------------------------------------------------------
# (C) EXISTING MODULE + RED ORACLE -> REJECT  (must not broadly accept RED)
# ---------------------------------------------------------------------------
def test_existing_module_red_oracle_still_rejected(tmp_path):
    state_dir, _ = _make_parent(tmp_path, extra_committed={_EXISTING_MODULE_REL: _EXISTING_MODULE_SRC})
    task_id = "EXISTING_RED"
    (state_dir / "output" / f"{task_id}.py").write_text(_ORACLE_EXISTING_RED, encoding="utf-8")
    task = {
        "task_id": task_id,
        "meta_task_type": "test_authoring",
        "files_touched": [_EXISTING_TEST_REL],
        "mutation_target": "feature_mod",
        "verification_command": _vcmd(_EXISTING_TEST_REL),
    }

    committed = _auto_commit_accepted(state_dir, task, task_id)
    assert committed is False, (
        "a RED oracle whose target module EXISTS must still be rejected -- the fix "
        "is narrowly scoped to absent-module RED-by-absence, not all RED oracles"
    )
