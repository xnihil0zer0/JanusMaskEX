"""Hermetic, in-memory oracle for the verification_command sanitize pass in
``harness.planner.plan_normalizer.normalize_plan``.

This file pins the observable behaviour of the sanitize pass described in the
spec, over hand-built plan dicts with ZERO I/O (no filesystem, no subprocess,
no network, no fixtures):

  * an impl task whose ``verification_command`` references a sibling oracle's
    test file is rewritten to ``python -c "import <module>"`` derived from the
    impl's own importable target;
  * an impl whose ``verification_command`` references no oracle path is left
    byte-identical (no-op);
  * a ``test_authoring`` task's ``verification_command`` is never touched;
  * the pass is idempotent: applying it twice equals applying it once;
  * the fallback strips only the oracle tokens when the impl has no importable
    target, and leaves the command unchanged when nothing meaningful remains.

The worked failure example from the brief is the ``fp-status`` plan: impl
``fp-status-impl`` touches ``harness/brief_status.py`` with a vcmd that runs the
sibling oracle's file ``tests/harness/test_failure_propagation_status.py``,
authored by the ``test_authoring`` task ``fp-status-oracle-test``.
"""

import copy

import pytest

from harness.planner.plan_normalizer import normalize_plan


# ---------------------------------------------------------------------------
# In-memory plan/task builders -- every datum is a literal; nothing touches disk
# ---------------------------------------------------------------------------

# The sibling oracle's test file used throughout the worked example.
ORACLE_TEST_FILE = "tests/harness/test_failure_propagation_status.py"


def _impl_task(task_id, files_touched, verification_command):
    """Build a plain implementation task dict (NOT a test_authoring task)."""
    return {
        "task_id": task_id,
        "title": "impl " + task_id,
        "meta_task_type": "implementation",
        "dependencies": [],
        "files_touched": list(files_touched),
        "verification_command": verification_command,
    }


def _oracle_task(task_id, files_touched, verification_command):
    """Build a test_authoring (oracle) task dict touching its own test file."""
    return {
        "task_id": task_id,
        "title": "oracle " + task_id,
        "meta_task_type": "test_authoring",
        "dependencies": [],
        "files_touched": list(files_touched),
        "verification_command": verification_command,
    }


def _plan(*tasks):
    return {"tasks": [copy.deepcopy(t) for t in tasks]}


def _task_by_id(plan, task_id):
    for task in plan["tasks"]:
        if task["task_id"] == task_id:
            return task
    raise AssertionError(
        "task %r not present in normalized plan: %r"
        % (task_id, [t["task_id"] for t in plan["tasks"]])
    )


def _fp_status_plan():
    """The canonical worked failure example from the brief."""
    impl = _impl_task(
        "fp-status-impl",
        ["harness/brief_status.py"],
        "python -m pytest %s -q" % ORACLE_TEST_FILE,
    )
    oracle = _oracle_task(
        "fp-status-oracle-test",
        [ORACLE_TEST_FILE],
        "python -m pytest %s -q" % ORACLE_TEST_FILE,
    )
    return _plan(impl, oracle)


# ---------------------------------------------------------------------------
# unit_tests
# ---------------------------------------------------------------------------

def test_impl_vcmd_referencing_oracle_rewritten_to_import_module():
    """An impl vcmd that runs a sibling oracle's file is rewritten to an
    `import` smoke check derived from the impl's own importable target."""
    plan = _fp_status_plan()

    result = normalize_plan(copy.deepcopy(plan))

    impl = _task_by_id(result, "fp-status-impl")
    assert impl["verification_command"] == 'python -c "import harness.brief_status"'
    # The oracle path must no longer be referenced by the rewritten impl.
    assert ORACLE_TEST_FILE not in impl["verification_command"]


def test_impl_vcmd_without_oracle_reference_unchanged_byte_identical():
    """An impl whose vcmd references no ORACLE_FILES path is byte-identical."""
    # The impl runs a test file that is NOT authored by any test_authoring task,
    # so it is not an oracle reference and must be left untouched.
    non_oracle_vcmd = "python -m pytest tests/harness/test_unrelated_thing.py -q"
    impl = _impl_task("clean-impl", ["harness/clean_module.py"], non_oracle_vcmd)
    oracle = _oracle_task(
        "some-oracle", [ORACLE_TEST_FILE], "python -m pytest %s -q" % ORACLE_TEST_FILE
    )
    plan = _plan(impl, oracle)
    original_impl = copy.deepcopy(impl)

    result = normalize_plan(copy.deepcopy(plan))

    got = _task_by_id(result, "clean-impl")
    assert got["verification_command"] == non_oracle_vcmd
    # The whole impl task is returned byte-identical, not just the vcmd.
    assert got == original_impl


