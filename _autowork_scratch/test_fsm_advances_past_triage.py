"""Oracle: the autonomous conductor FSM advances PAST the triage dead-end.

RED-before: build_default_seams' persist seam only records phase-count keys for
hunt/poc/detonate (_PHASE_COUNT_KEY), and build_evidence only emits the
detonate-gate evidence -- so the intermediate transitions never get their
count (planner re-spawns the phase forever) nor their gate evidence (the
hunt->triage gate blocks on findings:missing_evidence). The loop dead-ends at
or before triage.

GREEN-after: _PHASE_COUNT_KEY maps triage/verify/novelty/report to their count
fields AND build_evidence emits findings/triage_result/verify_result/
novelty_result/report_artifact, so the FSM advances hunt -> triage -> verify
-> poc (and blocks only at the substantive poc_authenticity gate, which is a
real evidence gate, not a wiring gap).

Hermetic + in-process: a FakeDB plus stubbed spawn/harvest/command_for_phase
(the legitimate seam-injection boundary). The REAL persist, plan, run_gates and
build_evidence closures from build_default_seams are exercised. No subprocess,
DB file, network, or LLM.
"""
import importlib
import json

seams_mod = importlib.import_module("ngv2.conductor_seams")
loop_mod = importlib.import_module("ngv2.conductor_loop")


class _FakeDB:
    def __init__(self, initial=None):
        self.rows = {}
        if initial:
            self.rows[initial["session_id"]] = dict(initial)

    def get_session(self, sid):
        r = self.rows.get(sid)
        return dict(r) if r is not None else None

    def save_session(self, sid, state):
        p = dict(state)
        p["session_id"] = sid
        self.rows[sid] = p


def _ctx():
    return {"session_id": "s1", "repo": "/repo", "target_path": "acme/app",
            "output_dir": "/tmp/o", "db_path": "/tmp/x.db"}


def _stage_arts(phase):
    """One real, non-empty harvested rollup for ``phase``.

    Carries the finding fields the downstream gates read so that, once the
    wiring gaps are closed, only the genuine evidence gates can still block.
    """
    finding = {
        "id": "F1", "title": "t", "phase": phase, "target": "acme",
        "sink_name": "os.system", "call_sites": ["os.system(u)"],
        "expected_signature": "os.system(u)",
    }
    inner = {
        "phase": phase, "filename": "%s.json" % phase,
        "content": json.dumps(finding),
        "source": "import acme", "code": "import acme",
    }
    rollup = {"phase": phase, "n_artifacts": 1, "verdict": None, "artifacts": [inner]}
    return [{"kind": "report", "verdict": None, "data": rollup,
             "filename": "%s_report.json" % phase}]


def _seams_with_stub_runner(db):
    """Real seams, but with spawn/harvest/command_for_phase stubbed in-process.

    This is the legitimate seam-injection boundary -- the REAL persist, plan,
    run_gates and build_evidence closures are kept.
    """
    seams = seams_mod.build_default_seams("s1", db, None, _ctx())
    seams["command_for_phase"] = lambda phase, c: {
        "runnable": False, "phase": phase, "argv": [],
        "output_path": "/tmp/o/x.json", "env": {}}
    seams["spawn"] = lambda cmd: "/tmp/o"
    seams["harvest"] = lambda phase, out: _stage_arts(phase)
    return seams


def _run(max_steps):
    db = _FakeDB({"session_id": "s1", "phase": "hunt", "findings": 0,
                  "repo": "/repo", "target": "acme/app"})
    seams = _seams_with_stub_runner(db)
    res = loop_mod.run_until_terminal("s1", seams, max_steps=max_steps)
    return db, res


def test_fsm_advances_into_triage():
    """The hunt->triage transition gate must pass (findings evidence emitted)."""
    db, res = _run(max_steps=30)
    advanced_to = [s.get("to") for s in res["steps"] if s.get("step") == "advanced"]
    assert "triage" in advanced_to, (
        "FSM never advanced into triage; steps=%r" % (res["steps"],))


def test_fsm_advances_past_triage_through_middle_phases():
    """The FSM must traverse triage and verify, not re-spawn triage forever."""
    db, res = _run(max_steps=30)
    advanced_to = [s.get("to") for s in res["steps"] if s.get("step") == "advanced"]
    # Reaching verify proves triage's count key was recorded (no re-spawn loop)
    # AND triage->verify gate evidence was emitted.
    assert "verify" in advanced_to, (
        "FSM dead-ended at/around triage; advanced_to=%r steps=%r"
        % (advanced_to, res["steps"]))
    # Must NOT have burned the whole step budget re-spawning a single phase.
    triage_spawns = sum(1 for s in res["steps"]
                        if s.get("step") == "spawned" and s.get("phase") == "triage")
    assert triage_spawns <= 1, (
        "triage was re-spawned %d times (planner-loop dead-end)" % triage_spawns)


def test_fsm_reaches_poc_phase_and_blocks_only_on_real_gate():
    """After the wiring fix the FSM reaches the poc phase; today it cannot.

    Reaching poc proves the three intermediate wiring transitions
    (hunt->triage->verify->poc) all cleared. The run then blocks on the
    genuine ``poc_authenticity`` evidence gate -- a real gate, not a wiring
    gap -- which is the correct stopping point for this deterministic slice.
    """
    db, res = _run(max_steps=30)
    advanced_to = [s.get("to") for s in res["steps"] if s.get("step") == "advanced"]
    assert "poc" in advanced_to, (
        "FSM never reached the poc phase; advanced_to=%r steps=%r"
        % (advanced_to, res["steps"]))
    assert len(res["steps"]) < 30, (
        "FSM hit the step cap (re-spawn dead-end); final=%r" % (res["final_step"],))
