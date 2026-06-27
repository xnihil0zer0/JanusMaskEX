---
interfaces: "creates NEW ngv2/taint_path_signal.py exposing to_taint_proof(finding)->dict|None and proofs_from_findings(findings)->list — maps a CodeQL taint finding to the taint_flow/result:proof signal shape ngv2.confidence_signals folds into compute_confidence"
dependencies: []
meta_task_type: data_model
spec_author: "Phase-III BUILD-PREP agent (JanusMask)"
spec_reviewed_by: "owner (CodeQL CLI use APPROVED 2026-06-12)"
---

# Title

ngv2/taint_path_signal.py — NEW pure adapter: CodeQL taint finding → {'tool':'codeql','kind':'taint_flow','result':'proof','rule':cwe,'path':[...]}; a locationless/empty finding → None (no fabricated proof).

# Scope

CREATE the NEW single-file module `ngv2/taint_path_signal.py`. Stage-2 emits CodeQL interprocedural taint findings; this pure adapter turns each into the `taint_flow` proof shape that `ngv2.semantic_signals` already produces and `ngv2.confidence_signals` merges (a taint_flow/proof signal drives the ADMIT band). A finding with an explicit path, a code_flow node list, or a bare file:line location becomes a proof carrying the full source→sink path; a finding with neither path nor location → None. Pure, stdlib-only, deterministic — nothing here can manufacture a path.

DISPATCH DIRECTIVE — PATCH FORMAT (MANDATORY — WHOLE-FILE): this is a NEW single-file module, so emit the COMPLETE file for `ngv2/taint_path_signal.py` (whole-file emission — NEVER a `__JANUSMASK_PATCHES__` symbol patch, never a manifest, never a dotted qualname). Reproduce it BYTE-FOR-BYTE exactly as follows:

```python
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
    return {
        'tool': 'codeql',
        'kind': 'taint_flow',
        'result': 'proof',
        'rule': _first_cwe(finding),
        'cwe': _first_cwe(finding),
        'file': finding.get('file'),
        'line': finding.get('line', 0),
        'path': path,
    }


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
```

POST-EMIT SELF-CHECK (mandatory): the module imports only `typing`; a finding with no path and no file → None; the proof dict carries keys tool/kind/result/rule/cwe/file/line/path; no network/clock/subprocess import.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the committed oracle is keyed to it): `task_id`: `ngv2_taint_path_signal`. meta_task_type=`data_model` (NEW pure module — single-file whole-file emission, no production-harness edit). priority: high. dependencies: []. working_dir: "/home/xnihil0zer0/NobleGreedv2". files_touched: `["ngv2/taint_path_signal.py"]` ONLY. partial_edit semantics: WHOLE-FILE single-file emission per the DISPATCH DIRECTIVE — the DISPATCH DIRECTIVE block above (including the full pinned file content) MUST be copied VERBATIM into the task's `implementation_notes` so the blind worker sees it. verification_command: `python3 -m pytest -q tests/ngv2/test_taint_path_signal_wired.py` (CWD-relative — NO `cd`). The committed RED oracle tests/ngv2/test_taint_path_signal_wired.py is the authoritative acceptance contract — make it GREEN (5 tests); do NOT author new tests. `test_spec.regression_tests` MUST list at least two entries naming committed oracle cases: `test_path_bearing_finding_becomes_taint_flow_proof`, `test_located_finding_without_explicit_path_synthesizes_one_step`. `test_spec.edge_cases` (≥2, reflected in those test names): `test_locationless_or_empty_finding_is_not_a_proof`, `test_code_flow_nodes_are_flattened`, `test_proofs_from_findings_drops_non_proofs` — including the integration-style case `test_proofs_from_findings_drops_non_proofs`.

# Non-Goals

Do NOT call CodeQL or parse SARIF here (codeql_runner.parse_sarif already produces the finding dicts this consumes). Do NOT touch confidence_signals, semantic_signals, or any other module. Do NOT add network, clock, randomness, subprocess, or logging. Wiring this proof INTO confidence_signals is a separate EDIT leaf.

# Inputs

The committed oracle tests/ngv2/test_taint_path_signal_wired.py (RED — module absent). It pins: a path-bearing CWE-502 finding → taint_flow proof with the full path; a located finding without an explicit path → a synthesized single-step path; code_flow nodes flattened to 'file:line — message'; a locationless/empty/None/non-dict finding → None; and proofs_from_findings dropping non-proofs (the integration-style batch case).

# Deliverables

The NEW file `ngv2/taint_path_signal.py` exactly as pinned in the DISPATCH DIRECTIVE, verified GREEN by `python3 -m pytest -q tests/ngv2/test_taint_path_signal_wired.py` (5 passed).
