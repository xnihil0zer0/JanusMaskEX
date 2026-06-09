"""Oracle for the wire_report PRODUCER on the live overseer dispatch path.

THE EDGE under test (not a unit of the producer in isolation): on a real
``run_chat_turn`` for a ``dispatch``-mode conversation parked at the ``WIRE_UP``
phase, the runtime producer must (1) actually CALL ``harness.wire_up.check_wired``
on the just-built module's recorded rel-path, (2) populate
``rec['procedure_artifacts']['wire_report']`` from its result, and (3) feed that
report to the REAL ``make_default_gate_runner`` gate so the FSM advances for a
wired module and stays Blocked for an orphan -- all within the SAME turn.

These drive the live path (real ``run_chat_turn`` + real ``make_default_gate_runner``)
with no agent/network (canned stream seams). ``check_wired`` is SPIED (not the
gate, not the producer) so we can both PROVE it is invoked on the live path and
control its verdict; the gate and the producer-to-gate wiring are exercised for
real. At HEAD (no producer) the spy is never called, so the spy-invocation and
phase-advance assertions go RED for the right reason.
"""
from __future__ import annotations

import json
from pathlib import Path

import harness.wire_up as wire_up
from harness.wire_up import WireResult
from overseer import turn_runner
from overseer.gate_runner import make_default_gate_runner
from overseer.procedure_state import ProcedureState, load_state, save_state
from overseer.session_store import SessionStore

CID = "conv-disp"
ORPHAN_REL = "overseer/__orphan_under_test__.py"
WIRED_REL = "overseer/__wired_under_test__.py"
LIVE_IMPORTER = "harness/orchestrator.py"


class _FakeParser:
    def __init__(self):
        self.events = []

    def handle_event(self, event):
        self.events.append(event)


def _canned_stream(session_id="sess-disp", text=("ok",)):
    lines = [json.dumps({"type": "system", "subtype": "init", "session_id": session_id})]
    for chunk in text:
        lines.append(json.dumps({"type": "content_block_delta",
                                 "delta": {"type": "text_delta", "text": chunk}}))
    return lines


def _seams(captured):
    def jail_builder(argv, **kw):
        captured["argv"] = list(argv)
        return list(argv)

    def env_builder(conversation, **kw):
        return {"X": "1"}

    def runner(cmd, *, env, stdin, **kw):
        captured["stdin"] = stdin
        return _canned_stream()

    return (runner, env_builder, jail_builder, _FakeParser())


def _dispatch_store(tmp_path, artifacts):
    store = SessionStore(tmp_path / "sessions.json")
    store.create(CID, current_mode="dispatch", model="opus", agent_backend="claude")
    store.append_turn(CID, {"role": "user", "content": "wire it"})
    # store.get returns the live record dict -> seed procedure_artifacts directly
    store.get(CID)["procedure_artifacts"] = dict(artifacts)
    return store


def _spy_check_wired(monkeypatch):
    calls = []

    def spy(repo_root, rel, **kw):
        calls.append(rel)
        if rel == WIRED_REL:
            return WireResult(wired=True, importers=[LIVE_IMPORTER], reason="", fix_hint="")
        return WireResult(wired=False, importers=[], reason="orphan", fix_hint="add an importer")

    monkeypatch.setattr(wire_up, "check_wired", spy)
    return calls


def _drive(tmp_path, store):
    state_dir = tmp_path / "state"
    save_state(CID, ProcedureState(phase="WIRE_UP", last_gate=None), state_dir=state_dir)
    gate_runner = make_default_gate_runner(tmp_path, state_dir)
    captured = {}
    turn_runner.run_chat_turn(
        store, CID, "wire it",
        config={}, repo_root=tmp_path, state_dir=state_dir, logs_dir=tmp_path / "logs",
        seams=_seams(captured), gate_runner=gate_runner,
    )
    return state_dir


def test_producer_invokes_check_wired_on_live_path(tmp_path, monkeypatch):
    # The single load-bearing assertion: the producer is REACHED on the live
    # run_chat_turn path and calls check_wired with the recorded module rel.
    calls = _spy_check_wired(monkeypatch)
    store = _dispatch_store(tmp_path, {"wire_module_rel": WIRED_REL})
    _drive(tmp_path, store)
    assert calls == [WIRED_REL]  # RED at HEAD: no producer => never invoked


def test_wired_module_populates_report_and_advances_past_wire_up(tmp_path, monkeypatch):
    calls = _spy_check_wired(monkeypatch)
    store = _dispatch_store(tmp_path, {"wire_module_rel": WIRED_REL})
    state_dir = _drive(tmp_path, store)
    # report reached procedure_artifacts...
    report = store.get(CID)["procedure_artifacts"].get("wire_report")
    assert report is not None and report.get("live_importers") == [LIVE_IMPORTER]
    # ...and the gate consequently advanced WIRE_UP -> RESTORE (the next phase).
    assert load_state(CID, state_dir=state_dir).phase == "RESTORE"
    assert WIRED_REL in calls


def test_orphan_module_populates_empty_report_and_blocks(tmp_path, monkeypatch):
    calls = _spy_check_wired(monkeypatch)
    store = _dispatch_store(tmp_path, {"wire_module_rel": ORPHAN_REL})
    state_dir = _drive(tmp_path, store)
    report = store.get(CID)["procedure_artifacts"].get("wire_report")
    assert report is not None and report.get("live_importers") == []  # populated, orphan
    st = load_state(CID, state_dir=state_dir)
    assert st.phase == "WIRE_UP"                       # held (Blocked)
    assert st.last_gate is not None and st.last_gate.ok is False
    assert ORPHAN_REL in calls


def test_no_recorded_module_fails_closed_without_invoking(tmp_path, monkeypatch):
    # Regression guard: with no wire_module_rel and no wire_report, the producer
    # must NOT run check_wired and the gate must fail closed (phase held).
    calls = _spy_check_wired(monkeypatch)
    store = _dispatch_store(tmp_path, {})
    state_dir = _drive(tmp_path, store)
    assert calls == []
    st = load_state(CID, state_dir=state_dir)
    assert st.phase == "WIRE_UP"
    assert st.last_gate is not None and st.last_gate.ok is False
