"""Regression-lock P0a/C9.16: the `-k` exit-5 fallback for an ORACLE-USABLE unit.

When `pytest -k <unit>` collects 0 tests (a behaviour-named SHIPPED suite, or a
partial operator oracle), the OLD engine fell back to the WHOLE test file -- which
runs tests of still-STUBBED siblings and cascade-rejects a CORRECT reconstruction
of THIS unit (#39 gotcha 14 / C9.15e). FIX: for an oracle-USABLE unit, on exit 5
fall back to the merged==original ORACLE alone (we possess the original = ground
truth), never the whole file. An oracle-SKIP unit (no usable oracle) keeps the
whole-file fallback (its scoped tests are the only gate).
"""

from __future__ import annotations

import harness.rebuild.task as task
from harness.rebuild.harvest import harvest_module
from harness.rebuild.target import TargetDescriptor


def _desc(tmp_path):
    return TargetDescriptor(
        name="m", source_root=tmp_path / "src", modules=["m.py"],
        test_files=["test_m.py"], output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash", unit_test_selector="test_m.py -k {unit}",
    )


def _unit(src, name):
    return [u for u in harvest_module("m.py", src, include_methods=True)
            if u.name == name][0]


def _oracle_usable():
    src = 'def f(s: str) -> str:\n    """F."""\n    return s\n'
    return _unit(src, "f")


def _oracle_skip():
    # impure (IO/nondeterministic) -> oracle-skip -> tests-only.
    src = 'import time\ndef g(s: str) -> float:\n    """G."""\n    return time.time()\n'
    return _unit(src, "g")


def test_oracle_usable_kfallback_is_oracle_only(tmp_path):
    spec = task.build_unit_task(
        descriptor=_desc(tmp_path), unit=_oracle_usable(), module_rel="m.py",
        oracle_original_path="/abs/m.py.orig", sibling_signatures=[],
        unit_test_text="def test_m_f_x(): pass", parent_root="/parent",
    )
    vcmd = spec["verification_command"]
    assert "oracle.py" in vcmd  # oracle gates the unit
    # exit 5 (no -k match) -> pass (oracle-only), NOT a second whole-file pytest run
    assert 'if [ "$__rc" = "5" ]; then __rc=0; fi' in vcmd
    assert "pytest test_m.py -q" not in vcmd  # no whole-file fallback for an oracle unit


def test_oracle_skip_keeps_whole_file_fallback(tmp_path):
    spec = task.build_unit_task(
        descriptor=_desc(tmp_path), unit=_oracle_skip(), module_rel="m.py",
        oracle_original_path="/abs/m.py.orig", sibling_signatures=[],
        unit_test_text="def test_m_g_x(): pass", parent_root="/parent",
    )
    vcmd = spec["verification_command"]
    assert "oracle.py" not in vcmd  # oracle-skip = tests-only
    # whole-file fallback retained on exit 5 (scoped tests are the only gate)
    assert "pytest test_m.py -q" in vcmd
    assert '__rc=0; fi' not in vcmd
