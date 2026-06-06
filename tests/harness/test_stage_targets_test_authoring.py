"""FIX #1 oracle (RED) — _stage_targets mounts the module-under-test for a
test_authoring task.

THE GAP (proven across 3 daemon runs): the autowork daemon lands implementations
hands-off but CANNOT synthesize PASSING ``test_authoring`` oracles, because the
oracle-authoring worker never sees the source of the thing it is testing. For a
test_authoring task ``files_touched`` is the brand-NEW test file (doesn't exist →
nothing copied) and the MODULE UNDER TEST is not in ``files_touched`` → it is
never mounted into the jail. The worker then guesses the interface from prose and
gets ``reject_rollback`` on the non-vacuity mutation gate.

THE FIX (PART 1, this oracle): ``_stage_targets`` must, for a ``test_authoring``
task, ALSO resolve the task's ``mutation_target`` (a bare dotted module the
planner already emits for test_authoring tasks) to a repo-relative ``.py`` path
and copy that source into ``inbox/targets/<rel>`` alongside ``files_touched`` —
using the same containment guard, is_file skip, and best-effort copy as the
existing loop.

  P1 — a test_authoring task with mutation_target='pkg.foo' stages pkg/foo.py
       into inbox/targets/ with the module's REAL content (content-equality, not
       mere existence → non-vacuous); the brand-new test file is NOT staged.
  N1 (negative control) — a NON-test_authoring task does NOT stage its
       mutation_target (the staging is gated on meta_task_type == test_authoring).
  N2 — a test_authoring task with no mutation_target is a no-op for module staging
       and never raises.
  C1 — double-stage guard: a mutation_target that is also in files_touched is
       copied once with correct content and never raises.

Pure filesystem; no agy/claude spawned. Mirrors the repo/state fixture of
tests/adversarial/test_stage_targets_escape.py (repo_root = state_dir.parent).
"""
from __future__ import annotations

import json

import pytest

import harness.orchestrator as orch


MODULE_SRC = (
    "def real_signature(repo_root, state_dir, config):\n"
    "    '''A disk-reading interface the worker could never guess from prose.'''\n"
    "    return (repo_root, state_dir, config)\n"
)


@pytest.fixture
def repo(tmp_path):
    """A tmp 'repo' whose state_dir is repo/state (repo_root = state.parent)."""
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "state").mkdir(parents=True)
    (repo / "pkg" / "foo.py").write_text(MODULE_SRC, encoding="utf-8")
    (repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    return repo


def _run(repo, inbox_name, task):
    """Stage ``task`` and invoke _stage_targets; return the inbox/targets dir."""
    state_dir = repo / "state"
    inbox = repo / inbox_name / "inbox"
    inbox.mkdir(parents=True)
    task_json = inbox / "task.json"
    task_json.write_text(json.dumps(task), encoding="utf-8")
    orch._stage_targets(inbox, state_dir, task_json)  # must never raise
    return inbox / "targets"


def test_P1_test_authoring_stages_module_under_test(repo):
    """The module named by mutation_target is mounted with its real source."""
    task = {
        "task_id": "ta1",
        "meta_task_type": "test_authoring",
        "mutation_target": "pkg.foo",
        "files_touched": ["tests/test_foo.py"],  # brand-new → does not exist
    }
    targets = _run(repo, "wd1", task)

    staged = targets / "pkg" / "foo.py"
    assert staged.is_file(), "module-under-test must be staged for a test_authoring task"
    # Non-vacuous: the staged content is the REAL source, not an empty/placeholder file.
    assert staged.read_text(encoding="utf-8") == MODULE_SRC
    # The brand-new test file does not exist yet → must NOT be staged.
    assert not (targets / "tests" / "test_foo.py").exists()


def test_N1_non_test_authoring_does_not_stage_mutation_target(repo):
    """Negative control: staging the mutation_target is gated on test_authoring."""
    task = {
        "task_id": "imp1",
        "meta_task_type": "harness_self_fix",
        "mutation_target": "pkg.foo",
        "files_touched": ["tests/test_foo.py"],  # NOT pkg/foo.py
    }
    targets = _run(repo, "wd2", task)
    assert not (targets / "pkg" / "foo.py").exists(), (
        "a non-test_authoring task must not stage its mutation_target"
    )


def test_N2_test_authoring_without_mutation_target_is_noop(repo):
    """No mutation_target → no extra module staging, no crash."""
    task = {
        "task_id": "ta2",
        "meta_task_type": "test_authoring",
        "files_touched": ["tests/test_foo.py"],
    }
    targets = _run(repo, "wd3", task)
    # Nothing to stage (files_touched is a brand-new file; no mutation_target).
    assert not (targets / "pkg" / "foo.py").exists()


def test_C1_double_stage_guard(repo):
    """mutation_target also present in files_touched → copied once, no crash."""
    task = {
        "task_id": "ta3",
        "meta_task_type": "test_authoring",
        "mutation_target": "pkg.foo",
        "files_touched": ["pkg/foo.py"],  # already in files_touched
    }
    targets = _run(repo, "wd4", task)
    staged = targets / "pkg" / "foo.py"
    assert staged.is_file()
    assert staged.read_text(encoding="utf-8") == MODULE_SRC
