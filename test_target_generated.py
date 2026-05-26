"""Verification oracle for harness/rebuild/target.py."""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from harness.rebuild.target import (
    TargetDescriptor,
    mathlib_descriptor,
    janusmask_module_descriptor,
)


def _base_kwargs(tmp_path: Path) -> dict:
    return dict(
        name="demo",
        source_root=tmp_path / "src",
        modules=["m.py"],
        test_files=["test_m.py"],
        output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash",
    )


# --------------------------------------------------------------------------
# TargetDescriptor.__post_init__
# --------------------------------------------------------------------------

def test_post_init_resolves_dir_paths_to_absolute_path_objects(tmp_path):
    desc = TargetDescriptor(**_base_kwargs(tmp_path))
    for attr in ("source_root", "output_dir", "stash_dir"):
        val = getattr(desc, attr)
        assert isinstance(val, Path), f"{attr} should be a Path"
        assert val.is_absolute(), f"{attr} should be absolute"


def test_post_init_accepts_string_paths_and_normalizes_them(tmp_path):
    kw = _base_kwargs(tmp_path)
    # Pass plain strings; __post_init__ must coerce to resolved Path.
    kw["source_root"] = str(tmp_path / "src")
    kw["output_dir"] = str(tmp_path / "out")
    kw["stash_dir"] = str(tmp_path / "stash")
    desc = TargetDescriptor(**kw)
    assert isinstance(desc.source_root, Path)
    assert isinstance(desc.output_dir, Path)
    assert isinstance(desc.stash_dir, Path)
    assert desc.source_root == (tmp_path / "src").resolve()
    assert desc.output_dir == (tmp_path / "out").resolve()
    assert desc.stash_dir == (tmp_path / "stash").resolve()