def test_test_authoring_vcmd_never_touched():
    """A test_authoring task legitimately runs its own file; even though that
    file IS an oracle path, the sanitize pass must never rewrite it."""
    plan = _fp_status_plan()
    original_oracle_vcmd = _task_by_id(plan, "fp-status-oracle-test")[
        "verification_command"
    ]

    result = normalize_plan(copy.deepcopy(plan))

    oracle = _task_by_id(result, "fp-status-oracle-test")
    assert oracle["verification_command"] == original_oracle_vcmd
    assert oracle["verification_command"] == "python -m pytest %s -q" % ORACLE_TEST_FILE


def test_normalize_plan_idempotent_twice_equals_once():
    """normalize_plan(normalize_plan(plan)) == normalize_plan(plan)."""
    plan = _fp_status_plan()

    once = normalize_plan(copy.deepcopy(plan))
    twice = normalize_plan(copy.deepcopy(once))

    assert twice == once
    # And the stable form is the rewritten one (idempotency is non-trivial here).
    assert (
        _task_by_id(once, "fp-status-impl")["verification_command"]
        == 'python -c "import harness.brief_status"'
    )


def test_fallback_strips_oracle_tokens_or_leaves_unchanged():
    """Impl with no importable .py target outside tests/: the oracle tokens are
    stripped while remaining tokens are preserved; and the command is left
    unchanged when nothing meaningful would remain after stripping."""
    oracle = _oracle_task(
        "fb-oracle", [ORACLE_TEST_FILE], "python -m pytest %s -q" % ORACLE_TEST_FILE
    )

    # Case A: impl touches only a non-importable file (a doc) -> no import is
    # derivable, so the oracle token is removed while the OTHER meaningful
    # token (a real, non-oracle test file) survives.
    other_test = "tests/harness/test_other_real.py"
    impl_a = _impl_task(
        "fb-impl-strip",
        ["docs/design_notes.md"],
        "python -m pytest %s %s -q" % (other_test, ORACLE_TEST_FILE),
    )
    # Case B: the vcmd is *only* boilerplate plus the oracle reference, so
    # stripping the oracle leaves nothing meaningful -> the command is left
    # unchanged (never a bare ``pytest`` that would run the whole suite).
    impl_b = _impl_task(
        "fb-impl-keep",
        ["docs/design_notes.md"],
        "python -m pytest %s -q" % ORACLE_TEST_FILE,
    )

    plan = _plan(impl_a, impl_b, oracle)
    result = normalize_plan(copy.deepcopy(plan))

    stripped = _task_by_id(result, "fb-impl-strip")["verification_command"]
    assert ORACLE_TEST_FILE not in stripped  # oracle token removed
    assert other_test in stripped  # the other meaningful token survives
    assert "pytest" in stripped  # remaining boilerplate preserved
    assert "python" in stripped
    # Not rewritten into an import (no importable target existed).
    assert "import" not in stripped

    kept = _task_by_id(result, "fb-impl-keep")["verification_command"]
    # Nothing meaningful remained after stripping -> left unchanged.
    assert kept == "python -m pytest %s -q" % ORACLE_TEST_FILE
    assert ORACLE_TEST_FILE in kept


# ---------------------------------------------------------------------------
# property_tests
# ---------------------------------------------------------------------------

def test_idempotency_property_over_repeated_normalization():
    """Repeated normalization reaches a fixed point after the first pass for a
    variety of plans (rewrite, no-op, fallback, oracle-only)."""
    plans = [
        _fp_status_plan(),
        _plan(
            _impl_task(
                "noref", ["pkg/mod.py"], "python -m pytest tests/test_other.py -q"
            )
        ),
        _plan(
            _impl_task("fb", ["docs/x.md"], "python -m pytest %s" % ORACLE_TEST_FILE),
            _oracle_task("orc", [ORACLE_TEST_FILE], "python -m pytest %s" % ORACLE_TEST_FILE),
        ),
    ]
    for plan in plans:
        first = normalize_plan(copy.deepcopy(plan))
        second = normalize_plan(copy.deepcopy(first))
        third = normalize_plan(copy.deepcopy(second))
        assert second == first
        assert third == first


