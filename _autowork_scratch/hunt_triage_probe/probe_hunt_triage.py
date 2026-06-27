"""Adversarial probe: does a REAL run_hunt seeded at phase `hunt` advance
hunt->triage after X1 (eb113f5)?

Drives the LIVE NGv2 conductor seams:
  persist (real hunt artifacts) -> load_state -> plan_next_action
  -> build_evidence -> run_gates('hunt','triage', evidence)

No stubs of build_evidence/run_gates/plan: those are the real ngv2 modules.
Only the DB is an in-memory stand-in matching the SessionDB get/save contract
(exactly the FakeDB the X1 oracle uses).

Run in NGv2 .venv:
  cd /home/xnihil0zer0/NobleGreedv2 && .venv/bin/python \
    /home/xnihil0zer0/JanusMaskJR/_autowork_scratch/hunt_triage_probe/probe_hunt_triage.py
"""
import json
import sys

from ngv2.conductor_seams import build_default_seams
from ngv2 import transition_planner


class FakeDB:
    """In-memory SessionDB stand-in (get_session/save_session) -- same as the X1 oracle."""

    def __init__(self, initial=None):
        self.sessions = {}
        if initial:
            self.sessions[initial['session_id']] = dict(initial)

    def get_session(self, sid):
        row = self.sessions.get(sid)
        return dict(row) if row is not None else None

    def save_session(self, sid, state):
        self.sessions[sid] = dict(state)


def main():
    sid = 's1'
    # Realistic carried-forward HUNT artifacts: the rollup shape the harvester
    # returns and the hunt worker emits (data.phase=='hunt', inner content is a
    # Finding-shaped dict). This is EXACTLY what `harvest('hunt', out)` yields.
    sentinel = 'SENTINEL_FINDING_PROBE_0xDEADBEEF'
    finding = {
        'id': 'F1',
        'title': sentinel,
        'category': 'CWE-89',
        'severity': 'high',
        'description': 'sql concat sink',
        'evidence': ['svc.py:2'],
        'sink_name': 'os.system',
    }
    hunt_arts = [{
        'kind': 'report',
        'data': {
            'phase': 'hunt',
            'n_artifacts': 1,
            'artifacts': [{
                'filename': 'hunt.json',
                'content': json.dumps(finding),
                'phase': 'hunt',
            }],
        },
        'filename': 'hunt_report.json',
    }]

    db = FakeDB({'session_id': sid, 'phase': 'hunt', 'repo': '/tmp/nonexistent_repo',
                 'target': 'svc', 'evidence': {}})
    seams = build_default_seams(sid, db, None, {'session_id': sid})

    # 1. persist the REAL hunt artifacts (this is the carry-forward seam).
    seams['persist'](sid, 'hunt', hunt_arts)
    state = seams['load_state'](sid)

    print('=== STATE AFTER persist(hunt) ===')
    print('phase                 :', state.get('phase'))
    print('findings (count key)  :', state.get('findings'))
    print('prior_findings present:', bool(state.get('prior_findings')))
    print('prior_findings[0].title:',
          (state.get('prior_findings') or [{}])[0].get('title'))

    # 2. plan_next_action over the REAL planner (carried via seams['plan']).
    plan = seams['plan'](state)
    print()
    print('=== plan_next_action(state) ===')
    print('action       :', plan.get('action'))
    print('target_phase :', plan.get('target_phase'))
    print('reason       :', plan.get('reason'))

    # 3. build_evidence over the REAL post-X1 closure.
    ev = seams['build_evidence'](state)
    print()
    print('=== build_evidence(state) -> evidence ===')
    print("'findings' in evidence:", 'findings' in ev)
    print("evidence.get('findings'):", repr(ev.get('findings')))
    print('evidence keys           :', sorted(ev.keys()))

    # 4. run_gates('hunt','triage', evidence) over the REAL gate executor.
    g = seams['run_gates']('hunt', plan.get('target_phase') or 'triage', ev)
    print()
    print('=== run_gates(hunt -> triage, evidence) ===')
    print('advance    :', g.get('advance'))
    print('blocked_by :', g.get('blocked_by'))
    print('results    :', g.get('results'))

    # 5. Drive the FULL conductor step the way run_hunt would, from phase=hunt.
    db2 = FakeDB({'session_id': sid, 'phase': 'hunt', 'repo': '/tmp/nonexistent_repo',
                  'target': 'svc', 'evidence': {}})
    seams2 = build_default_seams(sid, db2, None, {'session_id': sid})
    seams2['persist'](sid, 'hunt', hunt_arts)
    step = seams2['run_conductor_step'](sid, seams2)
    print()
    print('=== run_conductor_step at phase=hunt (full step) ===')
    print('step result:', step)

    print()
    print('=== VERDICT ===')
    if g.get('advance') is True and not g.get('blocked_by'):
        print('REFUTED: hunt->triage ADVANCES (findings evidence derived).')
        return 0
    print('VERIFIED: hunt->triage DEAD-ENDS. blocked_by=%r; '
          "evidence['findings'] is %r (gate requires a truthy 'findings')."
          % (g.get('blocked_by'), ev.get('findings')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
