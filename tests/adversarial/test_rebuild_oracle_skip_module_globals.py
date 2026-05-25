"""Session #39 P1 (external pip sweep, ``inflection``): a MODULE-LEVEL function
that mutates module global state as a side effect (e.g. inflection's
``_irregular``: ``PLURALS.insert(...)``, returns ``None``) routes to the
tests-only oracle-skip path.

Such a helper is contractually a side-effecting INITIALIZER -- only ever called
at import time with valid inputs, never the arbitrary fuzz inputs the
merged==original differential oracle throws at it. Fuzzing it yields spurious
``exception_mismatch`` divergences (``caps('')`` -> IndexError on the original)
that no correct reconstruction can match, so the diff-fuzz gate must be skipped
and the authored pytest oracle is the honest gate."""

from __future__ import annotations

from pathlib import Path

import harness.rebuild.harvest as _harvest
import harness.rebuild.task as _task
from harness.rebuild.target import TargetDescriptor

_REPO = Path(__file__).resolve().parent.parent.parent

# Shaped after inflection: a module-level mutable list + a private helper that
# mutates it in place (mutating method call), plus a pure sibling.
_SRC = (
    "RULES = []\n"
    "TABLE = {}\n\n\n"
    "def _register(key: str, val: str) -> None:\n"
    "    RULES.insert(0, (key, val))\n"
    "    TABLE[key] = val\n\n\n"
    "def _rebind() -> None:\n"
    "    global RULES\n"
    "    RULES = []\n\n\n"
    "def transform(word: str) -> str:\n"
    "    return word.upper()\n\n\n"
    "_register('a', 'b')\n"
)


def _units():
    return {u.name: u for u in _harvest.harvest_module("m.py", _SRC)}


def test_mutating_method_call_on_global_flagged_impure():
    # ``_register`` calls RULES.insert(...) / TABLE[...] = ... on module globals.
    assert _units()["_register"].impure is True


def test_global_rebind_flagged_impure():
    # ``_rebind`` rebinds a ``global``-declared module name.
    assert _units()["_rebind"].impure is True


def test_pure_sibling_not_flagged():
    # ``transform`` only reads its arg -> stays on the differential-fuzz oracle.
    assert _units()["transform"].impure is False


def _desc(tmp_path) -> TargetDescriptor:
    (tmp_path / "m.py").write_text(_SRC, encoding="utf-8")
    return TargetDescriptor(
        name="m",
        source_root=tmp_path,
        modules=["m.py"],
        test_files=["test_m.py"],
        output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash",
        unit_test_selector="test_m.py -k {unit}",
    )


def test_module_global_mutator_oracle_skips(tmp_path):
    spec = _task.build_unit_task(
        descriptor=_desc(tmp_path),
        unit=_units()["_register"],
        module_rel="m.py",
        oracle_original_path=str(tmp_path / "stash" / "m.py"),
        sibling_signatures=[],
        unit_test_text="",
        parent_root=str(_REPO),
    )
    # tests-only: the merged==original oracle.py is NOT invoked, and the unit
    # routes through the fuzzer-bypass meta_task_type.
    assert "oracle.py" not in spec["verification_command"]
    assert spec.get("meta_task_type") == "harness_plumbing"


def test_pure_sibling_keeps_oracle(tmp_path):
    spec = _task.build_unit_task(
        descriptor=_desc(tmp_path),
        unit=_units()["transform"],
        module_rel="m.py",
        oracle_original_path=str(tmp_path / "stash" / "m.py"),
        sibling_signatures=[],
        unit_test_text="",
        parent_root=str(_REPO),
    )
    assert "oracle.py" in spec["verification_command"]
