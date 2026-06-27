"""verify phase worker for ngv2.

This module exposes :func:`run_stage`, the verify-phase worker entry point.
It consumes a ``get_task``-shaped ``context`` (``phase``/``target``/
``prior_findings``/``parked_package``) and a ``seams`` mapping that injects an
llm-client seam together with the verify ``may_confirm`` gate. For every finding
worth checking it composes the llm-client seam (to drive reproduction) with the
verify gate (to confirm the result) and emits an artifact dict whose
``filename``/``content``/``phase`` are shaped so that
``artifact_harvester.parse_stage_artifact(filename, content, phase="verify")``
yields a ``contracts.LiveTestReport``-shaped mapping.

Constraints honoured here:

* Standard library only -- no third-party imports.
* Deterministic -- no wall-clock / random / uuid sources; any clock or ordinal
  is taken from an explicit, injected default.
* No string literal is ever bound to a credential-looking variable name.
* Seams are consumed purely by injection; no committed module is imported at
  module load time, keeping ``import ngv2.workers.verify`` side-effect free.
"""
from __future__ import annotations
import json
from typing import Any, Callable, Iterable, Optional
PHASE: str = 'verify'
_LLM_SEAM_NAMES: tuple[str, ...] = ('llm_client', 'llm-client', 'llm', 'llm_seam', 'client')
_VERIFY_GATE_NAMES: tuple[str, ...] = ('verify_may_confirm', 'may_confirm_verify', 'may_confirm', 'verify_gate', 'verify', 'gate')
_REPRODUCED_FLAGS: tuple[str, ...] = ('reproduced', 'reproducing', 'verified', 'confirmed', 'passed', 'ok')

def _resolve_seam(seams: dict, names: Iterable[str]) -> Optional[Any]:
    """Return the first seam registered under any of ``names`` (or ``None``)."""
    if not isinstance(seams, dict):
        return None
    for ident in names:
        if ident in seams and seams[ident] is not None:
            return seams[ident]
    return None

def _resolve_gate(seams: dict) -> Optional[Callable[..., Any]]:
    """Resolve the verify ``may_confirm`` gate from the injected seams.

    The gate may be supplied directly as a callable, or nested inside a
    ``may_confirm`` mapping keyed by phase name.
    """
    candidate = _resolve_seam(seams, _VERIFY_GATE_NAMES)
    if isinstance(candidate, dict):
        nested = candidate.get(PHASE)
        if nested is not None:
            return nested if callable(nested) else None
        return None
    if callable(candidate):
        return candidate
    return None

def _collect_findings(context: dict) -> list[Any]:
    """Gather findings to verify from prior_findings and the parked package."""
    findings: list[Any] = []
    prior = context.get('prior_findings')
    if isinstance(prior, (list, tuple)):
        findings.extend(prior)
    elif prior:
        findings.append(prior)
    parked = context.get('parked_package')
    if isinstance(parked, dict):
        nested = parked.get('findings')
        if nested is None:
            nested = parked.get('prior_findings')
        if isinstance(nested, (list, tuple)):
            findings.extend(nested)
        elif nested:
            findings.append(nested)
    elif isinstance(parked, (list, tuple)):
        findings.extend(parked)
    elif parked:
        findings.append(parked)
    return findings

def _invoke_llm(llm: Any, request: dict) -> Any:
    """Drive the injected llm-client seam with ``request``.

    Accepts either a plain callable or an object exposing a verify-style method.
    """
    if llm is None:
        return None
    if callable(llm):
        return llm(request)
    for method_name in ('verify', 'complete', 'generate', 'run', 'invoke', 'chat'):
        bound = getattr(llm, method_name, None)
        if callable(bound):
            return bound(request)
    return None

def _is_reproduced(result: Any) -> bool:
    """Normalise an llm result into a reproduced / not-reproduced boolean."""
    if result is None:
        return False
    if isinstance(result, bool):
        return result
    if isinstance(result, dict):
        for flag in _REPRODUCED_FLAGS:
            if flag in result:
                return bool(result[flag])
        return True
    return bool(result)

def _gate_confirms(gate: Optional[Callable[..., Any]], report: dict) -> bool:
    """Ask the verify ``may_confirm`` gate whether ``report`` may be confirmed.

    A rejected (falsey) verdict means the artifact is withheld. When no gate is
    injected the report is allowed through unchanged.
    """
    if gate is None:
        return True
    try:
        verdict = gate(report)
    except TypeError:
        verdict = gate(report, PHASE)
    return bool(verdict)

def _finding_identity(finding: Any, ordinal: int) -> str:
    """Derive a stable identifier for a finding without nondeterministic sources."""
    if isinstance(finding, dict):
        for ident in ('finding_id', 'id', 'ident', 'name', 'title'):
            value = finding.get(ident)
            if value:
                return str(value)
    return 'finding-{0}'.format(ordinal)

def _build_report(target: Any, finding: Any, finding_id: str, reproduced: bool, llm_result: Any) -> dict:
    """Assemble a LiveTestReport-shaped mapping for a single finding."""
    status_label = 'verified' if reproduced else 'not_reproduced'
    evidence: Any = llm_result if llm_result is not None else {}
    summary = 'Finding {0} reproduced against the live target.'.format(finding_id) if reproduced else 'Finding {0} did not reproduce against the live target.'.format(finding_id)
    return {'phase': PHASE, 'target': target, 'finding_id': finding_id, 'finding': finding, 'reproduced': reproduced, 'confirmed': reproduced, 'status': status_label, 'summary': summary, 'evidence': evidence}

def _artifact(report: dict, ordinal: int) -> dict:
    """Wrap a LiveTestReport mapping into a parse_stage_artifact-ready dict."""
    filename = 'live_test_report_{0}.json'.format(ordinal)
    content = json.dumps(report, sort_keys=True, default=str)
    return {'phase': PHASE, 'filename': filename, 'content': content, 'report': report}

def run_stage(context: dict, seams: dict) -> list[dict]:
    """Run the verify phase worker.

    Parameters
    ----------
    context:
        ``get_task``-shaped mapping with ``phase``, ``target``,
        ``prior_findings`` and ``parked_package`` entries.
    seams:
        Injected seam mapping providing the llm-client and the verify
        ``may_confirm`` gate.

    Returns
    -------
    list[dict]
        Verification artifact dicts (possibly empty). Each is parseable by
        ``artifact_harvester.parse_stage_artifact(filename, content,
        phase="verify")`` and shaped for the ``contracts.LiveTestReport``
        dataclass.
    """
    if not isinstance(context, dict):
        return []
    if not isinstance(seams, dict):
        seams = {}
    findings = _collect_findings(context)
    if not findings:
        return []
    target = context.get('target')
    llm = _resolve_seam(seams, _LLM_SEAM_NAMES)
    gate = _resolve_gate(seams)
    artifacts: list[dict] = []
    for ordinal, finding in enumerate(findings):
        finding_id = _finding_identity(finding, ordinal)
        request = {'phase': PHASE, 'target': target, 'finding': finding}
        llm_result = _invoke_llm(llm, request)
        reproduced = _is_reproduced(llm_result)
        report = _build_report(target, finding, finding_id, reproduced, llm_result)
        if not _gate_confirms(gate, report):
            continue
        artifacts.append(_artifact(report, ordinal))
    return artifacts

if __name__ == "__main__":
    import sys as _sys
    from ngv2.workers._runner import main as _main

    _sys.exit(_main("verify"))
