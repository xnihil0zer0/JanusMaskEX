"""Oracle for the repo-aware hardening of the normalizer's vcmd-sanitize pass.

RED on HEAD: ``normalize_plan`` takes no ``repo_root`` argument, so calling it
with ``repo_root=`` raises TypeError (or, if later it accepts but ignores the
arg, the impl vcmd is rewritten to a bare ``python -c "import ..."`` smoke check
instead of a pytest run of the EXISTING regression test for the touched module).

GREEN after the hardening: ``normalize_plan(plan, repo_root=<repo>)`` rewrites an
impl task's ``verification_command`` that references a sibling oracle's (not-yet-
landed) test file into a pytest run of the EXISTING ``tests/**/test_<leaf>.py``
files for the impl's touched modules — so a behaviour-breaking impl is caught by
real regression tests rather than passing a vacuous import. When no existing test
file is found (a brand-new module), it falls back to the import smoke check; with
``repo_root=None`` it stays a smoke check (pure, backward-compatible).

All cases use a HERMETIC fake repo under tmp_path — no dependency on the real
repository tree.
"""
import copy

import pytest

from harness.planner.plan_normalizer import normalize_plan


ORACLE_TEST_FILE = "tests/pkg/test_widget_oracle.py"


def _impl_task(task_id, files_touched, verification_command):
    return {
        "task_id": task_id,
        "title": "impl " + task_id,
        "meta_task_type": "implementation",
        "dependencies": [],
        "files_touched": list(files_touched),
        "verification_command": verification_command,
    }


def _oracle_task(task_id, files_touched, verification_command):
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
    raise AssertionError("task %r not in %r" % (task_id, [t["task_id"] for t in plan["tasks"]]))


def _make_repo(tmp_path, existing_tests):
    """Create a fake repo root with the given existing test files (rel paths)."""
    for rel in existing_tests:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")
    return tmp_path


def test_impl_vcmd_rewritten_to_existing_regression_test(tmp_path):
    """An impl whose vcmd runs the sibling oracle file is rewritten to run the
    EXISTING test_<leaf>.py for its touched module, discovered under repo_root."""
    repo = _make_repo(tmp_path, ["tests/pkg/test_widget.py"])
    impl = _impl_task(
        "widget-impl",
        ["pkg/widget.py"],
        "python -m pytest %s -q" % ORACLE_TEST_FILE,
    )
    oracle = _oracle_task("widget-oracle", [ORACLE_TEST_FILE], "python -m pytest %s -q" % ORACLE_TEST_FILE)
    plan = _plan(impl, oracle)

    result = normalize_plan(plan, repo_root=repo)

    vc = _task_by_id(result, "widget-impl")["verification_command"]
    assert "pytest" in vc
    assert "tests/pkg/test_widget.py" in vc  # the real existing regression test
    assert ORACLE_TEST_FILE not in vc  # the not-yet-landed oracle is gone
    assert "import" not in vc  # not a bare smoke import when a real test exists


def test_brand_new_module_with_no_existing_test_falls_back_to_smoke_import(tmp_path):
    """When NO existing test_<leaf>.py is found for the touched module, the pass
    falls back to the import smoke check (nothing to regress yet)."""
    repo = _make_repo(tmp_path, [])  # no test files at all
    impl = _impl_task(
        "fresh-impl",
        ["pkg/fresh_module.py"],
        "python -m pytest %s -q" % ORACLE_TEST_FILE,
    )
    oracle = _oracle_task("fresh-oracle", [ORACLE_TEST_FILE], "python -m pytest %s -q" % ORACLE_TEST_FILE)
    plan = _plan(impl, oracle)

    result = normalize_plan(plan, repo_root=repo)

    vc = _task_by_id(result, "fresh-impl")["verification_command"]
    assert vc == 'python -c "import pkg.fresh_module"'


def test_repo_root_none_is_smoke_import_backward_compatible(tmp_path):
    """With repo_root omitted/None the pass keeps the pure smoke-import behaviour
    (backward compatible with the existing sanitize oracle)."""
    impl = _impl_task(
        "compat-impl",
        ["pkg/compat_module.py"],
        "python -m pytest %s -q" % ORACLE_TEST_FILE,
    )
    oracle = _oracle_task("compat-oracle", [ORACLE_TEST_FILE], "python -m pytest %s -q" % ORACLE_TEST_FILE)
    plan = _plan(impl, oracle)

    result = normalize_plan(plan)  # no repo_root
    vc = _task_by_id(result, "compat-impl")["verification_command"]
    assert vc == 'python -c "import pkg.compat_module"'


def test_existing_oracle_file_is_not_used_as_the_regression_test(tmp_path):
    """The sibling oracle's own test file, even if it already exists under
    repo_root, must NOT be chosen as the impl's regression test (it is the
    not-yet-validated oracle, excluded by path)."""
    # The oracle file leaf is test_widget_oracle.py; create it AND a real
    # regression test for the module. Only the real one may be selected.
    repo = _make_repo(tmp_path, ["tests/pkg/test_widget.py", ORACLE_TEST_FILE])
    impl = _impl_task(
        "widget-impl2",
        ["pkg/widget.py"],
        "python -m pytest %s -q" % ORACLE_TEST_FILE,
    )
    oracle = _oracle_task("widget-oracle2", [ORACLE_TEST_FILE], "python -m pytest %s -q" % ORACLE_TEST_FILE)
    plan = _plan(impl, oracle)

    result = normalize_plan(plan, repo_root=repo)
    vc = _task_by_id(result, "widget-impl2")["verification_command"]
    assert "tests/pkg/test_widget.py" in vc
    assert ORACLE_TEST_FILE not in vc


def test_idempotent_under_repo_root(tmp_path):
    """normalize_plan(normalize_plan(plan, r), r) == normalize_plan(plan, r)."""
    repo = _make_repo(tmp_path, ["tests/pkg/test_widget.py"])
    impl = _impl_task("w", ["pkg/widget.py"], "python -m pytest %s -q" % ORACLE_TEST_FILE)
    oracle = _oracle_task("o", [ORACLE_TEST_FILE], "python -m pytest %s -q" % ORACLE_TEST_FILE)
    plan = _plan(impl, oracle)

    once = normalize_plan(plan, repo_root=repo)
    twice = normalize_plan(copy.deepcopy(once), repo_root=repo)
    assert twice == once
    assert "tests/pkg/test_widget.py" in _task_by_id(once, "w")["verification_command"]


def test_test_authoring_vcmd_never_touched_under_repo_root(tmp_path):
    """A test_authoring task's vcmd legitimately runs its own file and is never
    rewritten, even with repo_root provided."""
    repo = _make_repo(tmp_path, ["tests/pkg/test_widget.py"])
    impl = _impl_task("w", ["pkg/widget.py"], "python -m pytest %s -q" % ORACLE_TEST_FILE)
    oracle = _oracle_task("o", [ORACLE_TEST_FILE], "python -m pytest %s -q" % ORACLE_TEST_FILE)
    plan = _plan(impl, oracle)

    result = normalize_plan(plan, repo_root=repo)
    assert _task_by_id(result, "o")["verification_command"] == "python -m pytest %s -q" % ORACLE_TEST_FILE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
