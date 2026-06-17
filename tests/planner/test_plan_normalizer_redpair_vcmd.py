"""Regression guard for the fix-forward red-pair carve-out in
``_sanitize_impl_verification_commands``.

Bootstrap context: the sanitizer used to rewrite EVERY impl verification_command
that named a sibling oracle's test file (to stop vacuous "impl runs the oracle's
tests" passes). But a legitimate fix-forward red-pair REQUIRES the impl vcmd to
keep naming the oracle's own authored test file -- the runtime acceptance gate
``harness.redpair_acceptance.is_fix_forward_redpair`` re-checks exactly that
(impl.verification_command substring-contains one of the oracle's files_touched,
AND the oracle's mutation_target maps into the impl's files_touched). Rewriting
it at planner time severed that link and the RED oracle was wrongly rejected
(surfaced as auto_commit_failed), or the impl landed vacuously while the oracle
was orphaned. These tests pin the carve-out: red-pairs are spared, genuine
vacuous import-smokes are still upgraded.
"""
import os

from harness.planner.plan_normalizer import (
    _enforce_module_first,
    _sanitize_impl_verification_commands,
)


def _make_repo(tmp_path):
    """A minimal repo with an importable module + a pre-existing leaf test
    (the file the buggy rewrite would substitute in)."""
    (tmp_path / "harness" / "planner").mkdir(parents=True)
    (tmp_path / "harness" / "__init__.py").write_text("")
    (tmp_path / "harness" / "planner" / "__init__.py").write_text("")
    (tmp_path / "harness" / "planner" / "cli.py").write_text("# module under test\n")
    (tmp_path / "tests" / "planner").mkdir(parents=True)
    (tmp_path / "tests" / "harness").mkdir(parents=True)
    # pre-existing test for leaf 'cli' -- this is what the severing rewrite picks
    (tmp_path / "tests" / "planner" / "test_cli.py").write_text("def test_x():\n    pass\n")
    return tmp_path


def _impl(plan):
    return [t for t in plan["tasks"] if t["task_id"] == "i"][0]


def test_fix_forward_redpair_vcmd_is_preserved(tmp_path):
    repo = _make_repo(tmp_path)
    oracle_test = "tests/harness/test_epic_dedup_logging.py"
    plan = {"tasks": [
        {"task_id": "o", "meta_task_type": "test_authoring",
         "mutation_target": "harness.planner.cli",
         "files_touched": [oracle_test],
         "verification_command": "python -m pytest %s -q" % oracle_test},
        {"task_id": "i", "meta_task_type": "harness_self_fix",
         "files_touched": ["harness/planner/cli.py"],
         "dependencies": ["o"],
         "verification_command": "python -m pytest %s -q" % oracle_test},
    ]}
    out = _sanitize_impl_verification_commands(plan, repo)
    # The impl vcmd MUST still name the oracle's own authored test file, else
    # is_fix_forward_redpair returns False at acceptance and the oracle is rejected.
    assert oracle_test in _impl(out)["verification_command"]
    assert "tests/planner/test_cli.py" not in _impl(out)["verification_command"]


def test_fix_forward_redpair_with_union_oracle_files(tmp_path):
    """B5/B6-style: oracle touches several test files; impl need only name ONE."""
    repo = _make_repo(tmp_path)
    files = ["tests/harness/test_a.py", "tests/harness/test_b.py"]
    plan = {"tasks": [
        {"task_id": "o", "meta_task_type": "test_authoring",
         "mutation_target": "harness.planner.cli",
         "files_touched": files,
         "verification_command": "python -m pytest %s -q" % " ".join(files)},
        {"task_id": "i", "meta_task_type": "harness_self_fix",
         "files_touched": ["harness/planner/cli.py"],
         "dependencies": ["o"],
         "verification_command": "python -m pytest %s -q" % " ".join(files)},
    ]}
    out = _sanitize_impl_verification_commands(plan, repo)
    vc = _impl(out)["verification_command"]
    assert files[0] in vc and files[1] in vc


def test_vacuous_import_smoke_without_redpair_is_still_upgraded(tmp_path):
    """An impl whose oracle's mutation_target does NOT map into its files_touched
    is NOT a red-pair: the A.2 upgrade must still fire (no over-broadening)."""
    repo = _make_repo(tmp_path)
    plan = {"tasks": [
        {"task_id": "o", "meta_task_type": "test_authoring",
         "mutation_target": "harness.planner.something_else",
         "files_touched": ["tests/harness/test_unrelated.py"],
         "verification_command": "python -m pytest tests/harness/test_unrelated.py -q"},
        {"task_id": "i", "meta_task_type": "harness_self_fix",
         "files_touched": ["harness/planner/cli.py"],
         "verification_command": 'python -c "import harness.planner.cli"'},
    ]}
    out = _sanitize_impl_verification_commands(plan, repo)
    vc = _impl(out)["verification_command"]
    # upgraded to the real pre-existing leaf test, not left vacuous
    assert "python -c" not in vc
    assert "tests/planner/test_cli.py" in vc


