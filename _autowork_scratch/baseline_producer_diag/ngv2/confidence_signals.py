"""Live ``compute_confidence`` signal producer for ngv2.

This module assembles the structural signal list consumed by
``ngv2.grounding_confidence_gate.compute_confidence`` from *real* evidence:

* the regex scan finding (a ``pattern`` match),
* the P3.1 structural semantic signals (``taint_flow`` / ``formal_path``
  proofs, merged through verbatim), and
* a REAL live-detonation report (only a ``confirmed`` verdict yields a
  ``live_poc`` structural proof).

The function is pure and deterministic: it performs no I/O, consults no clock,
uses no randomness or subprocess, and never detonates anything. The verdict is
read from the already-computed report. A non-confirmed verdict can never
manufacture confidence.
"""
from __future__ import annotations
from typing import Any

def _scan_match_signal(finding: dict) -> dict | None:
    """Return a pattern-match signal for a truthy finding with id/category."""
    if not finding:
        return None
    if not isinstance(finding, dict):
        return None
    if finding.get('id') is None and finding.get('category') is None:
        return None
    return {'tool': 'pattern_scanner', 'kind': 'pattern', 'result': 'match'}

def _live_poc_signal(live_report: Any) -> dict | None:
    """Return a live_poc proof only when the report verdict is 'confirmed'."""
    if live_report is None:
        return None
    verdict: Any = None
    for field_name in ('verdict', 'semantic_verdict'):
        if isinstance(live_report, dict):
            value = live_report.get(field_name)
        else:
            value = getattr(live_report, field_name, None)
        if value is not None:
            verdict = value
            break
    if verdict is None:
        return None
    if str(verdict).strip().lower() != 'confirmed':
        return None
    return {'tool': 'poc_runner', 'kind': 'live_poc', 'result': 'proof'}

def resolve_signals(ev, finding=None):
    """Turn an evidence dict into the ``compute_confidence`` signal list.

    Single entry point the live triage->verify FSM gate calls. Honors a
    verbatim ``ev['signals']`` list when present; otherwise runs the structural
    semantic verifier over ``ev['source']`` and folds in any
    ``ev['live_report']`` detonation verdict via ``build_confidence_signals``.

    Totally tolerant: any import/derivation/build failure degrades to an
    empty/None list and never raises. ``ev`` may be ``None``, ``{}``, or any
    non-dict value.
    """
    get = ev.get if isinstance(ev, dict) else lambda key, default=None: default
    signals = get('signals')
    if signals is not None:
        return signals
    finding_d = finding if isinstance(finding, dict) else None
    if finding_d is None:
        ev_finding = get('finding')
        finding_d = ev_finding if isinstance(ev_finding, dict) else {}
    semantic = []
    source = get('source')
    if source:
        try:
            from ngv2.semantic_signals import produce_semantic_signals
            language = get('language')
            semantic = produce_semantic_signals(finding_d, source, language) or []
        except Exception:
            semantic = []
    try:
        return build_confidence_signals(finding_d, semantic_signals=semantic, taint_proofs=get('taint_proofs'), live_report=get('live_report'))
    except Exception:
        return semantic or None
def build_confidence_signals(finding: dict, *, semantic_signals: list | None = None, taint_proofs: list | None = None, live_report: dict | object | None = None) -> list[dict]:
    """Assemble the ``compute_confidence`` input list for a single finding.

    Combines the scan finding (a ``pattern`` match), any P3.1 structural
    ``semantic_signals``, and a real live-detonation ``live_report`` (a
    ``confirmed`` verdict -> a ``live_poc`` structural proof). A non-confirmed
    detonation never contributes a proof, so marker-spoofing cannot manufacture
    confidence.
    """
    signals: list[dict] = []
    finding = finding if isinstance(finding, dict) else {}

    # The scan finding itself contributes exactly one pattern match.
    if finding:
        signals.append({
            'tool': 'scan',
            'kind': 'pattern',
            'result': 'match',
            'finding_id': finding.get('id'),
            'category': finding.get('category'),
            'cwe': finding.get('cwe'),
        })

    # Merge the structural semantic signals through unchanged.
    if semantic_signals:
        for sem in semantic_signals:
            if isinstance(sem, dict):
                signals.append(sem)

    # Merge CodeQL interprocedural taint-path proofs through verbatim (same
    # shape as semantic taint_flow proofs): a taint_flow/result:proof signal
    # drives the ADMIT band in compute_confidence.
    if taint_proofs:
        for proof in taint_proofs:
            if isinstance(proof, dict):
                signals.append(proof)

    # Only a confirmed live detonation contributes a live_poc proof.
    verdict = None
    if isinstance(live_report, dict):
        verdict = live_report.get('verdict')
    elif live_report is not None:
        verdict = getattr(live_report, 'verdict', None)
    if verdict == 'confirmed':
        signals.append({
            'tool': 'live_detonation',
            'kind': 'live_poc',
            'result': 'proof',
            'finding_id': finding.get('id'),
        })

    return signals
