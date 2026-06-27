"""RED oracle for the confidence_signals taint-proof merge (EDIT leaf B5).

build_confidence_signals gains an optional taint_proofs list, merged verbatim
like semantic_signals; resolve_signals threads ev['taint_proofs'] through. A
CodeQL taint_flow proof present -> a taint_flow/result:proof signal in the list
(drives ADMIT); absent -> unchanged. Live-path: the merge fires via resolve_signals.
"""
from ngv2.confidence_signals import build_confidence_signals, resolve_signals


_PROOF = {'tool': 'codeql', 'kind': 'taint_flow', 'result': 'proof',
          'rule': 'CWE-502', 'path': ['s.py:1 — src', 'k.py:9 — pickle.loads']}


def test_taint_proof_merged_into_signal_list():
    finding = {'id': 'deser_pickle', 'cwe': 'CWE-502'}
    signals = build_confidence_signals(finding, taint_proofs=[_PROOF])
    flows = [s for s in signals if s.get('kind') == 'taint_flow' and s.get('result') == 'proof']
    assert flows == [_PROOF]


def test_absent_taint_proofs_unchanged():
    finding = {'id': 'x', 'cwe': 'CWE-94'}
    base = build_confidence_signals(finding)
    with_none = build_confidence_signals(finding, taint_proofs=None)
    assert base == with_none
    assert all(s.get('kind') != 'taint_flow' for s in base)


def test_taint_and_semantic_both_merge():
    finding = {'id': 'x', 'cwe': 'CWE-502'}
    sem = [{'tool': 'ast', 'kind': 'formal_path', 'result': 'proof'}]
    signals = build_confidence_signals(finding, semantic_signals=sem, taint_proofs=[_PROOF])
    kinds = {s.get('kind') for s in signals}
    assert {'pattern', 'formal_path', 'taint_flow'} <= kinds


def test_resolve_signals_threads_taint_proofs_live_path():
    ev = {'finding': {'id': 'deser', 'cwe': 'CWE-502'}, 'taint_proofs': [_PROOF]}
    signals = resolve_signals(ev, ev['finding'])
    assert any(s.get('kind') == 'taint_flow' and s.get('result') == 'proof' for s in signals)


def test_non_dict_taint_proofs_are_skipped():
    finding = {'id': 'x'}
    signals = build_confidence_signals(finding, taint_proofs=['nope', None, _PROOF])
    flows = [s for s in signals if s.get('kind') == 'taint_flow']
    assert flows == [_PROOF]
