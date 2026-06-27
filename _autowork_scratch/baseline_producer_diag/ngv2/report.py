"""Deterministic report builder and markdown renderer for NobleGreed v2.

This module is pure and stdlib-only: it performs no I/O, subprocess,
socket, network, eval/exec/__import__, randomness, or mutable
module-level state. It reads the ``VERDICTS`` contract tuple and the
``.to_dict()`` / ``.verdict`` attributes of the supplied objects without
re-implementing any dataclass.
"""
from ngv2.contracts import VERDICTS
__all__ = ['build_report', 'render_markdown']

def build_report(state, reports) -> dict:
    """Build a deterministic, serialisable report dict.

    Parameters
    ----------
    state:
        A HuntState-like object exposing ``.phase`` (str) and
        ``.findings`` (a list of Finding-like objects each exposing a
        ``.to_dict()`` method).
    reports:
        A list of LiveTestReport-like objects, each exposing ``.verdict``
        (str) and a ``.to_dict()`` method.

    Returns
    -------
    dict
        A dict with exactly the keys ``'phase'``, ``'findings'``,
        ``'results'`` and ``'summary'``. The summary contains
        ``'total_findings'`` plus one count per member of ``VERDICTS``.
    """
    findings = [f.to_dict() for f in state.findings]
    results = [r.to_dict() for r in reports]
    summary = {'total_findings': len(state.findings)}
    for verdict in VERDICTS:
        summary[verdict] = sum((1 for r in reports if r.verdict == verdict))
    return {'phase': state.phase, 'findings': findings, 'results': results, 'summary': summary}

def render_markdown(report: dict) -> str:
    """Render a report dict (as produced by :func:`build_report`) to markdown.

    Consumes only the plain dict -- never live state/report objects. The
    returned string always starts with a top-level ``#`` header, contains
    every finding's title and target text, and contains every result's
    verdict text.
    """
    lines = ['# NobleGreed v2 Report']
    phase = report.get('phase', '')
    lines.append('')
    lines.append('**Phase:** {}'.format(phase))
    summary = report.get('summary', {})
    lines.append('')
    lines.append('## Summary')
    lines.append('')
    lines.append('- **Total findings:** {}'.format(summary.get('total_findings', 0)))
    for verdict in VERDICTS:
        if verdict in summary:
            lines.append('- **{}:** {}'.format(verdict, summary[verdict]))
    lines.append('')
    lines.append('## Findings')
    findings = report.get('findings', [])
    if not findings:
        lines.append('')
        lines.append('_No findings._')
    for index, finding in enumerate(findings, start=1):
        title = finding.get('title', '')
        target = finding.get('target', '')
        lines.append('')
        lines.append('### {}. {}'.format(index, title))
        lines.append('')
        lines.append('- **Target:** {}'.format(target))
    lines.append('')
    lines.append('## Results')
    results = report.get('results', [])
    if not results:
        lines.append('')
        lines.append('_No results._')
    for index, result in enumerate(results, start=1):
        verdict = result.get('verdict', '')
        lines.append('')
        lines.append('### Result {}'.format(index))
        lines.append('')
        lines.append('- **Verdict:** {}'.format(verdict))
    return '\n'.join(lines)