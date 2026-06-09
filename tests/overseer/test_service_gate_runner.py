"""Wiring oracle: OverseerService passes a REAL gate_runner into the turn.

This is the wire that makes the procedure FSM actually run in production:
turn_runner.run_chat_turn only runs the procedure step when gate_runner is not
None, and the only production caller is OverseerService. The service must build
overseer.gate_runner.make_default_gate_runner(repo_root, state_dir) once and pass
it on both the chat_send and chat_resend turn calls.
"""
from overseer.service import OverseerService
from overseer.gates import GateResult


def _cfg():
    return {"overseer": {"enabled": True, "default_mode": "observe",
                         "default_backend": "claude",
                         "store_path": "state/overseer/sessions.json",
                         "models": {"claude": ["opus"]}, "unlock_policy": {}}}


def _capturing_service(tmp_path, captured):
    def capture(store, cid, text, **kw):
        captured.clear()
        captured.update(kw)
        return {"ok": True, "text": "hi", "session_id": None, "tool_uses": []}
    return OverseerService(tmp_path / "state", _cfg(), run_turn_fn=capture)


def test_chat_send_passes_a_real_gate_runner(tmp_path):
    captured = {}
    svc = _capturing_service(tmp_path, captured)
    svc.chat_send({"text": "hello"})
    gr = captured.get("gate_runner")
    assert gr is not None and callable(gr)


def test_chat_resend_passes_a_real_gate_runner(tmp_path):
    captured = {}
    svc = _capturing_service(tmp_path, captured)
    out = svc.chat_send({"text": "first"})
    cid = out[1]["conversation_id"]
    captured.clear()
    svc.chat_resend({"conversation_id": cid})
    gr = captured.get("gate_runner")
    assert gr is not None and callable(gr)


def test_service_exposes_a_gate_runner_attribute(tmp_path):
    svc = OverseerService(tmp_path / "state", _cfg())
    assert callable(svc._gate_runner)


def test_default_gate_runner_resolves_real_gates(tmp_path):
    # not a stub: posture_ok on an unlocked state_dir fails mentioning full_stop.
    svc = OverseerService(tmp_path / "state", _cfg())
    res = svc._gate_runner("push", "POSTURE", {}, tmp_path / "state")
    assert isinstance(res, GateResult) and res.ok is False and "full_stop" in res.reason
