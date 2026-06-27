"""ngv2.taint_path_signal -- map a CodeQL taint finding to a structural proof.

Stage-2 of the cascade emits CodeQL interprocedural taint findings; this pure
adapter turns each into the ``taint_flow`` proof shape that
``ngv2.semantic_signals`` already produces and ``ngv2.confidence_signals`` folds
into ``compute_confidence`` (a ``taint_flow``/``result: proof`` signal drives the
ADMIT band). A finding with no source->sink path and no location is NOT a proof
and maps to ``None`` -- nothing here can fabricate a path.

Pure, stdlib-only, deterministic. No network, clock, randomness, or subprocess.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
__all__ = ['to_taint_proof', 'proofs_from_findings']

def _first_cwe(finding: Dict[str, Any]) -> Optional[str]:
    cwe = finding.get('cwe')
    if isinstance(cwe, (list, tuple)):
        return cwe[0] if cwe else None
    if isinstance(cwe, str) and cwe:
        return cwe
    return finding.get('rule') or finding.get('rule_id')

def _normalize_path(finding: Dict[str, Any]) -> List[str]:
    """Build a ``["file:line — message", ...]`` source->sink path, or []."""
    explicit = finding.get('path')
    if isinstance(explicit, (list, tuple)) and explicit:
        steps = [str(s) for s in explicit if s is not None and str(s).strip()]
        if steps:
            return steps
    flows = finding.get('code_flow') or finding.get('codeFlows') or finding.get('flow')
    if isinstance(flows, (list, tuple)) and flows:
        steps = []
        for node in flows:
            if isinstance(node, dict):
                loc = '%s:%s' % (node.get('file', ''), node.get('line', 0))
                msg = node.get('message', '')
                steps.append(('%s — %s' % (loc, msg)).strip(' —'))
            elif node is not None and str(node).strip():
                steps.append(str(node))
        if steps:
            return steps
    file_uri = finding.get('file')
    if file_uri:
        line = finding.get('line', 0)
        message = finding.get('message', '')
        return [('%s:%s — %s' % (file_uri, line, message)).strip(' —')]
    return []

def to_taint_proof(finding: Any) -> Optional[Dict[str, Any]]:
    """Map one CodeQL finding to a ``taint_flow`` proof, or ``None``.

    Returns ``None`` for a non-dict, an empty finding, or a finding with neither
    a path nor a location (so a locationless / fabricated result yields no proof).
    """
    if not isinstance(finding, dict) or not finding:
        return None
    path = _normalize_path(finding)
    if not path:
        return None
    return {'tool': 'codeql', 'kind': 'taint_flow', 'result': 'proof', 'rule': _first_cwe(finding), 'cwe': _first_cwe(finding), 'file': finding.get('file'), 'line': finding.get('line', 0), 'path': path}

def proofs_from_findings(findings: Any) -> List[Dict[str, Any]]:
    """Map a list of CodeQL findings to taint proofs, dropping non-proofs."""
    proofs: List[Dict[str, Any]] = []
    if not isinstance(findings, (list, tuple)):
        return proofs
    for finding in findings:
        proof = to_taint_proof(finding)
        if proof is not None:
            proofs.append(proof)
    return proofs