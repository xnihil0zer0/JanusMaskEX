"""Regression-lock EG3: the per-unit test gate is scoped to the unit's OWN module.

A multi-module gen_testless batch registers every module's generated oracle into
``descriptor.test_files`` + ``unit_test_selector``. Pre-EG3, a unit's pytest
invocation (both the ``-k`` selector and the oracle-SKIP whole-file fallback)
listed EVERY module's generated test, so a sibling module's test that calls a
still-stubbed unit (raising NotImplementedError) -- or a collection error in a
sibling oracle -- FALSELY rejected this unit's correct reconstruction. The gate
must list only THIS module's generated oracle (+ shipped tests that import it).
"""
from __future__ import annotations

import harness.rebuild.task as task
from harness.rebuild.harvest import harvest_module
from harness.rebuild.target import TargetDescriptor


def _desc(tmp_path):
    return TargetDescriptor(
        name="batch", source_root=tmp_path / "src",
        modules=["a.py", "b.py"],
        test_files=["test_a_generated.py", "test_b_generated.py"],
        output_dir=tmp_path / "out", stash_dir=tmp_path / "stash",
        unit_test_selector="test_a_generated.py test_b_generated.py -k {unit}",
    )


def _impure_unit(module_rel, name):
    src = f"import time\n\n\ndef {name}(s: str) -> float:\n    return time.time()\n"
    return [u for u in harvest_module(module_rel, src, include_methods=True)
            if u.name == name][0]


def _pure_unit(module_rel, name):
    src = f"def {name}(s: str) -> str:\n    '''doc'''\n    return s\n"
    return [u for u in harvest_module(module_rel, src, include_methods=True)
            if u.name == name][0]


def test_oracle_skip_fallback_scoped_to_own_module(tmp_path):
    # An impure (oracle-SKIP) unit keeps the whole-file fallback -- but it must run
    # ONLY module a's generated oracle, never module b's.
    spec = task.build_unit_task(
        descriptor=_desc(tmp_path), unit=_impure_unit("a.py", "g"),
        module_rel="a.py", oracle_original_path="/abs/a.py.orig",
        sibling_signatures=[], unit_test_text="def test_a_g_x(): pass",
        parent_root="/parent",
    )
    vcmd = spec["verification_command"]
    assert "test_a_generated.py" in vcmd
    assert "test_b_generated.py" not in vcmd


def test_selector_scoped_to_own_module(tmp_path):
    # The -k selector for a unit in module b must reference module b's oracle only.
    spec = task.build_unit_task(
        descriptor=_desc(tmp_path), unit=_impure_unit("b.py", "h"),
        module_rel="b.py", oracle_original_path="/abs/b.py.orig",
        sibling_signatures=[], unit_test_text="def test_b_h_x(): pass",
        parent_root="/parent",
    )
    vcmd = spec["verification_command"]
    assert "test_b_generated.py" in vcmd
    assert "test_a_generated.py" not in vcmd


def test_module_test_files_matches_generated_and_importers(tmp_path):
    src = tmp_path / "src"
    (src / "tests").mkdir(parents=True, exist_ok=True)
    # A shipped test that imports module a by name.
    (src / "tests" / "test_shipped.py").write_text(
        "from a import g\n\n\ndef test_g():\n    assert g\n", encoding="utf-8"
    )
    desc = TargetDescriptor(
        name="batch", source_root=src, modules=["a.py", "b.py"],
        test_files=["test_a_generated.py", "test_b_generated.py", "tests/test_shipped.py"],
        output_dir=tmp_path / "out", stash_dir=tmp_path / "stash",
        unit_test_selector="",
    )
    got = task._module_test_files(desc, "a.py")
    assert "test_a_generated.py" in got
    assert "tests/test_shipped.py" in got  # imports module a
    assert "test_b_generated.py" not in got
