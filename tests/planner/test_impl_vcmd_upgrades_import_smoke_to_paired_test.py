"""Oracle for defect A.2 — planner ignores the brief's pytest verification_command.

DEFECT (RED on HEAD): ``_sanitize_impl_verification_commands`` only rewrites an
impl task's ``verification_command`` when that command ALREADY references a
sibling oracle file (its line-234 ``if not any(of in vcmd for of in
oracle_files): continue`` guard). For a new-module / harness_self_fix leaf the
blind-drafted impl frequently emits a WEAK ``python -c "import <module>"``
import-smoke that names NO oracle file, so the guard short-circuits and the weak
smoke survives — even when a PAIRED COMMITTED regression test
(``tests/**/test_<leaf>.py``) exists on disk under ``repo_root``. The buggy-but-
importable module then ACCEPTs against a vacuous import, which is the fuel for
the A.1 dep-gate leak.

INTENDED (GREEN after fix): when an impl task's command is an import-smoke (or
otherwise does not name a real pytest oracle) and a paired committed
``tests/**/test_<leaf>.py`` exists for one of its touched modules under
``repo_root``, the pass MUST upgrade the command to
``python -m pytest <existing test(s)> -q`` — regardless of whether the original
command referenced an oracle file. A genuinely brand-new module with no paired
test still falls back to the import smoke (nothing to regress yet), and
``repo_root=None`` stays a pure smoke check (backward compatible).

All cases use a HERMETIC fake repo under tmp_path — no dependency on the real
repository tree, no LLM, exercising only the deterministic post-processing
function ``normalize_plan`` / ``_sanitize_impl_verification_commands``.
"""
import copy

import pytest

from harness.planner.plan_normalizer import normalize_plan


ORACLE_TEST_FILE = "tests/pkg/test_widget_oracle.py"


def _impl_task(task_id, meta, files_touched, verification_command):
    return {
        "task_id": task_id,
        "title": "impl " + task_id,
        "meta_task_type": meta,
        "dependencies": [],
        "files_touched": list(files_touched),
        "verification_command": verification_command,
    }


def _oracle_task(task_id, files_touched, mutation_target):
    return {
        "task_id": task_id,
        "title": "oracle " + task_id,
        "meta_task_type": "test_authoring",
        "dependencies": [],
        "files_touched": list(files_touched),
        "mutation_target": mutation_target,
        "verification_command": "python -m pytest %s -q" % files_touched[0],
    }


def _plan(*tasks):
    return {"tasks": [copy.deepcopy(t) for t in tasks]}


def _task_by_id(plan, task_id):
    for task in plan["tasks"]:
        if task["task_id"] == task_id:
            return task
    raise AssertionError(
        "task %r not in %r" % (task_id, [t["task_id"] for t in plan["tasks"]])
    )


def _make_repo(tmp_path, existing_tests):
    for rel in existing_tests:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")
    return tmp_path


def test_import_smoke_impl_upgraded_to_paired_committed_test(tmp_path):
    """A.2 core: a new-module impl whose vcmd is a WEAK import-smoke (naming no
    oracle file) is upgraded to run the PAIRED COMMITTED test_<leaf>.py that
    exists under repo_root — proving the impl is gated on its real oracle, not a
    vacuous import.

    RED on HEAD: the line-234 oracle-reference guard makes the pass a no-op for an
    import-smoke command, so the weak smoke survives.
    """
    repo = _make_repo(tmp_path, ["tests/pkg/test_widget.py"])
    impl = _impl_task(
        "widget-impl",
        "data_model",
        ["pkg/widget.py"],
        'python -c "import pkg.widget"',  # WEAK import-smoke, names no oracle file
    )
    oracle = _oracle_task("widget-oracle", [ORACLE_TEST_FILE], "pkg.widget")
    plan = _plan(impl, oracle)

    result = normalize_plan(plan, repo_root=repo)

    vc = _task_by_id(result, "widget-impl")["verification_command"]
    assert "pytest" in vc, (
        "impl import-smoke must be upgraded to a pytest run of the paired "
        "committed test, got %r" % vc
    )
    assert "tests/pkg/test_widget.py" in vc, (
        "must run the real paired regression test, got %r" % vc
    )
    assert not vc.strip().startswith('python -c'), (
        "must NOT remain a vacuous import-smoke, got %r" % vc
    )


def test_harness_self_fix_import_smoke_upgraded_to_paired_test(tmp_path):
    """Same defect under the harness_self_fix meta_task_type: an internal self-fix
    leaf whose impl carries an import-smoke is upgraded to the paired committed
    test. RED on HEAD for the same line-234 guard reason."""
    repo = _make_repo(tmp_path, ["tests/harness/test_thing.py"])
    impl = _impl_task(
        "selffix-impl",
        "harness_self_fix",
        ["harness/thing.py"],
        'python -c "import harness.thing"',
    )
    oracle = _oracle_task("selffix-oracle", [ORACLE_TEST_FILE], "harness.thing")
    plan = _plan(impl, oracle)

    result = normalize_plan(plan, repo_root=repo)

    vc = _task_by_id(result, "selffix-impl")["verification_command"]
    assert "pytest" in vc and "tests/harness/test_thing.py" in vc, (
        "harness_self_fix impl must be gated on its paired committed test, got %r"
        % vc
    )
    assert not vc.strip().startswith('python -c'), repr(vc)


def test_brand_new_module_with_no_paired_test_stays_import_smoke(tmp_path):
    """A genuinely brand-new module with NO paired committed test still falls back
    to the import smoke (nothing to regress yet). Stays GREEN before and after the
    fix — guards against over-correction."""
    repo = _make_repo(tmp_path, [])  # no test files
    impl = _impl_task(
        "fresh-impl",
        "data_model",
        ["pkg/fresh_module.py"],
        'python -c "import pkg.fresh_module"',
    )
    oracle = _oracle_task("fresh-oracle", [ORACLE_TEST_FILE], "pkg.fresh_module")
    plan = _plan(impl, oracle)

    result = normalize_plan(plan, repo_root=repo)
    vc = _task_by_id(result, "fresh-impl")["verification_command"]
    assert vc == 'python -c "import pkg.fresh_module"', repr(vc)


def test_repo_root_none_stays_import_smoke_backward_compatible(tmp_path):
    """With repo_root omitted the pass cannot resolve on-disk tests and keeps the
    pure import-smoke behaviour. Backward-compatible / GREEN both sides."""
    impl = _impl_task(
        "compat-impl",
        "data_model",
        ["pkg/compat_module.py"],
        'python -c "import pkg.compat_module"',
    )
    oracle = _oracle_task("compat-oracle", [ORACLE_TEST_FILE], "pkg.compat_module")
    plan = _plan(impl, oracle)

    result = normalize_plan(plan)  # no repo_root
    vc = _task_by_id(result, "compat-impl")["verification_command"]
    assert vc == 'python -c "import pkg.compat_module"', repr(vc)


def test_idempotent_after_upgrade(tmp_path):
    """Applying normalize_plan twice yields the same plan once the impl has been
    upgraded to the paired test."""
    repo = _make_repo(tmp_path, ["tests/pkg/test_widget.py"])
    impl = _impl_task(
        "w", "data_model", ["pkg/widget.py"], 'python -c "import pkg.widget"'
    )
    oracle = _oracle_task("o", [ORACLE_TEST_FILE], "pkg.widget")
    plan = _plan(impl, oracle)

    once = normalize_plan(plan, repo_root=repo)
    twice = normalize_plan(copy.deepcopy(once), repo_root=repo)
    assert twice == once


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
