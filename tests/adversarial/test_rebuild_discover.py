"""Tests for harness.rebuild.discover: build a TargetDescriptor from a BARE dir.

The arbitrary-project enabler. Given just a directory of .py modules + pytest
files (no hand-authored module/test lists), discover infers the modules to
rebuild, the test spec, seed scaffolding, and a per-unit selector. Proven on
the shipped samples and on a JanusMask source slice.
"""

from __future__ import annotations

from pathlib import Path

import harness.rebuild.discover as discover

_REPO = Path(__file__).resolve().parent.parent.parent


def test_public_surface():
    assert callable(discover.discover_modules)
    assert callable(discover.build_descriptor)


def test_discover_modules_on_mathlib_sample():
    mods, tests, seeds = discover.discover_modules(_REPO / "samples" / "mathlib")
    assert mods == ["mathlib.py"]
    assert tests == ["test_mathlib.py"]
    assert seeds == []


def test_build_descriptor_from_bare_mathlib_dir(tmp_path):
    desc = discover.build_descriptor(
        _REPO / "samples" / "mathlib",
        output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash",
    )
    assert desc.name == "mathlib"
    assert desc.modules == ["mathlib.py"]
    assert desc.test_files == ["test_mathlib.py"]
    # single test file -> a per-unit -k selector is derived automatically
    assert "{unit}" in desc.unit_test_selector
    assert "test_mathlib.py" in desc.unit_test_selector
    assert "test_mathlib.py" in desc.full_test_command


def test_discover_classifies_tests_seeds_and_modules(tmp_path):
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "core.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (root / "conftest.py").write_text("", encoding="utf-8")
    (root / "test_core.py").write_text("def test_f():\n    assert True\n", encoding="utf-8")
    (root / "thing_test.py").write_text("def test_t():\n    assert True\n", encoding="utf-8")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "junk.py").write_text("x=1\n", encoding="utf-8")
    mods, tests, seeds = discover.discover_modules(root)
    assert "pkg/core.py" in mods
    assert "pkg/__init__.py" not in mods  # seed, not a rebuild target
    assert set(tests) == {"test_core.py", "thing_test.py"}
    assert "pkg/__init__.py" in seeds
    assert "conftest.py" in seeds
    assert all("__pycache__" not in m for m in mods)


def test_build_descriptor_on_janusmask_slice(tmp_path):
    # A bare slice: just depth_validator + its test, discovered from explicit roots.
    desc = discover.build_descriptor(
        _REPO,
        output_dir=tmp_path / "jr",
        stash_dir=tmp_path / "stash",
        name="depth_validator",
        modules=["harness/depth_validator.py"],
        test_files=["tests/test_depth_validator.py"],
        seed_files=["harness/__init__.py"],
    )
    assert desc.name == "depth_validator"
    assert desc.modules == ["harness/depth_validator.py"]
    assert "tests/test_depth_validator.py" in desc.full_test_command
    assert desc.source_root == _REPO.resolve()
