"""ngv2.report — deterministic report builder + markdown renderer.

Turns a HuntState (findings) plus the detonation ``LiveTestReport`` results
into a serializable report dict and a huntr-submission-shaped markdown string.

The module is pure and deterministic: it performs no real LLM call, network
request, subprocess, wall-clock read, or external submission. The submission
phase worker entrypoint ``run_stage`` composes only the injected seams.

Public API:
    build_report(state, reports) -> dict
    render_markdown(report) -> str
    run_stage(context, seams) -> list[dict]
"""
from __future__ import annotations
import dataclasses
import json
from typing import Any, Dict, Iterable, List, Optional

def _to_dict(obj: Any) -> Dict[str, Any]:
    """Best-effort conversion of a finding/result record to a plain dict."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return dict(obj)
    if dataclasses.is_dataclass(obj) and (not isinstance(obj, type)):
        return dataclasses.asdict(obj)
    if hasattr(obj, '_asdict'):
        try:
            return dict(obj._asdict())
        except Exception:
            pass
    if hasattr(obj, '__dict__'):
        return dict(vars(obj))
    return {}

def _findings_of(state: Any) -> List[Any]:
    """Extract the iterable of Finding records from a HuntState-like object."""
    if state is None:
        return []
    container: Any
    if isinstance(state, dict):
        container = state.get('findings')
    else:
        container = getattr(state, 'findings', None)
    if container is None:
        return []
    if isinstance(container, dict):
        return list(container.values())
    if isinstance(container, (list, tuple, set)):
        return list(container)
    try:
        return list(container)
    except TypeError:
        return [container]

def build_report(state: Any, reports: Iterable[Any]) -> Dict[str, Any]:
    """Compose a serializable report dict from hunt state + live test reports.

    Returns a dict shaped as::

        {
            "summary": {"total_findings", "total_results",
                        "confirmed", "refuted", "verdicts"},
            "findings": [ {<finding fields>}, ... ],
            "results":  [ {<live-test-report fields>}, ... ],
        }
    """
    findings = _findings_of(state)
    report_list = list(reports or [])
    finding_dicts: List[Dict[str, Any]] = [_to_dict(f) for f in findings]
    result_dicts: List[Dict[str, Any]] = [_to_dict(r) for r in report_list]
    verdict_counts: Dict[str, int] = {}
    for rd in result_dicts:
        verdict = rd.get('verdict')
        if verdict is not None:
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
    summary = {'total_findings': len(finding_dicts), 'total_results': len(result_dicts), 'confirmed': verdict_counts.get('confirmed', 0), 'refuted': verdict_counts.get('refuted', 0), 'verdicts': verdict_counts}
    return {'summary': summary, 'findings': finding_dicts, 'results': result_dicts}

def _result_id(result: Dict[str, Any]) -> Any:
    for field_name in ('finding_id', 'id', 'finding'):
        if field_name in result:
            return result[field_name]
    return None

def render_markdown(report: Optional[Dict[str, Any]]) -> str:
    """Render a report dict (from :func:`build_report`) as markdown text."""
    report = report or {}
    summary = report.get('summary', {}) or {}
    findings = report.get('findings', []) or []
    results = report.get('results', []) or []
    results_by_id: Dict[Any, List[Dict[str, Any]]] = {}
    for rd in results:
        results_by_id.setdefault(_result_id(rd), []).append(rd)
    lines: List[str] = []
    lines.append('# Vulnerability Report')
    lines.append('')
    lines.append('## Summary')
    lines.append(f'- Total findings: {summary.get('total_findings', 0)}')
    lines.append(f'- Total results: {summary.get('total_results', 0)}')
    lines.append(f'- Confirmed: {summary.get('confirmed', 0)}')
    lines.append(f'- Refuted: {summary.get('refuted', 0)}')
    lines.append('')
    lines.append('## Findings')
    if not findings:
        lines.append('- (no findings)')
    for fd in findings:
        fid = fd.get('id', '')
        title = fd.get('title', '')
        lines.append('')
        lines.append(f'### {fid}: {title}'.rstrip())
        for field_name, value in fd.items():
            lines.append(f'- {field_name}: {value}')
        for rd in results_by_id.get(fid, []):
            lines.append(f'- verdict: {rd.get('verdict', '')}')
            for field_name, value in rd.items():
                lines.append(f'- result.{field_name}: {value}')
    lines.append('')
    lines.append('## Results')
    if not results:
        lines.append('- (no results)')
    for rd in results:
        lines.append(f'- {_result_id(rd)}: {rd.get('verdict', '')}')
    return '\n'.join(lines)

def _invoke_seam(seam: Any, parked: Any, prior: Any, context: Dict[str, Any], seams: Dict[str, Any]) -> Any:
    """Invoke the injected submission_package seam, tolerating its signature."""
    fn = None
    if callable(seam):
        fn = seam
    else:
        for member in ('build', 'assemble', 'compose', 'package', 'run'):
            candidate = getattr(seam, member, None)
            if callable(candidate):
                fn = candidate
                break
    if fn is None:
        return None
    attempts = (lambda: fn(parked_package=parked, prior_findings=prior), lambda: fn(parked, prior), lambda: fn(context), lambda: fn(parked), lambda: fn())
    last_type_error: Optional[TypeError] = None
    for attempt in attempts:
        try:
            return attempt()
        except TypeError as exc:
            last_type_error = exc
            continue
    if last_type_error is not None:
        raise last_type_error
    return None

def _is_valid_package(package: Any) -> bool:
    if package is None:
        return False
    if isinstance(package, dict):
        return len(package) > 0
    if isinstance(package, (list, tuple, str)):
        return len(package) > 0
    return True

def _artifact_filename(phase: str) -> str:
    safe = phase if isinstance(phase, str) and phase else 'report'
    return f'{safe}.json'

def run_stage(context: dict, seams: dict) -> list[dict]:
    """Compose the injected seams into a single harvester-aligned report artifact.

    Returns ``[]`` when there is no material to report (no findings and no
    parked package). Otherwise emits exactly one report-stage artifact whose
    filename ends in ``_report.json`` so that
    ``artifact_harvester.parse_stage_artifact`` accepts it.
    """
    import json

    context = context or {}
    seams = seams or {}

    prior_findings = context.get("prior_findings") or []
    parked_package = context.get("parked_package")

    # Empty input: nothing to report.
    if not prior_findings and not parked_package:
        return []

    target = context.get("target")
    phase = context.get("phase")

    llm_client = seams.get("llm_client")
    builder = seams.get("submission_package")

    submission = None
    if builder is not None:
        submission = builder(
            llm_client=llm_client,
            findings=prior_findings,
            parked_package=parked_package,
            target=target,
            phase=phase,
        )

    payload = {
        "submission": submission,
        "findings": prior_findings,
        "parked_package": parked_package,
        "target": target,
        "phase": phase,
    }

    content = json.dumps(payload, indent=2, sort_keys=True)

    artifact = {
        # Harvester-aligned filename: must end in "_report.json" so that
        # artifact_harvester.parse_stage_artifact classifies it as a report.
        "filename": "submission_report.json",
        "content": content,
        "stage": "report",
        "phase": phase,
        "target": target,
    }
    return [artifact]


if __name__ == "__main__":
    import sys as _sys
    from ngv2.workers._runner import main as _main

    _sys.exit(_main("report"))