def test_noop_property_when_no_oracle_reference_present():
    """With no test_authoring tasks (ORACLE_FILES empty), normalize_plan is a
    complete no-op on impl verification_commands."""
    impl1 = _impl_task(
        "i1", ["pkg/a.py"], "python -m pytest tests/pkg/test_a.py -q"
    )
    impl2 = _impl_task("i2", ["pkg/b.py"], 'python -c "import pkg.b"')
    plan = _plan(impl1, impl2)
    original = copy.deepcopy(plan)

    result = normalize_plan(copy.deepcopy(plan))

    for task in (impl1, impl2):
        got = _task_by_id(result, task["task_id"])
        assert got["verification_command"] == task["verification_command"]
    # Every impl vcmd is preserved exactly.
    assert [t["verification_command"] for t in result["tasks"]] == [
        t["verification_command"] for t in original["tasks"]
    ]


# ---------------------------------------------------------------------------
# regression_tests
# ---------------------------------------------------------------------------

def test_worked_failure_example_fp_status_impl_rewritten():
    """End-to-end pin of the brief's worked example plan."""
    plan = _fp_status_plan()

    result = normalize_plan(copy.deepcopy(plan))

    impl = _task_by_id(result, "fp-status-impl")
    oracle = _task_by_id(result, "fp-status-oracle-test")
    assert impl["verification_command"] == 'python -c "import harness.brief_status"'
    # The oracle task that authored the test file is untouched.
    assert oracle["verification_command"] == "python -m pytest %s -q" % ORACLE_TEST_FILE


def test_non_referencing_fields_and_task_order_preserved():
    """Sanitize only mutates the impl verification_command; every other field
    and the task ordering are preserved."""
    plan = _fp_status_plan()
    original = copy.deepcopy(plan)

    result = normalize_plan(copy.deepcopy(plan))

    # Task order preserved.
    assert [t["task_id"] for t in result["tasks"]] == [
        t["task_id"] for t in original["tasks"]
    ]
    impl = _task_by_id(result, "fp-status-impl")
    orig_impl = _task_by_id(original, "fp-status-impl")
    for field in ("task_id", "title", "meta_task_type", "dependencies", "files_touched"):
        assert impl[field] == orig_impl[field]


def test_multiple_importable_targets_imported_comma_separated():
    """After the _split_multifile_module_tasks pass, an impl that creates
    multiple NEW modules is split into one task per module (the old
    comma-separated single-task vcmd no longer applies to new-module impls).
    Each split task gets its OWN single-module import vcmd, in files_touched
    order; the non-importable test file under tests/ is not a created module and
    is dropped, and the oracle reference is gone."""
    impl = _impl_task(
        "multi-impl",
        ["pkg/alpha.py", "tests/pkg/test_alpha.py", "pkg/beta.py"],
        "python -m pytest -q %s --maxfail=1" % ORACLE_TEST_FILE,
    )
    oracle = _oracle_task(
        "multi-oracle", [ORACLE_TEST_FILE], "python -m pytest %s -q" % ORACLE_TEST_FILE
    )
    plan = _plan(impl, oracle)

    result = normalize_plan(copy.deepcopy(plan))

    a = _task_by_id(result, "multi-impl__alpha")
    b = _task_by_id(result, "multi-impl__beta")
    assert a["files_touched"] == ["pkg/alpha.py"]
    assert b["files_touched"] == ["pkg/beta.py"]
    # each split gets its own single-module import vcmd
    assert a["verification_command"].startswith('python -c "import ')
    assert "pkg.alpha" in a["verification_command"]
    assert "pkg.beta" in b["verification_command"]
    # the test file and oracle reference are excluded from both
    for vc in (a["verification_command"], b["verification_command"]):
        assert "tests" not in vc and "test_alpha" not in vc
        assert ORACLE_TEST_FILE not in vc
    # order preserved: alpha task before beta task
    ids = [t["task_id"] for t in result["tasks"]]
    assert ids.index("multi-impl__alpha") < ids.index("multi-impl__beta")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
