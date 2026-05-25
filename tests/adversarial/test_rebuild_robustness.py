"""C9.6 oracle/task robustness: impure->tests-only + sibling-body injection."""

from __future__ import annotations

from pathlib import Path

import harness.rebuild.harvest as _harvest
import harness.rebuild.task as _task
import harness.rebuild.loop as _loop
from harness.rebuild.target import TargetDescriptor

_REPO = Path(__file__).resolve().parent.parent.parent
_WIDGETS_REL = "widgets.py"
_WIDGETS = (_REPO / "samples" / "widgets" / "widgets.py").read_text(encoding="utf-8")


def _desc(tmp_path) -> TargetDescriptor:
    return TargetDescriptor(
        name="widgets",
        source_root=_REPO / "samples" / "widgets",
        modules=[_WIDGETS_REL],
        test_files=["test_widgets.py"],
        output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash",
        unit_test_selector="test_widgets.py -k {unit}",
    )


def _units():
    return {u.name: u for u in _harvest.harvest_module(_WIDGETS_REL, _WIDGETS)}


# ----- impure detection -----

def test_impure_flag_set_for_io_function():
    units = _units()
    assert units["file_size"].impure is True   # uses os.* (filesystem IO)
    assert units["double"].impure is False
    assert units["quadruple"].impure is False


def test_depth_validator_detected_impure():
    src = (_REPO / "harness" / "depth_validator.py").read_text(encoding="utf-8")
    units = {u.name: u for u in _harvest.harvest_module("depth_validator.py", src)}
    assert units["check_true_depth"].impure is True  # open + IO


# ----- oracle-skip path -----

def test_impure_unit_task_skips_oracle(tmp_path):
    units = _units()
    spec = _task.build_unit_task(
        descriptor=_desc(tmp_path),
        unit=units["file_size"],
        module_rel=_WIDGETS_REL,
        oracle_original_path="/abs/stash/widgets.py.orig",
        sibling_signatures=[],
        unit_test_text="assert True",
        parent_root=str(_REPO),
    )
    vcmd = spec["verification_command"]
    assert "oracle.py" not in vcmd, "impure unit must take the tests-only path"
    assert "pytest" in vcmd
    # impure -> fuzzer-bypass so out-of-spec agent divergence can't trigger
    # a meaningless decomposition; the scoped tests gate the commit.
    assert spec.get("meta_task_type") == "harness_plumbing"
    from harness.orchestrator import BYPASS_FUZZER_TYPES
    assert spec["meta_task_type"] in BYPASS_FUZZER_TYPES


def test_pure_unit_task_keeps_oracle(tmp_path):
    units = _units()
    spec = _task.build_unit_task(
        descriptor=_desc(tmp_path),
        unit=units["double"],
        module_rel=_WIDGETS_REL,
        oracle_original_path="/abs/stash/widgets.py.orig",
        sibling_signatures=[],
        unit_test_text="assert True",
        parent_root=str(_REPO),
    )
    assert "oracle.py" in spec["verification_command"]
    assert "meta_task_type" not in spec  # pure units keep the full dual-agent + oracle gate


# ----- sibling-body injection -----

def test_sibling_bodies_injected_into_spec(tmp_path):
    units = _units()
    spec = _task.build_unit_task(
        descriptor=_desc(tmp_path),
        unit=units["quadruple"],
        module_rel=_WIDGETS_REL,
        oracle_original_path="/abs/stash/widgets.py.orig",
        sibling_signatures=["def double(x: int) -> int:"],
        sibling_bodies=["def double(x: int) -> int:\n    return x * 2"],
        unit_test_text="assert quadruple(3) == 12",
        parent_root=str(_REPO),
    )
    spec_text = spec["specification"]
    assert "VERBATIM" in spec_text
    assert "return x * 2" in spec_text  # the real callee body, not just a signature


def test_extract_unit_source_reads_real_body(tmp_path):
    mod = tmp_path / "widgets.py"
    mod.write_text(_WIDGETS, encoding="utf-8")
    src = _loop.extract_unit_source(mod, "double")
    assert src is not None
    assert "return x * 2" in src
    # a stripped stub returns None
    from harness.rebuild import strip as _strip
    mod.write_text(_strip.strip_source(_WIDGETS), encoding="utf-8")
    assert _loop.extract_unit_source(mod, "double") is None


def test_reconstruct_all_resume_skips_real_bodies(tmp_path, monkeypatch):
    # If a body is already real and resume=True, reconstruct_unit is never called.
    desc = _desc(tmp_path)
    from harness.rebuild import strip as _strip
    _strip.materialize_skeleton(desc)
    # make `double` real in the output (write the full real module; only=double)
    out_mod = desc.output_dir / _WIDGETS_REL
    out_mod.write_text(_WIDGETS, encoding="utf-8")
    assert _loop.has_notimplemented(out_mod, "double") is False
    called = []
    monkeypatch.setattr(
        _loop, "reconstruct_unit",
        lambda *a, **k: called.append(k) or {"unit": "x", "body_landed": True, "outcome": "accepted"},
    )
    _loop.reconstruct_all(desc, only="double", init=False, resume=True)
    assert called == [], "resume must skip the already-real `double` body"
