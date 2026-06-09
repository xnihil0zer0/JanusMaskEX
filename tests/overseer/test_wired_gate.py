"""RED oracle for the `wired` GateResult function (epic: wire_up_phase, leaf: wired-gate-fn).

Contract: overseer/gates.py exposes a pure `wired(report) -> GateResult` that is
ok=False when the report shows zero live importers (an ORPHAN) and ok=True otherwise,
and it is exported via __all__. This is the pure gate the WIRE_UP phase binds.
"""
import overseer.gates as gates
from overseer.gates import wired, GateResult


def test_wired_exported():
    assert "wired" in gates.__all__


def test_zero_importers_is_not_ok():
    r = wired({"live_importers": []})
    assert isinstance(r, GateResult)
    assert r.ok is False
    assert r.fix_hint  # actionable: how to add a live importer


def test_some_importers_is_ok():
    r = wired({"live_importers": ["harness/orchestrator.py"]})
    assert r.ok is True


def test_missing_importers_key_is_not_ok():
    # A report that never measured importers must fail closed, not pass.
    r = wired({})
    assert r.ok is False
