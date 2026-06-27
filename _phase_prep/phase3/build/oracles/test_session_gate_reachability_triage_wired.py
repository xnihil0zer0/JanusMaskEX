"""RED oracle for the session_gate reachability-triage sub-gate (EDIT leaf C3).

The (triage -> verify) gate consults ngv2.reachability_triage when an LLM seam is
supplied in evidence: DROP -> ok=False error='out_of_scope'; MANUAL -> ok=False
error='manual_review_scope'; ADMIT/absent -> falls through to the existing
confidence path. Legacy callers (no seam) are unaffected. Live-path: the edge is
registered in _HANDLERS and reachable via gate_transition.
"""
from ngv2.session_gate import gate_transition, _HANDLERS


def _seam(classification):
    def complete(messages, **kwargs):
        return '{"classification": "%s", "justification": "x"}' % classification
    return complete


def test_triage_verify_edge_registered():
    assert ('triage', 'verify') in _HANDLERS


def test_out_of_scope_drops_at_gate():
    ev = {'finding': {'cwe': 'CWE-502', 'file': 'r.py', 'line': 9},
          'taint_path': ['s.py:1 — src', 'r.py:9 — pickle.loads'],
          'llm_complete': _seam('internal_only')}
    res = gate_transition('triage', 'verify', ev)
    assert res.ok is False
    assert res.error == 'out_of_scope'


def test_auth_gated_routes_manual_at_gate():
    ev = {'finding': {'cwe': 'CWE-918', 'file': 'r.py', 'line': 3},
          'taint_path': ['a:1', 'r.py:3'],
          'llm_complete': _seam('auth_gated')}
    res = gate_transition('triage', 'verify', ev)
    assert res.ok is False
    assert res.error == 'manual_review_scope'


def test_admit_falls_through_to_confidence_path():
    # ADMIT triage does NOT short-circuit; it proceeds to the confidence gate,
    # which (with no confidence signals wired) yields a non-out_of_scope result.
    ev = {'finding': {'cwe': 'CWE-502', 'file': 'r.py', 'line': 9},
          'taint_path': ['s.py:1', 'r.py:9'],
          'llm_complete': _seam('reachable_unauth')}
    res = gate_transition('triage', 'verify', ev)
    assert res.error not in ('out_of_scope', 'manual_review_scope')


def test_legacy_no_seam_unaffected():
    # no llm seam -> triage skipped, behaves exactly as before (confidence path)
    res = gate_transition('triage', 'verify', {'finding': {'cwe': 'CWE-94'}})
    assert res.error not in ('out_of_scope', 'manual_review_scope')
