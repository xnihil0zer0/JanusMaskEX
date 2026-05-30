"""B2 (DYNAMIC_SIGNATURE_PROBING): the generated unit-task spec's interface must
reflect the ACTUAL oracle signature + boundary/exception behavior, PROBED from the
trusted original at task-build time, with a strict fail-safe fallback to the static
spec.

Pins three properties:
  (i)   for an original oracle with a known signature, build_unit_task folds the
        PROBED signature + boundary contracts into the spec text;
  (ii)  when probing fails / raises (missing original, oracle-skip unit, broken
        module), build_unit_task still returns a valid spec (static fallback);
  (iii) build_unit_task's contract / return shape is unchanged either way.
"""

from __future__ import annotations

from pathlib import Path

import harness.rebuild.task as task
from harness.rebuild.harvest import harvest_module
from harness.rebuild.target import TargetDescriptor


def _descriptor(tmp_path, *, test_files=None, selector=""):
    return TargetDescriptor(
        name="m", source_root=tmp_path / "src", modules=["m.py"],
        test_files=test_files or [], output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash", unit_test_selector=selector,
    )


def _unit(src, name):
    return [
        u for u in harvest_module("m.py", src, include_methods=True) if u.name == name
    ][0]


# A pure, typed, deterministic oracle: probable. It RAISES on None (len(None)) and
# RETURNS on the empty/zero boundary values -- a contract the probe should observe.
_PURE_SRC = (
    'def shout(s: str) -> str:\n'
    '    """Uppercase a string, "!"-suffixed."""\n'
    '    return s.upper() + "!"\n'
)


def _write_stash(tmp_path, src):
    stash = tmp_path / "m.py.orig"
    stash.write_text(src, encoding="utf-8")
    return str(stash)


_REQUIRED_KEYS = {
    "task_id", "specification", "constraints", "files_touched",
    "verification_command",
}


def _assert_valid_spec(spec, unit):
    assert isinstance(spec, dict)
    assert _REQUIRED_KEYS.issubset(spec.keys())
    assert spec["specification"]  # never empty
    assert spec["constraints"]["function_signature"] == unit.signature
    assert spec["files_touched"] == ["m.py"]


# ---------------------------------------------------------------------------
# (i) PROBED signature + contracts land in the spec when the oracle is present.
# ---------------------------------------------------------------------------
def test_probe_records_observed_signature_and_contracts(tmp_path):
    unit = _unit(_PURE_SRC, "shout")
    orig = _write_stash(tmp_path, _PURE_SRC)
    spec = task.build_unit_task(
        descriptor=_descriptor(tmp_path), unit=unit, module_rel="m.py",
        oracle_original_path=orig, sibling_signatures=[], unit_test_text="",
        parent_root="/parent",
    )
    _assert_valid_spec(spec, unit)
    text = spec["specification"]
    assert "Boundary & Exception Contracts" in text
    # The PROBED signature is the real one, not just the static guess.
    assert "Observed signature: shout(s: str) -> str" in text
    # shout(None) -> None.upper() raises AttributeError; shout("") returns.
    assert "raises AttributeError" in text
    assert "-> returns" in text


def test_probe_helper_returns_section_directly(tmp_path):
    # Exercise the helper in isolation (top-level symbol, §3.10 sanctioned add).
    unit = _unit(_PURE_SRC, "shout")
    orig = _write_stash(tmp_path, _PURE_SRC)
    section = task.probe_oracle_contracts(orig, unit)
    assert section is not None
    assert "Observed signature: shout(s: str) -> str" in section


# ---------------------------------------------------------------------------
# (ii) FAIL-SAFE fallback: probing failures never break task-building.
# ---------------------------------------------------------------------------
def test_missing_original_falls_back_to_static(tmp_path):
    unit = _unit(_PURE_SRC, "shout")
    spec = task.build_unit_task(
        descriptor=_descriptor(tmp_path), unit=unit, module_rel="m.py",
        oracle_original_path="/no/such/path/m.py.orig", sibling_signatures=[],
        unit_test_text="", parent_root="/parent",
    )
    _assert_valid_spec(spec, unit)
    assert "Boundary & Exception Contracts" not in spec["specification"]
    assert task.probe_oracle_contracts("/no/such/path/m.py.orig", unit) is None


