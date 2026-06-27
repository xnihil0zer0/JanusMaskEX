#!/usr/bin/env python3
"""
ADVERSARIAL DEMONSTRATION of NGv2 fix X1 (p11-xproc-middle-phase-impl).

Drives the REAL cross-process conductor path the way the dead-end manifested:
  - session starts at phase 'triage' with EMPTY evidence ({})
  - realistic carried-forward middle-phase worker artifacts (mirroring the
    <phase>_report.json rollup shape that workers/_runner.py + artifact_harvester
    roll up)
  - exercises persist -> plan_next_action -> build_evidence -> run_gates across
    the FOUR middle transitions triage->verify->novelty->report.

Each transition is contrasted against the DOCUMENTED BROKEN behavior:
  - was: plan_next_action re-spawns the SAME phase forever (count <= 0)
  - was: run_gates('triage','verify', build_evidence(state)) returned
         advance=False, blocked_by=['triage_result:missing_evidence']

Plus an ANTI-GAMING check: a target with a NOVEL source string + NOVEL package
name is fed; build_evidence must return the REAL provided source (containing the
nonce) and target_import_names DERIVED from the novel package (NOT a hardcoded
constant, NOT 'target_pkg').

Run with NGv2's venv:
  cd /home/xnihil0zer0/NobleGreedv2 && .venv/bin/python \
      /home/xnihil0zer0/JanusMaskJR/_autowork_scratch/x1_demo/demo_fsm_traversal.py
"""
import json
import os
import sys
import tempfile

# Ensure NGv2 is importable regardless of cwd.
NGV2_ROOT = "/home/xnihil0zer0/NobleGreedv2"
if NGV2_ROOT not in sys.path:
    sys.path.insert(0, NGV2_ROOT)

from ngv2.conductor_seams import build_default_seams
from ngv2 import transition_planner


class FakeDB:
    """In-memory SessionDB stand-in: get_session / save_session only."""

    def __init__(self, initial=None):
        self.sessions = {}
        if initial:
            self.sessions[initial["session_id"]] = dict(initial)

    def get_session(self, sid):
        row = self.sessions.get(sid)
        return dict(row) if row is not None else None

    def save_session(self, sid, state):
        self.sessions[sid] = dict(state)


def rollup(phase, result_key):
    """Realistic harvested <phase>_report.json rollup (worker artifact shape)."""
    return [{
        "kind": "report",
        "data": {
            "phase": phase,
            "n_artifacts": 1,
            "artifacts": [{
                "filename": "%s.json" % phase,
                "content": json.dumps({result_key: True}),
                "phase": phase,
            }],
        },
        "filename": "%s_report.json" % phase,
    }]


