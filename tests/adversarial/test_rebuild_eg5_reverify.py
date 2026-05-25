"""Regression-lock EG5: post-rebuild whole-module STANDALONE re-verify.

Per-unit gating holds only at the instant a unit lands. A later sibling's blind
reconstruction re-emits an already-accepted unit's body (injected as context),
the AST merge applies it, and the sibling's gate never re-checks the accepted
unit -- so a carry-forward can silently corrupt it (#43 g33; #47
``get_latest_submission`` lost its ``Path()`` coercion). ``--resume`` then SKIPS
the corrupted unit, fake-accepting it. ``loop._reverify_modules`` re-runs each
oracle-USABLE top-level unit's merged==original ORACLE against its CURRENTLY
COMMITTED body and reports the diverging units so ``reconstruct_all`` refuses
``complete`` instead of fake-accepting.
"""
from __future__ import annotations

import harness.rebuild.loop as loop
from harness.rebuild.harvest import harvest_module
from harness.rebuild.target import TargetDescriptor

_ORIG = "def add(a: int, b: int) -> int:\n    return a + b\n"
_WRONG = "def add(a: int, b: int) -> int:\n    return a * b\n"


def _setup(tmp_path, out_body):
    src = tmp_path / "src"
    src.mkdir()
    (src / "m.py").write_text(_ORIG, encoding="utf-8")
    stash = tmp_path / "stash"
    stash.mkdir()
    orig = stash / "m.py.orig"
    orig.write_text(_ORIG, encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    (out / "m.py").write_text(out_body, encoding="utf-8")
    desc = TargetDescriptor(
        name="t", source_root=src, modules=["m.py"], test_files=[],
        output_dir=out, stash_dir=stash, unit_test_selector="",
    )
    units = harvest_module("m.py", _ORIG, include_methods=True)
    ordered = [("m.py", u) for u in units]
    return desc, ordered, {"m.py": str(orig)}


def test_reverify_flags_diverged_unit(tmp_path):
    # A committed body that diverges from the original (a*b vs a+b) must be flagged.
    desc, ordered, stash_map = _setup(tmp_path, _WRONG)
    failures = loop._reverify_modules(desc, ordered, stash_map)
    assert any("add" in f for f in failures), failures


def test_reverify_passes_correct_unit(tmp_path):
    # A faithfully reconstructed body (a+b) re-verifies clean -- no false positive.
    desc, ordered, stash_map = _setup(tmp_path, _ORIG)
    failures = loop._reverify_modules(desc, ordered, stash_map)
    assert failures == [], failures
