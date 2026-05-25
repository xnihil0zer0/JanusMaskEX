"""Regression-lock the P1/C9.14 large-file partial-edit rebuild keystone.

A MODULE FILE too large to round-trip as a whole-file submission through the AST
merge (e.g. harness/orchestrator.py ~136KB, sandbox.py ~74KB) cannot be rebuilt
unit-by-unit by the default whole-file path -- the agent cannot reliably reproduce
the entire file. P1 routes each unit of an over-budget file through the EXISTING
__JANUSMASK_PATCHES__ partial-edit contract (single-symbol in-place patch applied
by harness/git_integration.py), which is fuzz-bypassed (the patch list is not
fuzzable module code) via the harness_plumbing meta_task_type and gated by the
merged==original oracle + scoped tests against the PATCHED file post-commit.

These lock: (1) the file-budget trigger, (2) the partial-edit task spec shape the
worker + git_integration consume, (3) the bare (non-``module:``-prefixed) patch
name for plain/method/whole-class units, and (4) that the whole-file path is
unchanged when the file is under budget.
"""

from __future__ import annotations

from pathlib import Path

import harness.rebuild.loop as loop
import harness.rebuild.task as task
from harness.rebuild.harvest import harvest_module
from harness.rebuild.target import TargetDescriptor


_SRC = (
    'def titleize(word: str) -> str:\n'
    '    """Capitalize each word."""\n'
    '    return word.title()\n'
    '\n'
    'class Box:\n'
    '    """A box."""\n'
    '    def grow(self, n: int) -> int:\n'
    '        """Grow by n."""\n'
    '        return n + 1\n'
)


def _descriptor(tmp_path: Path) -> TargetDescriptor:
    return TargetDescriptor(
        name="big",
        source_root=tmp_path / "src",
        modules=["big.py"],
        test_files=["test_big.py"],
        output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash",
        unit_test_selector="test_big.py -k {unit}",
    )


def _unit(name, cls=None):
    units = harvest_module("big.py", _SRC, include_methods=True)
    for u in units:
        if u.name == name and u.cls == cls and not u.whole_class:
            return u
    raise AssertionError(f"unit {name!r} cls={cls!r} not harvested from sample")


# --- (1) the file-budget trigger ----------------------------------------------

def test_file_merge_budget_default_is_50k():
    assert loop._file_merge_budget_from_config(None) == 50000


def test_file_exceeds_merge_budget_large_true_small_false():
    assert loop.file_exceeds_merge_budget("x" * 60000) is True
    assert loop.file_exceeds_merge_budget("x" * 100) is False


def test_file_merge_budget_config_override():
    cfg = {"rebuild": {"file_merge_budget": 10}}
    assert loop.file_exceeds_merge_budget("x" * 20, cfg) is True
    assert loop.file_exceeds_merge_budget("x" * 5, cfg) is False


def test_file_budget_counts_utf8_bytes_not_chars():
    # a multibyte char must count by its encoded bytes, not str length.
    s = "é" * 30000  # 2 bytes each -> 60000 bytes > 50000
    assert len(s) < 50000 and loop.file_exceeds_merge_budget(s) is True


# --- (2)+(3) partial-edit task spec shape -------------------------------------

def test_partial_edit_spec_routes_through_patches_and_plumbing(tmp_path):
    d = _descriptor(tmp_path)
    spec = task.build_unit_task(
        descriptor=d, unit=_unit("titleize"), module_rel="big.py",
        oracle_original_path="/abs/stash/big.py.orig",
        sibling_signatures=[], unit_test_text="def test_big_titleize_x(): pass",
        parent_root="/parent", partial_edit=True,
    )
    assert spec["partial_edit"] is True
    # un-fuzzable patch list -> fuzz-bypass + smoke-skip harness_plumbing policy.
    assert spec["meta_task_type"] == "harness_plumbing"
    body = spec["specification"]
    assert "__JANUSMASK_PATCHES__" in body
    # the bare in-file symbol name, NOT the module:-prefixed qualname.
    assert "'name': 'titleize'" in body
    assert "big.py:titleize" not in body
    assert "'file': 'big.py'" in body
    # must NOT instruct the agent to emit a whole self-contained file.
    assert "single self-contained Python file" not in body


def test_partial_edit_method_name_is_dotted(tmp_path):
    d = _descriptor(tmp_path)
    spec = task.build_unit_task(
        descriptor=d, unit=_unit("grow", cls="Box"), module_rel="big.py",
        oracle_original_path="/abs/stash/big.py.orig",
        sibling_signatures=[], unit_test_text="def test_big_grow_x(): pass",
        parent_root="/parent", partial_edit=True,
    )
    body = spec["specification"]
    assert "'name': 'Box.grow'" in body
    assert spec["partial_edit"] is True


def test_partial_edit_keeps_oracle_in_vcmd_for_pure_unit(tmp_path):
    # a pure (non-oracle-skip) unit in a large file still runs the merged==original
    # oracle against the PATCHED file -- partial_edit must NOT silently drop it.
    d = _descriptor(tmp_path)
    spec = task.build_unit_task(
        descriptor=d, unit=_unit("titleize"), module_rel="big.py",
        oracle_original_path="/abs/stash/big.py.orig",
        sibling_signatures=[], unit_test_text="def test_big_titleize_x(): pass",
        parent_root="/parent", partial_edit=True,
    )
    assert "rebuild/oracle.py" in spec["verification_command"]


def test_partial_edit_suppresses_sibling_body_inlining(tmp_path):
    # the patch is a single symbol, so verbatim sibling BODIES must not be inlined.
    d = _descriptor(tmp_path)
    sib_body = "def helper(x):\n    return x\n"
    spec = task.build_unit_task(
        descriptor=d, unit=_unit("titleize"), module_rel="big.py",
        oracle_original_path="/abs/stash/big.py.orig",
        sibling_signatures=["def helper(x):"], sibling_bodies=[sib_body],
        unit_test_text="", parent_root="/parent", partial_edit=True,
    )
    assert "include each of them VERBATIM" not in spec["specification"]


# --- (4) the whole-file path is unchanged when under budget --------------------

def test_non_partial_edit_unchanged(tmp_path):
    d = _descriptor(tmp_path)
    spec = task.build_unit_task(
        descriptor=d, unit=_unit("titleize"), module_rel="big.py",
        oracle_original_path="/abs/stash/big.py.orig",
        sibling_signatures=[], unit_test_text="def test_big_titleize_x(): pass",
        parent_root="/parent",
    )
    assert "partial_edit" not in spec
    assert "__JANUSMASK_PATCHES__" not in spec["specification"]
    assert "single self-contained Python file" in spec["specification"]
