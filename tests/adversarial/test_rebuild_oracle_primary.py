"""Regression-lock the P0/C9.15 ORACLE-PRIMARY rebuild gate (W1).

For a clean-room rebuild we POSSESS the original, so the merged==original oracle
(word-domain when fuzz_str_ascii) is GROUND TRUTH. The Claude==Gemini differential
is a redundant proxy whose FALSE-divergence blocks a CORRECT reconstruction of a
quirky rule-table fn (one blind draft omits a catch-all rule and RAISES on a
no-match word, the other returns -> the differential fires FIRST and decomposes a
correct unit; inflection's stochastic exception_vs_return residual).

The fix: an opt-in rebuild_oracle_primary flag routes an oracle-USABLE unit through
the fuzz-bypass harness_plumbing policy while KEEPING the oracle vcmd, so the unit
gates on (oracle && scoped-tests) + reconstruct_unit retry. It must NOT apply to an
oracle-SKIP unit (those already route to tests-only harness_plumbing -- there is no
usable oracle to keep), and the DEFAULT path must keep the differential's redundancy.
"""

from __future__ import annotations

import harness.rebuild.task as task
from harness.rebuild.harvest import harvest_module
from harness.rebuild.target import TargetDescriptor


def _descriptor(tmp_path):
    return TargetDescriptor(
        name="infl", source_root=tmp_path / "src", modules=["infl.py"],
        test_files=["test_infl.py"], output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash", unit_test_selector="test_infl.py -k {unit}",
    )


def _unit(src, name):
    return [u for u in harvest_module("infl.py", src, include_methods=True)
            if u.name == name][0]


def _oracle_usable_unit():
    # pure + fully typed -> oracle is usable (not oracle-skip).
    src = 'def titleize(word: str) -> str:\n    """T."""\n    return word.title()\n'
    return _unit(src, "titleize")


def _oracle_skip_unit():
    # un-typed signature -> untyped -> oracle_skip (tests-only path).
    src = 'def widen(x):\n    """W."""\n    return x\n'
    return _unit(src, "widen")


def test_oracle_primary_routes_usable_unit_to_bypass_keeping_oracle(tmp_path):
    d = _descriptor(tmp_path)
    spec = task.build_unit_task(
        descriptor=d, unit=_oracle_usable_unit(), module_rel="infl.py",
        oracle_original_path="/abs/stash/infl.py.orig",
        sibling_signatures=[], unit_test_text="def test_infl_titleize_x(): pass",
        parent_root="/parent", rebuild_oracle_primary=True,
    )
    # routed through the fuzz-bypass policy ...
    assert spec.get("meta_task_type") == "harness_plumbing"
    # ... but the merged==original ORACLE vcmd is KEPT (this is the whole point --
    # bypass the redundant differential, gate on the ground-truth oracle).
    assert "oracle.py" in spec["verification_command"]
    assert "--target infl.py" in spec["verification_command"]


def test_oracle_primary_combines_with_str_ascii(tmp_path):
    d = _descriptor(tmp_path)
    spec = task.build_unit_task(
        descriptor=d, unit=_oracle_usable_unit(), module_rel="infl.py",
        oracle_original_path="/abs/stash/infl.py.orig",
        sibling_signatures=[], unit_test_text="def test_infl_titleize_x(): pass",
        parent_root="/parent", rebuild_oracle_primary=True, fuzz_str_ascii=True,
    )
    assert spec.get("meta_task_type") == "harness_plumbing"
    assert "--str-ascii" in spec["verification_command"]
    assert spec.get("fuzz_str_ascii") is True


def test_default_keeps_differential_for_usable_unit(tmp_path):
    d = _descriptor(tmp_path)
    spec = task.build_unit_task(
        descriptor=d, unit=_oracle_usable_unit(), module_rel="infl.py",
        oracle_original_path="/abs/stash/infl.py.orig",
        sibling_signatures=[], unit_test_text="def test_infl_titleize_x(): pass",
        parent_root="/parent",
    )
    # No opt-in -> the oracle-usable unit stays on the Claude==Gemini differential
    # path (no harness_plumbing bypass).
    assert "meta_task_type" not in spec


def test_oracle_primary_no_op_on_oracle_skip_unit(tmp_path):
    d = _descriptor(tmp_path)
    spec = task.build_unit_task(
        descriptor=d, unit=_oracle_skip_unit(), module_rel="infl.py",
        oracle_original_path="/abs/stash/infl.py.orig",
        sibling_signatures=[], unit_test_text="def test_infl_widen_x(): pass",
        parent_root="/parent", rebuild_oracle_primary=True,
    )
    # an oracle-skip unit already routes to tests-only harness_plumbing; oracle-primary
    # must NOT graft an (unusable) oracle onto its vcmd.
    assert spec.get("meta_task_type") == "harness_plumbing"
    assert "oracle.py" not in spec["verification_command"]
