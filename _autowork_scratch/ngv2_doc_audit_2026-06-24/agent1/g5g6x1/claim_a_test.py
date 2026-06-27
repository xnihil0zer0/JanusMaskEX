"""CLAIM A empirical test: do persist() set the 4 intermediate counters,
and does build_evidence() emit the 4 intermediate-gate keys, at current HEAD?

Run from /home/xnihil0zer0/NobleGreedv2 with PYTHONPATH=.
"""
import json
import sys

from ngv2 import conductor_seams


class FakeDB:
    """Minimal in-memory session store matching the seams' db contract."""

    def __init__(self):
        self.sessions = {}

    def get_session(self, sid):
        return dict(self.sessions.get(sid, {}))

    def save_session(self, sid, state):
        self.sessions[sid] = dict(state)


def make_artifact(phase, result_key, result_val):
    """A real-looking harvested rollup artifact for `phase`.

    Shape matches _rollup_inner: {'kind','data':{'phase','artifacts':[...]}}.
    The inner artifact carries content JSON with the gate result key.
    """
    inner = {
        'kind': phase + '_result',
        'content': json.dumps({result_key: result_val, 'note': 'real-looking'}),
    }
    return {
        'kind': phase + '_rollup',
        'data': {'phase': phase, 'artifacts': [inner]},
    }


def main():
    db = FakeDB()
    seams = conductor_seams.build_default_seams('sess1', db, None, {})
    persist = seams['persist']
    build_evidence = seams['build_evidence']

    sid = 'sess1'
    # seed an empty session row
    db.save_session(sid, {})

    cases = [
        ('triage', 'triaged', 'triage_result', True),
        ('verify', 'verified', 'verify_result', True),
        ('novelty', 'novelties', 'novelty_result', True),
        ('report', 'report_count', 'report_artifact', True),
    ]

    results = {}
    for phase, counter, gate_key, gate_val in cases:
        art = make_artifact(phase, gate_key, gate_val)
        persist(sid, phase, [art])
        state_after = db.get_session(sid)
        counter_val = state_after.get(counter)
        results[phase] = {
            'counter_field': counter,
            'counter_value_after_persist': counter_val,
            'counter_set': isinstance(counter_val, int) and counter_val > 0,
        }

    # Now build_evidence over the accumulated state
    final_state = db.get_session(sid)
    ev = build_evidence(final_state)

    gate_keys = ['triage_result', 'verify_result', 'novelty_result', 'report_artifact']
    emit = {k: (k in ev, ev.get(k)) for k in gate_keys}

    print('=== CLAIM A EMPIRICAL RESULT (HEAD) ===')
    print('--- persist sets the 4 intermediate counters? ---')
    all_counters_ok = True
    for phase, info in results.items():
        ok = info['counter_set']
        all_counters_ok = all_counters_ok and ok
        print(f"  persist(phase={phase!r}) -> state[{info['counter_field']!r}] = "
              f"{info['counter_value_after_persist']!r}  SET={ok}")

    print('--- build_evidence emits the 4 intermediate-gate keys? ---')
    all_emit_ok = True
    for k in gate_keys:
        present, val = emit[k]
        all_emit_ok = all_emit_ok and present
        print(f"  ev[{k!r}] present={present}  value={val!r}")

    print('--- FULL evidence keys ---')
    print('  ', sorted(ev.keys()))

    verdict_counters = 'ALL-4-SET' if all_counters_ok else 'NOT-ALL-SET'
    verdict_emit = 'ALL-4-EMITTED' if all_emit_ok else 'NOT-ALL-EMITTED'
    print('=== ONE-LINE VERDICT ===')
    print(f"persist_counters={verdict_counters}  build_evidence_gate_keys={verdict_emit}")

    # Also test the run_gates triage gate would NOT see missing_evidence
    # (the doc's specific symptom). We feed ev into run_gates(triage->verify).
    try:
        from ngv2 import gate_executor
        # find a triage->verify gate result if exposed; just sanity-check that
        # triage_result True is present (the prerequisite the gate checks).
        print('=== triage->verify prerequisite ===')
        print(f"  triage_result in ev = {'triage_result' in ev}, value={ev.get('triage_result')!r}")
    except Exception as e:
        print('  (gate_executor import skipped:', e, ')')


if __name__ == '__main__':
    main()
