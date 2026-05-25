"""C9.10 P1 contract: the reconstruct-oversized DRIVER actually decomposes ->
reconstructs (blind, via gen_fn) -> recomposes -> writes -> gates on the unit's
tests, and reconstruct_all ROUTES an oversized unit to it (not just an enqueued
retry). The blind per-segment reconstruction is stubbed (gen_fn returns the
original segments) so the orchestration is proven without spawning agents.
"""
from __future__ import annotations

from pathlib import Path

import harness.rebuild.loop as _loop
import harness.rebuild.strip as _strip
import harness.rebuild.harvest as _harvest
from harness.rebuild.decompose import decompose_function_body
from harness.rebuild.target import TargetDescriptor

_REPO = Path(__file__).resolve().parent.parent.parent
_SAMPLE = _REPO / "samples" / "bigpipe"
_MOD_REL = "bigpipe/pipeline.py"
_BUDGET = 400


def _desc(tmp_path) -> TargetDescriptor:
    return TargetDescriptor(
        name="bigpipe",
        source_root=_SAMPLE,
        modules=[_MOD_REL],
        test_files=["tests/test_pipeline.py"],
        output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash",
        unit_test_selector="tests/test_pipeline.py -k {unit}",
    )


def _normalize_unit():
    src = (_SAMPLE / _MOD_REL).read_text(encoding="utf-8")
    return next(
        u for u in _harvest.harvest_module(_MOD_REL, src, include_methods=True)
        if u.name == "normalize"
    )


def test_oversized_unit_decomposes_reconstructs_recomposes(tmp_path):
    desc = _desc(tmp_path)
    info = _strip.materialize_skeleton(desc)
    stash_map = info["stash"]
    out_mod = desc.output_dir / _MOD_REL
    assert _loop.has_notimplemented(out_mod, "normalize"), "skeleton must stub normalize"

    unit = _normalize_unit()
    orig_src = Path(stash_map[_MOD_REL]).read_text(encoding="utf-8")
    func_src = _loop._unit_body_segment(orig_src, unit)
    dec = decompose_function_body(func_src, _BUDGET)
    assert len(dec["segments"]) >= 2, "sample must genuinely decompose at this budget"

    seq = iter(dec["segments"])
    calls = {"n": 0}

    def gen(prompt):
        calls["n"] += 1
        return next(seq)

    res = _loop.reconstruct_oversized_unit(
        desc, unit, _MOD_REL, stash_map,
        gen_fn=gen, config={"rebuild": {"unit_byte_budget": _BUDGET}}, commit=False,
    )
    assert res["body_landed"] is True
    assert res["segments"] >= 2
    assert res.get("tests_passed") is True
    assert calls["n"] == res["segments"], "every segment reconstructed blind"
    # the recomposed body is real (no NotImplementedError stub remains)
    assert _loop.has_notimplemented(out_mod, "normalize") is False


def test_reconstruct_all_routes_oversized_to_driver(tmp_path, monkeypatch):
    desc = _desc(tmp_path)
    _strip.materialize_skeleton(desc)
    routed = {}

    def _fake_oversized(*a, **k):
        routed["oversized"] = True
        return {"unit": "normalize", "body_landed": True,
                "outcome": "oversized_recomposed", "segments": 3}

    def _fake_normal(*a, **k):
        routed["normal"] = True
        return {"unit": "x", "body_landed": True, "outcome": "accepted"}

    monkeypatch.setattr(_loop, "reconstruct_oversized_unit", _fake_oversized)
    monkeypatch.setattr(_loop, "reconstruct_unit", _fake_normal)
    _loop.reconstruct_all(
        desc, only="normalize", init=False,
        config={"rebuild": {"unit_byte_budget": _BUDGET}},
    )
    assert routed.get("oversized") is True, "oversized unit must route to the driver"
    assert routed.get("normal") is None, "oversized unit must NOT take the normal path"


# --- B2 (session #37): robustness of the oversized driver ---------------------

def _segs(tmp_path):
    desc = _desc(tmp_path)
    info = _strip.materialize_skeleton(desc)
    stash_map = info["stash"]
    unit = _normalize_unit()
    func_src = _loop._unit_body_segment(
        Path(stash_map[_MOD_REL]).read_text(encoding="utf-8"), unit
    )
    dec = decompose_function_body(func_src, _BUDGET)
    return desc, stash_map, unit, dec["segments"]


def test_oversized_driver_retries_whole_unit_on_test_failure(tmp_path):
    # First whole-unit attempt produces a body that LANDS + parses but FAILS the
    # unit tests (returns the wrong value); the driver must restore the stub and
    # regenerate. Second attempt emits the correct segments -> accepted.
    desc, stash_map, unit, segments = _segs(tmp_path)
    n = len(segments)
    assert n >= 2, "sample must genuinely decompose"
    calls = {"n": 0}

    def gen(prompt):
        c = calls["n"]
        calls["n"] += 1
        attempt, idx = divmod(c, n)
        if attempt == 0:
            return "    pass" if idx < n - 1 else "    return 'WRONG'"
        return segments[idx]

    res = _loop.reconstruct_oversized_unit(
        desc, unit, _MOD_REL, stash_map,
        gen_fn=gen, config={"rebuild": {"unit_byte_budget": _BUDGET}}, commit=False,
    )
    assert res["body_landed"] is True
    assert res["tests_passed"] is True
    assert res["attempts"] == 2, "must retry the whole unit after a test failure"
    assert calls["n"] == 2 * n
    assert _loop.has_notimplemented(desc.output_dir / _MOD_REL, "normalize") is False


def test_oversized_driver_retries_unparseable_segment(tmp_path):
    # The first emission for segment 0 is syntactically broken (an unclosed
    # paren); the driver must regenerate that segment (not abort the unit) and
    # still land on the first whole-unit attempt.
    desc, stash_map, unit, segments = _segs(tmp_path)
    n = len(segments)
    state = {"seg": 0, "injected_bad": False}
    calls = {"n": 0}

    def gen(prompt):
        calls["n"] += 1
        if state["seg"] == 0 and not state["injected_bad"]:
            state["injected_bad"] = True
            return "    return ("  # unparseable in accumulated context
        seg = segments[state["seg"]]
        state["seg"] += 1
        return seg

    res = _loop.reconstruct_oversized_unit(
        desc, unit, _MOD_REL, stash_map,
        gen_fn=gen, config={"rebuild": {"unit_byte_budget": _BUDGET}}, commit=False,
    )
    assert res["body_landed"] is True
    assert res["attempts"] == 1, "a regenerated segment must not cost a whole-unit attempt"
    assert calls["n"] == n + 1, "exactly one extra (retried) segment generation"
    assert _loop.has_notimplemented(desc.output_dir / _MOD_REL, "normalize") is False