def hr(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def main():
    sid = "demo-session-1"

    # ---- PART A: middle-phase FSM traversal from EMPTY evidence -----------
    hr("PART A  -  Middle-phase FSM traversal (was: dead-end at triage)")
    db = FakeDB({"session_id": sid, "phase": "triage", "evidence": {}})
    seams = build_default_seams(sid, db, None, {"session_id": sid})

    persist = seams["persist"]
    plan = seams["plan"]               # transition_planner.plan_next_action
    build_evidence = seams["build_evidence"]
    run_gates = seams["run_gates"]     # gate_executor.run_gates

    # Each middle phase: (phase, count_field, gate result-key, next_phase)
    middle = [
        ("triage", "triaged", "triage_result", "verify"),
        ("verify", "verified", "verify_result", "poc"),
        ("novelty", "novelties", "novelty_result", "report"),
        ("report", "report_count", "report_artifact", "awaiting_submission"),
    ]

    # 1) Show the planner re-spawns BEFORE artifacts persisted (the old loop).
    state0 = db.get_session(sid)
    pre = plan(state0)
    print("\n[1] At phase=triage with EMPTY evidence, BEFORE any artifacts persisted:")
    print("    plan_next_action -> action=%r target=%r reason=%r"
          % (pre["action"], pre["target_phase"], pre["reason"]))
    print("    (DOCUMENTED BROKEN: stayed here forever -- count<=0 -> re-spawn triage)")
    assert pre["action"] == "spawn_stage" and pre["target_phase"] == "triage", \
        "expected the initial spawn of triage"

    chosen_actions = []
    all_ok = True

    for phase, count_field, result_key, next_phase in middle:
        print("\n[ phase=%s ] ----------------------------------------------" % phase)

        # Set the session to this phase (simulating arrival after a prior advance).
        st = db.get_session(sid)
        st["phase"] = phase
        db.save_session(sid, st)

        # 2) persist realistic harvested artifacts (carried-forward worker output).
        persist(sid, phase, rollup(phase, result_key))
        st = db.get_session(sid)
        cnt = st.get(count_field, 0)
        print("    persist(%s) -> state[%r]=%r  (was: never set -> stayed 0)"
              % (phase, count_field, cnt))
        if not cnt > 0:
            all_ok = False
            print("    !! REFUTED: %s count not set positive" % count_field)

        # 3) planner now ADVANCES instead of re-spawning.
        decision = plan(db.get_session(sid))
        chosen_actions.append((phase, decision["action"], decision["target_phase"]))
        print("    plan_next_action -> action=%r target=%r"
              % (decision["action"], decision["target_phase"]))
        if not (decision["action"] == "apply_gates"
                and decision["target_phase"] == next_phase):
            all_ok = False
            print("    !! REFUTED: planner did not choose apply_gates->%s "
                  "(still re-spawning?)" % next_phase)

        # 4) build_evidence from REAL carried state derives the gate key.
        ev = build_evidence(db.get_session(sid))
        print("    build_evidence -> %s=%r  (was: key absent)"
              % (result_key, ev.get(result_key)))
        if ev.get(result_key) is not True:
            all_ok = False
            print("    !! REFUTED: %s not derived from carried state" % result_key)

        # 5) run_gates returns advance=True with NO *_result:missing_evidence.
        g = run_gates(phase, next_phase, ev)
        print("    run_gates(%s->%s) -> advance=%r blocked_by=%r"
              % (phase, next_phase, g["advance"], g["blocked_by"]))
        was_blocked = "%s:missing_evidence" % result_key
        print("    (DOCUMENTED BROKEN: was advance=False blocked_by=[%r])" % was_blocked)
        if not g["advance"]:
            all_ok = False
            print("    !! REFUTED: transition did not advance")
        if any(b.endswith(":missing_evidence") for b in g["blocked_by"]):
            all_ok = False
            print("    !! REFUTED: a *_result:missing_evidence block survived")

        # Advance the recorded phase for the next loop iteration.
        seams["advance"](sid)

    print("\n[chosen action sequence across middle phases]:")
    for ph, act, tgt in chosen_actions:
        print("    %-8s -> %-12s (target=%s)" % (ph, act, tgt))
    print("\nEXPECTED post-fix: every row is 'apply_gates' (advance), NOT 'spawn_stage'.")

    # ---- PART B: anti-gaming novel-value check ---------------------------
    hr("PART B  -  Anti-gaming: novel target source + novel package name")
    with tempfile.TemporaryDirectory() as repo:
        nonce = "X1_SENTINEL_NONCE_a9f3c7"
        novel_pkg = "totally_unique_pkg_q8w2"
        # Real target source file referenced by the finding.
        with open(os.path.join(repo, "svc.py"), "w") as fh:
            fh.write("def my_endpoint(req):\n    # %s\n    run(req)\n" % nonce)
        # A real importable package physically present in the repo.
        pkg_dir = os.path.join(repo, novel_pkg)
        os.mkdir(pkg_dir)
        open(os.path.join(pkg_dir, "__init__.py"), "w").close()

        db2 = FakeDB()
        seams2 = build_default_seams("s2", db2, None, {"session_id": "s2"})
        finding = {
            "id": "F1", "evidence": ["svc.py:3"],
            "sink_name": "run", "expected_signature": "run(req)",
            "call_sites": ["run(req)"], "file": "svc.py",
        }
        state2 = {
            "repo": repo, "target": "svc",
            "prior_findings": [finding], "evidence": {},
        }
        ev2 = seams2["build_evidence"](state2)
        ts = ev2.get("target_source")
        names = ev2.get("target_import_names", [])
        print("    target_source (first 120 chars): %r" % ((ts or "")[:120]))
        print("    target_import_names: %r" % names)

        OLD_GAMED_LITERAL = (
            "def handler(req):\n    os.system(req.params['cmd'])\n    return 200\n"
        )
        antigaming_ok = True
        if ts is None or nonce not in ts:
            antigaming_ok = False
            print("    !! REFUTED: nonce %r NOT in target_source (not the real file)"
                  % nonce)
        else:
            print("    OK: real nonce present -> target_source is the genuine repo file")
        if ts == OLD_GAMED_LITERAL:
            antigaming_ok = False
            print("    !! REFUTED: target_source equals the ed91619 hardcoded literal")
        else:
            print("    OK: target_source != ed91619 hardcoded os.system handler literal")
        if novel_pkg not in names:
            antigaming_ok = False
            print("    !! REFUTED: novel package %r NOT derived into import names"
                  % novel_pkg)
        else:
            print("    OK: novel package %r derived from real repo" % novel_pkg)
        if "target_pkg" in names:
            antigaming_ok = False
            print("    !! REFUTED: unconditional 'target_pkg' literal survives")
        else:
            print("    OK: no unconditional 'target_pkg' literal appended")

    # ---- VERDICT ---------------------------------------------------------
    hr("VERDICT")
    final_phase = db.get_session(sid)["phase"]
    print("    final recorded phase after middle traversal: %r" % final_phase)
    verdict_pass = all_ok and antigaming_ok and final_phase == "awaiting_submission"
    print("    PART A (middle FSM advances, no missing_evidence): %s"
          % ("PASS" if all_ok else "FAIL"))
    print("    PART B (anti-gaming, real-derived values): %s"
          % ("PASS" if antigaming_ok else "FAIL"))
    print("\n>>> OVERALL: %s" % ("VERIFIED" if verdict_pass else "REFUTED"))
    return 0 if verdict_pass else 1


if __name__ == "__main__":
    sys.exit(main())
