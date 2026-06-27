"""RED oracle for ngv2.taint_path_signal -- CodeQL finding -> taint_flow proof.

Pure mapping: a path-bearing or located finding -> a taint_flow/result:proof
signal carrying the full source->sink path; a locationless/empty finding -> None
(no fabricated proof). Shape aligns with ngv2.semantic_signals taint proofs.
"""
from ngv2.taint_path_signal import to_taint_proof, proofs_from_findings


def test_path_bearing_finding_becomes_taint_flow_proof():
    finding = {
        'rule_id': 'py/unsafe-deserialization', 'cwe': ['CWE-502'],
        'file': 'app/runner.py', 'line': 88, 'message': 'pickle.loads on request body',
        'path': ['app/server.py:12 — request body', 'app/runner.py:88 — pickle.loads'],
    }
    proof = to_taint_proof(finding)
    assert proof['tool'] == 'codeql'
    assert proof['kind'] == 'taint_flow'
    assert proof['result'] == 'proof'
    assert proof['rule'] == 'CWE-502'
    assert proof['path'] == finding['path']


def test_located_finding_without_explicit_path_synthesizes_one_step():
    finding = {'rule_id': 'py/ssrf', 'cwe': ['CWE-918'],
               'file': 'x.py', 'line': 5, 'message': 'requests.get(url)'}
    proof = to_taint_proof(finding)
    assert proof is not None
    assert proof['path'] == ['x.py:5 — requests.get(url)']


def test_code_flow_nodes_are_flattened():
    finding = {'cwe': 'CWE-94', 'file': 's.py', 'line': 9,
               'code_flow': [{'file': 'a.py', 'line': 1, 'message': 'src'},
                             {'file': 's.py', 'line': 9, 'message': 'eval'}]}
    proof = to_taint_proof(finding)
    assert proof['path'] == ['a.py:1 — src', 's.py:9 — eval']


def test_locationless_or_empty_finding_is_not_a_proof():
    assert to_taint_proof({}) is None
    assert to_taint_proof({'rule_id': 'x', 'cwe': ['CWE-1']}) is None
    assert to_taint_proof(None) is None
    assert to_taint_proof('not a dict') is None


def test_proofs_from_findings_drops_non_proofs():
    findings = [
        {'file': 'a.py', 'line': 1, 'cwe': ['CWE-502'], 'message': 'm'},
        {'cwe': ['CWE-1']},  # no location -> dropped
    ]
    proofs = proofs_from_findings(findings)
    assert len(proofs) == 1
    assert proofs[0]['kind'] == 'taint_flow'
    assert proofs_from_findings('nope') == []