def test_post_init_collapses_dotdot_components(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    messy = tmp_path / "real" / ".." / "real"
    kw = _base_kwargs(tmp_path)
    kw["source_root"] = messy
    kw["output_dir"] = messy
    kw["stash_dir"] = messy
    desc = TargetDescriptor(**kw)
    assert desc.source_root == real.resolve()
    assert ".." not in desc.source_root.parts
    assert ".." not in desc.output_dir.parts
    assert ".." not in desc.stash_dir.parts


def test_post_init_leaves_non_path_fields_untouched(tmp_path):
    kw = _base_kwargs(tmp_path)
    kw["modules"] = ["a.py", "b.py"]
    kw["test_files"] = ["test_a.py"]
    desc = TargetDescriptor(**kw)
    # name + module/test lists are stored verbatim (not Path-coerced).
    assert desc.name == "demo"
    assert desc.modules == ["a.py", "b.py"]
    assert desc.test_files == ["test_a.py"]
    assert all(isinstance(m, str) for m in desc.modules)


def test_post_init_does_not_resolve_or_coerce_name(tmp_path):
    kw = _base_kwargs(tmp_path)
    kw["name"] = "weird/../name"
    desc = TargetDescriptor(**kw)
    assert desc.name == "weird/../name"
    assert isinstance(desc.name, str)


def test_default_field_values(tmp_path):
    desc = TargetDescriptor(**_base_kwargs(tmp_path))
    assert desc.seed_files == []
    assert desc.full_test_command == "python -m pytest -q"
    assert desc.unit_test_selector == ""
    assert desc.dependencies == []
    assert desc.requirements_files == []
    assert desc.python_exe is None


def test_default_list_fields_are_independent_per_instance(tmp_path):
    d1 = TargetDescriptor(**_base_kwargs(tmp_path))
    d2 = TargetDescriptor(**_base_kwargs(tmp_path))
    d1.seed_files.append("seed")
    d1.dependencies.append("dep")
    d1.requirements_files.append("req")
    # field(default_factory=list) -> distinct list objects, no shared mutable default.
    assert d2.seed_files == []
    assert d2.dependencies == []
    assert d2.requirements_files == []


def test_is_a_dataclass_with_explicit_overrides(tmp_path):
    kw = _base_kwargs(tmp_path)
    kw["seed_files"] = ["harness/__init__.py"]
    kw["dependencies"] = ["pytest>=7"]
    kw["requirements_files"] = ["requirements.txt"]
    kw["python_exe"] = "/usr/bin/python3"
    kw["unit_test_selector"] = "tests -k {unit}"
    kw["full_test_command"] = "pytest -x"
    desc = TargetDescriptor(**kw)
    assert dataclasses.is_dataclass(desc)
    assert desc.seed_files == ["harness/__init__.py"]
    assert desc.dependencies == ["pytest>=7"]
    assert desc.requirements_files == ["requirements.txt"]
    assert desc.python_exe == "/usr/bin/python3"
    assert desc.unit_test_selector == "tests -k {unit}"
    assert desc.full_test_command == "pytest -x"


# --------------------------------------------------------------------------
# mathlib_descriptor
# --------------------------------------------------------------------------

def test_mathlib_descriptor_fixed_fields(tmp_path):
    desc = mathlib_descriptor(
        output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash",
        source_root=tmp_path / "src",
    )
    assert isinstance(desc, TargetDescriptor)
    assert desc.name == "mathlib"
    assert desc.modules == ["mathlib.py"]
    assert desc.test_files == ["test_mathlib.py"]
    assert desc.seed_files == []
    # mathlib uses the default whole-suite command (test files are NOT appended).
    assert desc.full_test_command == "python -m pytest -q"
    assert desc.unit_test_selector == "test_mathlib.py -k {unit}"


def test_mathlib_descriptor_resolves_paths(tmp_path):
    desc = mathlib_descriptor(
        output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash",
        source_root=tmp_path / "src",
    )
    assert desc.source_root == (tmp_path / "src").resolve()
    assert desc.output_dir == (tmp_path / "out").resolve()
    assert desc.stash_dir == (tmp_path / "stash").resolve()
    assert desc.source_root.is_absolute()
    assert desc.output_dir.is_absolute()
    assert desc.stash_dir.is_absolute()


# --------------------------------------------------------------------------
# janusmask_module_descriptor
# --------------------------------------------------------------------------

def test_janusmask_descriptor_passes_through_core_fields(tmp_path):
    desc = janusmask_module_descriptor(
        name="safe_subpath",
        modules=["harness/safe_subpath.py"],
        test_files=["tests/security/test_safe_subpath.py"],
        output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash",
        source_root=tmp_path / "src",
        unit_test_selector="tests -k {unit}",
    )
    assert isinstance(desc, TargetDescriptor)
    assert desc.name == "safe_subpath"
    assert desc.modules == ["harness/safe_subpath.py"]
    assert desc.test_files == ["tests/security/test_safe_subpath.py"]
    assert desc.unit_test_selector == "tests -k {unit}"
    assert desc.source_root == (tmp_path / "src").resolve()
    assert desc.output_dir == (tmp_path / "out").resolve()
    assert desc.stash_dir == (tmp_path / "stash").resolve()


def test_janusmask_descriptor_builds_full_test_command_from_test_files(tmp_path):
    desc = janusmask_module_descriptor(
        name="multi",
        modules=["a.py"],
        test_files=["tests/test_a.py", "tests/test_b.py"],
        output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash",
        source_root=tmp_path / "src",
    )
    assert desc.full_test_command == "python -m pytest -q tests/test_a.py tests/test_b.py"


def test_janusmask_descriptor_single_test_file_in_command(tmp_path):
    desc = janusmask_module_descriptor(
        name="solo",
        modules=["a.py"],
        test_files=["tests/test_a.py"],
        output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash",
        source_root=tmp_path / "src",
    )
    assert desc.full_test_command == "python -m pytest -q tests/test_a.py"


def test_janusmask_descriptor_seed_files_default_none_becomes_empty_list(tmp_path):
    desc = janusmask_module_descriptor(
        name="x",
        modules=["a.py"],
        test_files=["t.py"],
        output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash",
        source_root=tmp_path / "src",
        seed_files=None,
    )
    assert desc.seed_files == []


def test_janusmask_descriptor_seed_files_passed_through(tmp_path):
    seeds = ["harness/__init__.py", "tests/conftest.py"]
    desc = janusmask_module_descriptor(
        name="x",
        modules=["a.py"],
        test_files=["t.py"],
        output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash",
        source_root=tmp_path / "src",
        seed_files=seeds,
    )
    assert desc.seed_files == seeds


def test_janusmask_descriptor_default_unit_test_selector_is_empty(tmp_path):
    desc = janusmask_module_descriptor(
        name="x",
        modules=["a.py"],
        test_files=["t.py"],
        output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash",
        source_root=tmp_path / "src",
    )
    assert desc.unit_test_selector == ""