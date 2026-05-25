"""C9.9 contract: arbitrary REAL package discovery + routing (no live rebuild).

Deterministic proofs that the engine PLANS a clean-room rebuild of a real
``samples/geopack`` package correctly:
- package discovery (sub-dir modules, ``__init__.py`` as a seed);
- relative-import-aware module ordering with a CYCLE (base<->shapes);
- per-unit routing flags: whole_class (stateful Accumulator), untyped (clamp),
  rel_import (base/shapes), needs_deps (deputil/inflection);
- test-less detection scoped to the dotted package name (only fuzzy.py).

The live blind rebuild of this package is the session capstone; this file locks
the planning logic so a regression is caught without a multi-minute live run.
"""

from __future__ import annotations

import pathlib

from harness.rebuild import discover, harvest
from harness.rebuild.loop import modules_without_tests

_REPO = pathlib.Path(__file__).resolve().parents[2]
_SAMPLE = _REPO / "samples" / "geopack"


def _descriptor(tmp_path):
    return discover.build_descriptor(
        _SAMPLE, output_dir=tmp_path / "out", stash_dir=tmp_path / "stash", name="geopack"
    )


def test_package_discovery():
    mods, tests, seeds = discover.discover_modules(_SAMPLE)
    assert set(mods) == {
        "geopack/accumulator.py", "geopack/base.py", "geopack/deputil.py",
        "geopack/fuzzy.py", "geopack/shapes.py",
    }
    assert "geopack/__init__.py" in seeds  # package init is a seed, not a target
    assert set(tests) == {
        "tests/test_accumulator.py", "tests/test_base.py",
        "tests/test_deputil.py", "tests/test_shapes.py",
    }


def test_relative_cycle_ordering():
    mods, _, _ = discover.discover_modules(_SAMPLE)
    graph = discover.module_import_graph(_SAMPLE, mods)
    # base<->shapes form a genuine module-level import CYCLE via relative imports
    assert "geopack/shapes.py" in graph["geopack/base.py"]
    assert "geopack/base.py" in graph["geopack/shapes.py"]
    order = discover.order_modules(_SAMPLE, mods)
    assert set(order) == set(mods)  # cycle falls back to a stable total order


def test_per_unit_routing_flags():
    ext = {"inflection"}
    flags: dict[str, list[str]] = {}
    for m in discover.discover_modules(_SAMPLE)[0]:
        src = (_SAMPLE / m).read_text(encoding="utf-8")
        for u in harvest.harvest_module(m, src, include_methods=True, external_modules=ext):
            flags[u.qualname] = [
                f for f in ("whole_class", "untyped", "rel_import", "needs_deps", "impure")
                if getattr(u, f)
            ]
    assert flags["geopack/accumulator.py:Accumulator"] == ["whole_class"]
    assert "untyped" in flags["geopack/fuzzy.py:clamp"]
    assert "rel_import" in flags["geopack/base.py:unit_length"]
    assert "rel_import" in flags["geopack/shapes.py:square_area"]
    assert "needs_deps" in flags["geopack/deputil.py:camelize_label"]


def test_testless_scoped_to_package(tmp_path):
    # only the genuinely test-less module (fuzzy) is flagged -- the dotted-name
    # match keeps base/shapes/accumulator/deputil (imported via from geopack.X)
    # OUT of the test-less set despite living in a sub-package.
    d = _descriptor(tmp_path)
    assert modules_without_tests(d) == ["geopack/fuzzy.py"]
    assert d.dependencies == ["inflection"]


def test_accumulator_is_whole_class():
    src = (_SAMPLE / "geopack" / "accumulator.py").read_text(encoding="utf-8")
    units = harvest.harvest_module("geopack/accumulator.py", src, include_methods=True)
    assert len(units) == 1
    u = units[0]
    assert u.whole_class and set(u.methods) == {"__init__", "add", "mean"}
