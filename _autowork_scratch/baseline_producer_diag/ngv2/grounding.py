"""Adapter that normalizes a semgrep-shaped report dict into Finding objects.

Pure, deterministic, stdlib-only. Exposes exactly ``normalize_severity`` and
``parse_semgrep``. Does not redefine ``Finding`` or ``SEVERITIES``.
"""
from ngv2.contracts import Finding, SEVERITIES
__all__ = ['normalize_severity', 'parse_semgrep']
_SEVERITY_MAP = {'critical': 'critical', 'error': 'high', 'warning': 'medium', 'info': 'low'}

def normalize_severity(raw: str) -> str:
    """Map a raw semgrep severity to a canonical SEVERITIES member.

    Case-insensitive: CRITICAL->'critical', ERROR->'high', WARNING->'medium',
    INFO->'low'. Any unknown/unmapped/None-ish input falls back to 'low'.
    """
    try:
        key = str(raw).lower()
    except Exception:
        return 'low'
    return _SEVERITY_MAP.get(key, 'low')

def parse_semgrep(report: dict, target: str) -> list:
    """Convert a semgrep-shaped report dict into a list of Finding objects."""
    findings = []
    for i, result in enumerate(report.get('results', [])):
        check_id = result['check_id']
        cwe = result.get('extra', {}).get('metadata', {}).get('cwe') or []
        category = cwe[0] if cwe else check_id
        message = result['extra']['message']
        evidence = [f'{result['path']}:{result['start']['line']}-{result['end']['line']}']
        finding = Finding(id=f'{check_id}-{i}', target=target, category=category, severity=normalize_severity(result['extra']['severity']), title=message, description=message, evidence=evidence)
        findings.append(finding)
    return findings