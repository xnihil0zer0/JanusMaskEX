"""Harvest/strip handle ClassDef METHOD units + full-project skeleton (C9.6)."""

from __future__ import annotations

import ast
from pathlib import Path

import harness.rebuild.harvest as _harvest
import harness.rebuild.strip as _strip

_REPO = Path(__file__).resolve().parent.parent.parent
_WIDGETS_REL = "widgets.py"
_WIDGETS = (_REPO / "samples" / "widgets" / "widgets.py").read_text(encoding="utf-8")


def test_harvest_top_level_only_by_default():
    names = {u.name for u in _harvest.harvest_module(_WIDGETS_REL, _WIDGETS)}
    assert names == {"double", "quadruple", "file_size"}
    assert all(u.cls is None for u in _harvest.harvest_module(_WIDGETS_REL, _WIDGETS))


def test_harvest_includes_methods_when_requested():
    # C9.9: widgets.Accumulator is STATEFUL (add/reset mutate self.total set in
    # __init__) and co-tested (test_accumulator calls add() AND reset()), so
    # include_methods harvests it as ONE whole_class unit reconstructed together
    # -- per-method recon would fail because the shared test exercises sibling
    # stubs (the #34 gotcha). Per-method recon remains for STATELESS classes
    # (wordtools.Caser, covered in test_rebuild_multimodule).
    units = _harvest.harvest_module(_WIDGETS_REL, _WIDGETS, include_methods=True)
    by_qn = {u.qualname: u for u in units}
    acc = by_qn["widgets.py:Accumulator"]
    assert acc.whole_class is True and acc.cls == "Accumulator"
    assert set(acc.methods) == {"__init__", "add", "reset"}
    assert "def add(self, x: int)" in acc.class_skeleton
    # top-level functions still present alongside the class unit
    assert "widgets.py:double" in by_qn


def test_harvest_intra_module_call_dep_edge():
    units = {u.name: u for u in _harvest.harvest_module(_WIDGETS_REL, _WIDGETS)}
    assert "double" in units["quadruple"].calls  # quadruple -> double dependency


def test_order_units_places_callee_before_caller():
    units = _harvest.harvest_module(_WIDGETS_REL, _WIDGETS)
    ordered = [u.name for u in _harvest.order_units(units)]
    assert ordered.index("double") < ordered.index("quadruple")


def test_strip_skeletonizes_methods_too():
    skel = _strip.strip_source(_WIDGETS)
    tree = ast.parse(skel)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Accumulator")
    methods = [m for m in cls.body if isinstance(m, ast.FunctionDef)]
    assert {m.name for m in methods} == {"__init__", "add", "reset"}
    for m in methods:
        raises = [s for s in m.body if isinstance(s, ast.Raise)]
        assert len(raises) == 1 and raises[0].exc.id == "NotImplementedError"


def test_strip_retains_class_and_signatures():
    skel = _strip.strip_source(_WIDGETS)
    tree = ast.parse(skel)
    # the class survives, top-level functions survive and are stubbed
    assert any(isinstance(n, ast.ClassDef) and n.name == "Accumulator" for n in tree.body)
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert set(fns) == {"double", "quadruple", "file_size"}
    assert fns["double"].returns is not None