def test_empty_oracle_path_falls_back_to_static(tmp_path):
    unit = _unit(_PURE_SRC, "shout")
    spec = task.build_unit_task(
        descriptor=_descriptor(tmp_path), unit=unit, module_rel="m.py",
        oracle_original_path="", sibling_signatures=[], unit_test_text="",
        parent_root="/parent",
    )
    _assert_valid_spec(spec, unit)
    assert "Boundary & Exception Contracts" not in spec["specification"]


def test_broken_module_import_falls_back_to_static(tmp_path):
    # An original whose import raises at module scope must NOT crash task-building.
    broken = (
        'raise RuntimeError("import side-effect boom")\n'
        'def shout(s: str) -> str:\n    return s\n'
    )
    unit = _unit(broken, "shout")
    orig = _write_stash(tmp_path, broken)
    assert task.probe_oracle_contracts(orig, unit) is None
    spec = task.build_unit_task(
        descriptor=_descriptor(tmp_path), unit=unit, module_rel="m.py",
        oracle_original_path=orig, sibling_signatures=[], unit_test_text="",
        parent_root="/parent",
    )
    _assert_valid_spec(spec, unit)
    assert "Boundary & Exception Contracts" not in spec["specification"]


def test_impure_oracle_skip_unit_is_not_probed(tmp_path):
    # The brief's Non-Goal: do not probe impure/nondeterministic (oracle-skip) units.
    impure = (
        'import time\n'
        'def now(x: int) -> float:\n    """Now."""\n    return time.time() + x\n'
    )
    unit = _unit(impure, "now")
    assert getattr(unit, "impure", False)  # precondition: it IS oracle-skip
    orig = _write_stash(tmp_path, impure)
    assert task.probe_oracle_contracts(orig, unit) is None
    spec = task.build_unit_task(
        descriptor=_descriptor(tmp_path), unit=unit, module_rel="m.py",
        oracle_original_path=orig, sibling_signatures=[], unit_test_text="",
        parent_root="/parent",
    )
    _assert_valid_spec(spec, unit)
    assert "Boundary & Exception Contracts" not in spec["specification"]


def test_method_unit_is_not_probed(tmp_path):
    # A class method isn't resolvable as a bare module attribute -> no probe.
    src = (
        'class C:\n'
        '    def m(self, s: str) -> str:\n'
        '        """M."""\n        return s\n'
    )
    units = harvest_module("m.py", src, include_methods=True)
    method = [u for u in units if u.name == "m" and u.cls == "C"][0]
    orig = _write_stash(tmp_path, src)
    assert task.probe_oracle_contracts(orig, method) is None


# ---------------------------------------------------------------------------
# (iii) Return-shape parity: probing must not add/remove top-level spec keys.
# ---------------------------------------------------------------------------
def test_return_shape_unchanged_with_and_without_probe(tmp_path, monkeypatch):
    unit = _unit(_PURE_SRC, "shout")
    orig = _write_stash(tmp_path, _PURE_SRC)
    probed = task.build_unit_task(
        descriptor=_descriptor(tmp_path), unit=unit, module_rel="m.py",
        oracle_original_path=orig, sibling_signatures=[], unit_test_text="",
        parent_root="/parent",
    )
    # Disable ONLY the probe (keep the SAME oracle path so the vcmd is identical),
    # isolating the probe's effect to the specification text alone.
    monkeypatch.setattr(task, "probe_oracle_contracts", lambda *a, **k: None)
    static = task.build_unit_task(
        descriptor=_descriptor(tmp_path), unit=unit, module_rel="m.py",
        oracle_original_path=orig, sibling_signatures=[], unit_test_text="",
        parent_root="/parent",
    )
    # Only the specification TEXT differs; the key set + every other field match.
    assert set(probed.keys()) == set(static.keys()) == _REQUIRED_KEYS
    for k in _REQUIRED_KEYS - {"specification"}:
        assert probed[k] == static[k]
    assert "Boundary & Exception Contracts" in probed["specification"]
    assert "Boundary & Exception Contracts" not in static["specification"]
    # The static spec is a PREFIX of the probed one (probe is purely additive).
    assert probed["specification"].startswith(static["specification"])
