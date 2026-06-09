"""Wiring oracle: mode_set refuses switching modes mid-procedure.

The procedure machine's rule -- "while a mode's procedure is mid-sequence the
overseer may NOT change modes except an always-available abort to observe" -- is
enforced by mode_set reading the conversation's active phase
(rec['procedure_phase'], set by turn_runner) and gating via mode_gate.can_switch.
Once the phase is COMPLETE (or absent) the pre-existing behavior resumes.
"""
from overseer.session_store import SessionStore
from overseer.web_api import OverseerWebApi


def _api(tmp_path):
    store = SessionStore(tmp_path / "s.json")
    return OverseerWebApi(store), store


def _conv(store, mode="brief-author", phase=None):
    store.create("c1", current_mode=mode, model="opus", agent_backend="claude")
    if phase is not None:
        store.get("c1")["procedure_phase"] = phase
    return "c1"


def test_mid_procedure_refuses_other_mode(tmp_path):
    api, store = _api(tmp_path)
    cid = _conv(store, "brief-author", phase="SCOPE")
    res = api.mode_set(cid, "dispatch")              # dispatch needs no unlock
    assert res["ok"] is False
    assert store.get(cid)["current_mode"] == "brief-author"


def test_mid_procedure_allows_abort_to_observe(tmp_path):
    api, store = _api(tmp_path)
    cid = _conv(store, "brief-author", phase="SCOPE")
    assert api.mode_set(cid, "observe")["ok"] is True


def test_mid_procedure_allows_noop_current(tmp_path):
    api, store = _api(tmp_path)
    cid = _conv(store, "brief-author", phase="SCOPE")
    assert api.mode_set(cid, "brief-author")["ok"] is True


def test_complete_phase_unlocks_switching(tmp_path):
    api, store = _api(tmp_path)
    cid = _conv(store, "brief-author", phase="COMPLETE")
    assert api.mode_set(cid, "dispatch")["ok"] is True


def test_no_procedure_phase_behaves_as_before(tmp_path):
    api, store = _api(tmp_path)
    cid = _conv(store, "observe", phase=None)
    assert api.mode_set(cid, "dispatch")["ok"] is True
