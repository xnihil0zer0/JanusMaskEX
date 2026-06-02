"""Oracle for RELAX_PREDICATE (REV23 §1(a) — CRITICAL self-target bypass).

Proves the shared ``harness.paths.relax_external_for(task, content=None)``
predicate keys the eval/exec/__import__ relax on BOTH the working_dir AND the
declared target set, closing the bypass where an EXTERNAL working_dir but a
target file INSIDE the JanusMask tree relaxed self-code security.

RED on HEAD: ``relax_external_for`` does not exist in harness.paths, so every
test fails its behavioral assertion (the helper surfaces the missing symbol as
an assertion failure, not a bare collection error, so each behavior is a
genuine RED).

GREEN after fix: the predicate returns False whenever working_dir is self/
absent OR any declared target resolves inside PROJECT_ROOT OR the target set is
empty/unresolvable (fail-closed); True only when working_dir is external AND
every resolved target lies outside PROJECT_ROOT.
"""

import pytest

from harness.paths import PROJECT_ROOT


def _relax(task, content=None):
    """Call relax_external_for, surfacing its absence as a RED assertion.

    On HEAD the symbol is missing -> AssertionError (clean RED) instead of an
    ImportError at collection time, so each behavioral case fails on its own.
    """
    try:
        from harness.paths import relax_external_for
    except ImportError as exc:  # pragma: no cover - exercised on HEAD
        pytest.fail(f"relax_external_for missing from harness.paths: {exc}")
    return relax_external_for(task, content=content)


def test_critical_self_target_bypass(tmp_path):
    # external working_dir + target file INSIDE the JM tree (absolute path into
    # PROJECT_ROOT) -> strict (False). This is the CRITICAL bypass: today the
    # working_dir-only logic returns True and relaxes eval/exec INTO JM code.
    working_dir = tmp_path / "external_target"
    working_dir.mkdir()
    task = {
        "working_dir": str(working_dir),
        "files_touched": [str(PROJECT_ROOT / "harness" / "agent_jail.py")],
    }
    assert _relax(task) is False


def test_external_working_dir_outside_project(tmp_path):
    # external working_dir + relative target resolving UNDER working_dir (outside
    # PROJECT_ROOT) -> relax allowed (True).
    working_dir = tmp_path / "external_target"
    working_dir.mkdir()
    task = {
        "working_dir": str(working_dir),
        "files_touched": ["src/foo.py"],
    }
    assert _relax(task) is True


def test_working_dir_absent_is_strict():
    # absent / None working_dir classifies as self -> strict (False).
    assert _relax({"files_touched": ["src/foo.py"]}) is False
    assert _relax({"working_dir": None, "files_touched": ["src/foo.py"]}) is False


def test_fail_closed_empty_target_set(tmp_path):
    # external working_dir but NO declared target -> fail-closed strict (False).
    working_dir = tmp_path / "external_target"
    working_dir.mkdir()
    assert _relax({"working_dir": str(working_dir), "files_touched": []}) is False
    assert _relax({"working_dir": str(working_dir)}) is False


def test_target_file_key_inside_project_is_strict(tmp_path):
    # external working_dir but task['target_file'] is an absolute JM path -> strict.
    working_dir = tmp_path / "external_target"
    working_dir.mkdir()
    task = {
        "working_dir": str(working_dir),
        "target_file": str(PROJECT_ROOT / "harness" / "orchestrator.py"),
    }
    assert _relax(task) is False


def test_manifest_targets_outside_project(tmp_path):
    # manifest-carrying content, all relative paths resolve under the external
    # working_dir (outside PROJECT_ROOT) -> True.
    working_dir = tmp_path / "external_target"
    working_dir.mkdir()
    task = {"working_dir": str(working_dir), "files_touched": []}
    content = (
        "__JANUSMASK_MANIFEST__ = {\n"
        '    "src/bar.py": "def f(): pass",\n'
        '    "src/baz.py": "def g(): pass",\n'
        "}\n"
    )
    assert _relax(task, content=content) is True


def test_manifest_target_inside_project_is_strict(tmp_path):
    # a manifest path that resolves into the JM tree -> strict (bypass closed).
    working_dir = tmp_path / "external_target"
    working_dir.mkdir()
    task = {"working_dir": str(working_dir), "files_touched": []}
    content = (
        "__JANUSMASK_MANIFEST__ = {\n"
        f'    "{PROJECT_ROOT / "harness" / "agent_jail.py"}": "def f(): pass",\n'
        "}\n"
    )
    assert _relax(task, content=content) is False


def test_unparseable_content_falls_back_to_files_touched(tmp_path):
    # content not parseable as a manifest -> ignore it, use files_touched only.
    # files_touched is empty -> fail-closed strict (False).
    working_dir = tmp_path / "external_target"
    working_dir.mkdir()
    task = {"working_dir": str(working_dir), "files_touched": []}
    assert _relax(task, content="this is not valid python {") is False
