"""B6 (C9.11e): a self-mutating method (dataclass __post_init__ / value-less
setter) routes to the tests-only oracle-skip path, because the merged==original
differential fuzz oracle is VACUOUS for it (the oracle resolves the target by
MODULE-namespace name, never finds a method there, and reports every input as a
matching NameError -> equivalent=True even for a plainly wrong body)."""

from __future__ import annotations

from pathlib import Path

import harness.rebuild.harvest as _harvest
import harness.rebuild.task as _task
from harness.rebuild.target import TargetDescriptor

_REPO = Path(__file__).resolve().parent.parent.parent

_SRC = (
    "from dataclasses import dataclass\n\n\n"
    "@dataclass\n"
    "class Box:\n"
    "    raw: str\n"
    '    norm: str = ""\n'
    "    def __post_init__(self):\n"
    "        self.norm = self.raw.strip().lower()\n"
    "    def label(self) -> str:\n"
    "        return self.norm.upper()\n"
)


def _units():
    return {
        u.name: u
        for u in _harvest.harvest_module("box.py", _SRC, include_methods=True)
    }


def test_post_init_flagged_self_mutating():
    pi = _units()["__post_init__"]
    assert pi.self_mutating is True


def test_value_returning_method_not_self_mutating():
    # ``label`` returns a value -> it HAS a meaningful fuzz/test domain; not flagged.
    lbl = _units()["label"]
    assert lbl.self_mutating is False


def _desc(tmp_path) -> TargetDescriptor:
    (tmp_path / "box.py").write_text(_SRC, encoding="utf-8")
    return TargetDescriptor(
        name="box",
        source_root=tmp_path,
        modules=["box.py"],
        test_files=["test_box.py"],
        output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash",
        unit_test_selector="test_box.py -k {unit}",
    )


def test_self_mutating_unit_oracle_skips(tmp_path):
    desc = _desc(tmp_path)
    pi = _units()["__post_init__"]
    spec = _task.build_unit_task(
        descriptor=desc,
        unit=pi,
        module_rel="box.py",
        oracle_original_path=str(tmp_path / "stash" / "box.py"),
        sibling_signatures=[],
        unit_test_text="",
        parent_root=str(_REPO),
    )
    # tests-only: the merged==original oracle.py is NOT invoked.
    assert "oracle.py" not in spec["verification_command"]
    # fuzzer-bypass so two drafts diverging on a vacuous domain don't force a
    # meaningless decomposition of an atomic method.
    assert spec.get("meta_task_type") == "harness_plumbing"


def test_value_returning_method_keeps_oracle(tmp_path):
    desc = _desc(tmp_path)
    lbl = _units()["label"]
    spec = _task.build_unit_task(
        descriptor=desc,
        unit=lbl,
        module_rel="box.py",
        oracle_original_path=str(tmp_path / "stash" / "box.py"),
        sibling_signatures=[],
        unit_test_text="",
        parent_root=str(_REPO),
    )
    assert "oracle.py" in spec["verification_command"]


# ----- unfuzzable typed params (domain objects) route to oracle-skip -----
# NOTE: Path and ast.* are NO LONGER unfuzzable as of the session #47 structured-
# input fuzz (diff_fuzzer synthesizes them); a genuine DOMAIN type the fuzzer can't
# synthesize (a local class) still routes to oracle-skip.

_UNFUZZABLE_SRC = (
    "class Widget:\n"
    "    pass\n\n\n"
    "def make_domain_thing(w: Widget, n: int) -> str:\n"
    "    return repr(w) + ':' + str(n)\n\n\n"
    "def pure_primitive(a: int, b: str) -> str:\n"
    "    return b * a\n"
)


def _unfuzzable_units():
    return {
        u.name: u
        for u in _harvest.harvest_module("m.py", _UNFUZZABLE_SRC)
    }


def test_domain_param_flagged_unfuzzable():
    u = _unfuzzable_units()["make_domain_thing"]
    assert u.unfuzzable is True


def test_all_primitive_params_not_unfuzzable():
    u = _unfuzzable_units()["pure_primitive"]
    assert u.unfuzzable is False


def test_unfuzzable_unit_oracle_skips(tmp_path):
    (tmp_path / "m.py").write_text(_UNFUZZABLE_SRC, encoding="utf-8")
    desc = TargetDescriptor(
        name="m",
        source_root=tmp_path,
        modules=["m.py"],
        test_files=["test_m.py"],
        output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash",
        unit_test_selector="test_m.py -k {unit}",
    )
    u = _unfuzzable_units()["make_domain_thing"]
    spec = _task.build_unit_task(
        descriptor=desc,
        unit=u,
        module_rel="m.py",
        oracle_original_path=str(tmp_path / "stash" / "m.py"),
        sibling_signatures=[],
        unit_test_text="",
        parent_root=str(_REPO),
    )
    assert "oracle.py" not in spec["verification_command"]
    assert spec.get("meta_task_type") == "harness_plumbing"
