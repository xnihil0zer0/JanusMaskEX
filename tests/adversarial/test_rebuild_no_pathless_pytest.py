"""Regression-lock: the rebuild engine must NEVER emit a path-less ``pytest -q``.

When a discovered descriptor has no ``unit_test_selector`` AND no ``test_files``
(e.g. a test-less module rebuilt with --no-gen-testless, or before the test-author
registers its generated oracle), the per-unit verification_command degenerated to
``python -m pytest  -q`` -- a path-LESS invocation that collects the WHOLE output
repo. The rebuild agents leave stray scratch ``test_*.py`` in the output root, and
one with a top-level ``sys.exit(pytest.main(...))`` crashes pytest collection with
an INTERNALERROR (exit 3), spuriously rolling back a CORRECT reconstruction
(witnessed on the inflection rebuild: pluralize/titleize/tableize passed the
2000/2000 differential fuzz, then the path-less pytest crashed on a scratch file).

The fix: with no scoped tests, the merged==original oracle is the sole gate (never
a whole-dir pytest); an oracle-skip unit with no tests fails LOUD instead.
"""

from __future__ import annotations

from pathlib import Path

import harness.rebuild.loop as loop
import harness.rebuild.task as task
from harness.rebuild.harvest import harvest_module
from harness.rebuild.target import TargetDescriptor


def _descriptor(tmp_path, *, test_files=None, selector=""):
    return TargetDescriptor(
        name="m", source_root=tmp_path / "src", modules=["m.py"],
        test_files=test_files or [], output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash", unit_test_selector=selector,
    )


def _pure_unit():
    src = 'def f(s: str) -> str:\n    """F."""\n    return s\n'
    return [u for u in harvest_module("m.py", src, include_methods=True) if u.name == "f"][0]


def _impure_unit():
    # an impure (oracle-skip) unit: calls time.time() -> tests-only path.
    src = ('import time\n'
           'def g(s: str) -> float:\n    """G."""\n    return time.time()\n')
    return [u for u in harvest_module("m.py", src, include_methods=True) if u.name == "g"][0]


def test_no_testfiles_no_selector_oracle_only_no_pathless_pytest(tmp_path):
    d = _descriptor(tmp_path)  # empty test_files + empty selector
    spec = task.build_unit_task(
        descriptor=d, unit=_pure_unit(), module_rel="m.py",
        oracle_original_path="/abs/m.py.orig", sibling_signatures=[],
        unit_test_text="", parent_root="/parent",
    )
    vcmd = spec["verification_command"]
    assert "rebuild/oracle.py" in vcmd  # oracle is the gate
    # never a path-less pytest (the bug was a bare ``pytest  -q`` with no path).
    assert "pytest  -q" not in vcmd
    assert "&& python -m pytest -q" not in vcmd
    assert not vcmd.rstrip().endswith("pytest -q")


def test_oracle_skip_no_tests_fails_loud_not_pathless(tmp_path):
    d = _descriptor(tmp_path)  # empty test_files + empty selector
    spec = task.build_unit_task(
        descriptor=d, unit=_impure_unit(), module_rel="m.py",
        oracle_original_path="/abs/m.py.orig", sibling_signatures=[],
        unit_test_text="", parent_root="/parent",
    )
    vcmd = spec["verification_command"]
    assert "pytest  -q" not in vcmd
    assert "exit 1" in vcmd  # loud failure, not a vacuous/whole-dir pass


def test_run_unit_tests_no_tests_is_noop_pass(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    d = _descriptor(tmp_path)  # empty test_files + empty selector
    res = loop._run_unit_tests(d, _pure_unit())
    assert res["returncode"] == 0
    assert "no scoped tests" in res["stdout_tail"]


def test_with_testfiles_still_scopes_to_them(tmp_path):
    d = _descriptor(tmp_path, test_files=["test_m.py"])
    spec = task.build_unit_task(
        descriptor=d, unit=_pure_unit(), module_rel="m.py",
        oracle_original_path="/abs/m.py.orig", sibling_signatures=[],
        unit_test_text="", parent_root="/parent",
    )
    assert "pytest test_m.py -q" in spec["verification_command"]