def test_redpair_carveout_is_idempotent(tmp_path):
    repo = _make_repo(tmp_path)
    oracle_test = "tests/harness/test_epic_dedup_logging.py"
    plan = {"tasks": [
        {"task_id": "o", "meta_task_type": "test_authoring",
         "mutation_target": "harness.planner.cli",
         "files_touched": [oracle_test],
         "verification_command": "python -m pytest %s -q" % oracle_test},
        {"task_id": "i", "meta_task_type": "harness_self_fix",
         "files_touched": ["harness/planner/cli.py"],
         "dependencies": ["o"],
         "verification_command": "python -m pytest %s -q" % oracle_test},
    ]}
    once = _sanitize_impl_verification_commands(plan, repo)
    twice = _sanitize_impl_verification_commands(once, repo)
    assert _impl(once)["verification_command"] == _impl(twice)["verification_command"]


# --- _enforce_module_first fix-forward red-pair carve-out -----------------
#
# _enforce_module_first flips "oracle-first" pairs to module-first (oracle
# depends on impl). For a genuine EXISTING-module fix-forward red-pair that
# inverts the runtime contract: is_fix_forward_redpair needs impl.deps=[oracle]
# so load_sibling_tasks can link them. The carve-out mirrors that predicate --
# spared only when the module is on disk AND the impl vcmd names the oracle's
# own test file. A NEW-module build (module absent) still flips to module-first.

def _deps(tasks, tid):
    return [t for t in tasks if t["task_id"] == tid][0].get("dependencies")


def _redpair_tasks(mutation_target, module_file, impl_vc, oracle_test):
    return [
        {"task_id": "o", "meta_task_type": "test_authoring",
         "mutation_target": mutation_target, "files_touched": [oracle_test],
         "dependencies": []},
        {"task_id": "i", "meta_task_type": "harness_self_fix",
         "files_touched": [module_file], "verification_command": impl_vc,
         "dependencies": ["o"]},
    ]


def test_enforce_module_first_spares_existing_module_redpair(tmp_path):
    repo = _make_repo(tmp_path)  # writes harness/planner/cli.py on disk
    oracle_test = "tests/harness/test_epic_dedup_logging.py"
    tasks = _redpair_tasks("harness.planner.cli", "harness/planner/cli.py",
                           "python -m pytest %s -q" % oracle_test, oracle_test)
    _enforce_module_first(tasks, repo)
    # oracle-first preserved: impl still depends on the oracle, oracle on nothing
    assert _deps(tasks, "i") == ["o"]
    assert not _deps(tasks, "o")


def test_enforce_module_first_still_flips_new_module_build(tmp_path):
    repo = _make_repo(tmp_path)  # does NOT create harness/planner/brandnew.py
    # impl vcmd names the test, but the module is absent -> NOT a fix-forward
    # red-pair -> must still flip to module-first.
    tasks = _redpair_tasks("harness.planner.brandnew", "harness/planner/brandnew.py",
                           "python -m pytest tests/harness/test_brandnew.py -q",
                           "tests/harness/test_brandnew.py")
    _enforce_module_first(tasks, repo)
    assert _deps(tasks, "o") == ["i"]
    assert "o" not in (_deps(tasks, "i") or [])


def test_enforce_module_first_still_flips_smoke_vcmd_on_existing_module(tmp_path):
    repo = _make_repo(tmp_path)
    # existing module but impl vcmd does NOT name the oracle test (smoke import)
    # -> not a red-pair -> flip.
    tasks = _redpair_tasks("harness.planner.cli", "harness/planner/cli.py",
                           'python -c "import harness.planner.cli"',
                           "tests/harness/test_epic_dedup_logging.py")
    _enforce_module_first(tasks, repo)
    assert _deps(tasks, "o") == ["i"]
    assert "o" not in (_deps(tasks, "i") or [])


def test_enforce_module_first_none_repo_root_flips(tmp_path):
    # repo_root=None (pure mode / unit-test path) -> carve-out inert -> flip.
    oracle_test = "tests/harness/test_epic_dedup_logging.py"
    tasks = _redpair_tasks("harness.planner.cli", "harness/planner/cli.py",
                           "python -m pytest %s -q" % oracle_test, oracle_test)
    _enforce_module_first(tasks, None)
    assert _deps(tasks, "o") == ["i"]


def test_enforce_module_first_redpair_carveout_idempotent(tmp_path):
    repo = _make_repo(tmp_path)
    oracle_test = "tests/harness/test_epic_dedup_logging.py"
    tasks = _redpair_tasks("harness.planner.cli", "harness/planner/cli.py",
                           "python -m pytest %s -q" % oracle_test, oracle_test)
    _enforce_module_first(tasks, repo)
    _enforce_module_first(tasks, repo)
    assert _deps(tasks, "i") == ["o"]
    assert not _deps(tasks, "o")
