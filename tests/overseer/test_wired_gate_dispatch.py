"""RED wiring oracle: the production gate_runner DISPATCHES the WIRE_UP phase's
'wired' gate label to overseer.gates.wired (epic wire_up_phase, leaf wired-gate-dispatch).

This closes the runtime gap noted when the FSM phase landed: gate_label_for already
resolves ('dispatch','WIRE_UP') -> 'wired' (the registry binding), but make_default_gate_runner's
_run_gate had no 'wired' branch, so the overseer dispatch FSM never actually RAN the
reachability gate at WIRE_UP. This is a WIRING assertion -- it drives the live public
gate_runner and asserts the (phase -> label -> gates.wired) edge fires, not gates.wired in
isolation.
"""
from overseer.gate_runner import make_default_gate_runner, gate_label_for
from overseer.gates import GateResult


def test_wire_up_phase_resolves_to_wired_label():
    assert gate_label_for('dispatch', 'WIRE_UP') == 'wired'


def _runner(tmp_path):
    return make_default_gate_runner(repo_root='.', state_dir=tmp_path)


def test_gate_runner_routes_orphan_report_to_not_ok(tmp_path):
    gr = _runner(tmp_path)
    res = gr('dispatch', 'WIRE_UP', {'procedure_artifacts': {'wire_report': {'live_importers': []}}})
    assert isinstance(res, GateResult)
    assert res.ok is False


def test_gate_runner_routes_wired_report_to_ok(tmp_path):
    gr = _runner(tmp_path)
    res = gr('dispatch', 'WIRE_UP',
             {'procedure_artifacts': {'wire_report': {'live_importers': ['harness/orchestrator.py']}}})
    assert isinstance(res, GateResult)
    assert res.ok is True


def test_gate_runner_wired_missing_report_fails_closed(tmp_path):
    # No wire_report recorded -> the gate must fail closed with an actionable hint,
    # never silent-pass (mirrors the other backed gates).
    gr = _runner(tmp_path)
    res = gr('dispatch', 'WIRE_UP', {})
    assert res.ok is False
    assert res.fix_hint
