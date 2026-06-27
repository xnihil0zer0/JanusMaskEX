"""ngv2.pre_analysis -- deterministic pre-analysis merge layer.

``run_pre_analysis`` orchestrates two static scanners -- a semgrep adapter and a
locally inlined regex pattern scanner -- and cross-references their findings by
``(file, line)`` into a single structured report.  The actual scanning is done
behind injectable seams (``semgrep_finder`` / ``pattern_finder``) so the module
itself is a *pure*, deterministic shell: given the same finder outputs it always
produces the same report.  No real scanner, binary, or network call is ever
performed by this module.

This module consumes the committed spine ``ngv2.semgrep_adapter`` for its default
semgrep seam and re-implements (inlines) the regex pattern-scanning behaviour
locally rather than importing any sibling pattern-scanner leaf.  It depends only
on the Python standard library.
"""
from __future__ import annotations
import copy
import os
import re
from typing import Callable, Dict, List, Optional, Tuple
try:
    from ngv2 import semgrep_adapter as _semgrep_adapter
except Exception:
    _semgrep_adapter = None
PRE_ANALYSIS_FIELDS: Tuple[str, ...] = ('semgrep_findings', 'scanner_findings', 'cross_validated', 'semgrep_only', 'scanner_only', 'summary_stats', 'repo_path', 'timestamp', 'warnings')
SUMMARY_STATS_FIELDS: Tuple[str, ...] = ('total_semgrep', 'total_scanner', 'total_cross_validated', 'priority_count', 'severity_breakdown', 'files_with_findings')
_DEFAULT_TIMESTAMP = '1970-01-01T00:00:00+00:00'
_PATTERN_RULES: Tuple[Tuple[str, 're.Pattern[str]', str, str, str], ...] = tuple(((ident, re.compile(expr), severity, description, cwe) for ident, expr, severity, description, cwe in (('os-system', 'os\\.system\\s*\\(', 'high', 'os.system call with potential user input', 'CWE-78'), ('subprocess-shell', 'subprocess\\.[A-Za-z_]+\\([^)]*shell\\s*=\\s*True', 'high', 'subprocess invoked with shell=True', 'CWE-78'), ('eval-exec', '\\b(?:eval|exec)\\s*\\(', 'high', 'use of eval/exec', 'CWE-95'), ('weak-hash', 'hashlib\\.(?:md5|sha1)\\s*\\(', 'medium', 'weak hash primitive', 'CWE-327'), ('todo-marker', '#\\s*(?:TODO|FIXME|XXX)\\b', 'low', 'leftover TODO/FIXME marker', ''))))

def make_mock_finder(findings: List[Dict]) -> Callable[[str], List[Dict]]:
    """Return a finder seam that yields an independent deep copy of ``findings``.

    Each invocation returns a fresh copy so that callers mutating one result can
    never leak state into a subsequent call or back into ``findings``.
    """
    snapshot = copy.deepcopy(list(findings))

    def _finder(repo_path: str) -> List[Dict]:
        return copy.deepcopy(snapshot)
    return _finder

def regex_pattern_scan(repo_path: str) -> List[Dict]:
    """Inlined regex pattern scanner over the files under ``repo_path``.

    Walks the tree deterministically, applies the compiled rule table to every
    text line, and returns findings shaped for the merge contract:
    ``{file, line, severity, id, description, cwe, code}``.  Returns ``[]`` for a
    missing/unreadable path rather than raising.
    """
    findings: List[Dict] = []
    if not repo_path or not os.path.isdir(repo_path):
        return findings
    for current_dir, dir_names, file_names in os.walk(repo_path):
        dir_names.sort()
        for file_name in sorted(file_names):
            abs_path = os.path.join(current_dir, file_name)
            try:
                with open(abs_path, 'r', encoding='utf-8', errors='strict') as handle:
                    lines = handle.readlines()
            except (OSError, UnicodeDecodeError):
                continue
            rel_path = os.path.relpath(abs_path, repo_path)
            for line_number, raw_line in enumerate(lines, start=1):
                stripped = raw_line.rstrip('\n')
                for ident, compiled, severity, description, cwe in _PATTERN_RULES:
                    if compiled.search(stripped):
                        findings.append({'file': rel_path, 'line': line_number, 'severity': severity, 'id': ident, 'description': description, 'cwe': cwe, 'code': stripped.strip()})
    findings.sort(key=lambda f: (str(f.get('file', '')), int(f.get('line', 0)), str(f.get('id', ''))))
    return findings

def _default_semgrep_finder(repo_path: str) -> List[Dict]:
    """Default semgrep seam backed by the committed spine ``ngv2.semgrep_adapter``."""
    if _semgrep_adapter is None:
        return []
    for attr in ('run', 'scan', 'analyze', 'run_semgrep', 'find', 'findings'):
        candidate = getattr(_semgrep_adapter, attr, None)
        if callable(candidate):
            result = candidate(repo_path)
            return list(result or [])
    return []

def _call_finder(finder: Callable[[str], List[Dict]], repo_path: str, label: str, warnings: List[str]) -> List[Dict]:
    """Invoke a finder seam, degrading a raised error to ``[]`` plus a warning."""
    try:
        result = finder(repo_path)
    except Exception as exc:
        warnings.append('{} finder failed: {}'.format(label, exc))
        return []
    return list(result or [])

def _location(finding: Dict) -> Tuple[str, int]:
    return (str(finding.get('file', '')), int(finding.get('line', 0)))

def _build_cross_validated(semgrep_finding: Dict, scanner_finding: Dict) -> Dict:
    return {'file': semgrep_finding.get('file', scanner_finding.get('file', '')), 'line': semgrep_finding.get('line', scanner_finding.get('line', 0)), 'severity': semgrep_finding.get('severity') or scanner_finding.get('severity', ''), 'semgrep_rule': semgrep_finding.get('rule_short', ''), 'semgrep_rule_id': semgrep_finding.get('rule_id', ''), 'analyzer_pattern': scanner_finding.get('id', ''), 'cwe': scanner_finding.get('cwe', '') or semgrep_finding.get('cwe', ''), 'message': semgrep_finding.get('message', ''), 'description': scanner_finding.get('description', '')}

def run_pre_analysis(repo_path: str, *, semgrep_finder: Optional[Callable[[str], List[Dict]]]=None, pattern_finder: Optional[Callable[[str], List[Dict]]]=None, now_fn: Optional[Callable[[], str]]=None) -> Dict:
    """Run both scanner seams over ``repo_path`` and merge them into one report.

    Findings sharing a ``(file, line)`` location across both tools are recorded
    as ``cross_validated`` (and removed from the per-tool *only* buckets).  A
    finder that raises degrades to no findings plus a recorded warning instead of
    crashing.  The result is deterministic for identical finder outputs.
    """
    if semgrep_finder is None:
        semgrep_finder = _default_semgrep_finder
    if pattern_finder is None:
        pattern_finder = regex_pattern_scan
    warnings: List[str] = []
    semgrep_findings = _call_finder(semgrep_finder, repo_path, 'semgrep', warnings)
    scanner_findings = _call_finder(pattern_finder, repo_path, 'scanner', warnings)
    scanner_by_loc: Dict[Tuple[str, int], Dict] = {}
    for finding in scanner_findings:
        scanner_by_loc.setdefault(_location(finding), finding)
    semgrep_locs = {_location(f) for f in semgrep_findings}
    cross_validated: List[Dict] = []
    seen_cross: set = set()
    for finding in semgrep_findings:
        loc = _location(finding)
        if loc in scanner_by_loc and loc not in seen_cross:
            seen_cross.add(loc)
            cross_validated.append(_build_cross_validated(finding, scanner_by_loc[loc]))
    semgrep_only = [f for f in semgrep_findings if _location(f) not in scanner_by_loc]
    scanner_only = [f for f in scanner_findings if _location(f) not in semgrep_locs]
    cross_validated.sort(key=lambda c: (str(c.get('file', '')), int(c.get('line', 0))))
    semgrep_only.sort(key=lambda f: (str(f.get('file', '')), int(f.get('line', 0)), str(f.get('rule_id', ''))))
    scanner_only.sort(key=lambda f: (str(f.get('file', '')), int(f.get('line', 0)), str(f.get('id', ''))))
    severity_breakdown: Dict[str, int] = {}
    for finding in list(semgrep_findings) + list(scanner_findings):
        severity = str(finding.get('severity', '') or 'unknown')
        severity_breakdown[severity] = severity_breakdown.get(severity, 0) + 1
    files_with_findings = {_location(f)[0] for f in list(semgrep_findings) + list(scanner_findings)}
    priority_count = sum((1 for f in semgrep_findings if f.get('is_priority')))
    summary_stats = {'total_semgrep': len(semgrep_findings), 'total_scanner': len(scanner_findings), 'total_cross_validated': len(cross_validated), 'priority_count': priority_count, 'severity_breakdown': severity_breakdown, 'files_with_findings': len(files_with_findings)}
    timestamp = now_fn() if now_fn is not None else _DEFAULT_TIMESTAMP
    return {'semgrep_findings': semgrep_findings, 'scanner_findings': scanner_findings, 'cross_validated': cross_validated, 'semgrep_only': semgrep_only, 'scanner_only': scanner_only, 'summary_stats': summary_stats, 'repo_path': repo_path, 'timestamp': timestamp, 'warnings': warnings}

def format_for_prompt(report: Dict) -> str:
    """Render a pre-analysis ``report`` to deterministic markdown."""
    stats = report.get('summary_stats', {}) or {}
    lines: List[str] = []
    lines.append('# Pre-Analysis Results')
    lines.append('')
    lines.append('Repository: {}'.format(report.get('repo_path', '')))
    lines.append('Timestamp: {}'.format(report.get('timestamp', '')))
    lines.append('')
    lines.append('## Summary')
    lines.append('- Semgrep findings: {}'.format(stats.get('total_semgrep', 0)))
    lines.append('- Scanner findings: {}'.format(stats.get('total_scanner', 0)))
    lines.append('- Cross-Validated: {}'.format(stats.get('total_cross_validated', 0)))
    lines.append('- Priority findings: {}'.format(stats.get('priority_count', 0)))
    lines.append('- Files with findings: {}'.format(stats.get('files_with_findings', 0)))
    severity_breakdown = stats.get('severity_breakdown', {}) or {}
    if severity_breakdown:
        parts = ', '.join(('{}={}'.format(name, severity_breakdown[name]) for name in sorted(severity_breakdown)))
        lines.append('- Severity breakdown: {}'.format(parts))
    lines.append('')
    lines.append('## Cross-Validated Findings')
    cross_validated = report.get('cross_validated', []) or []
    if not cross_validated:
        lines.append('- (none)')
    else:
        for entry in cross_validated:
            lines.append('- {file}:{line} [{severity}] {rule} / {pattern} {cwe}'.format(file=entry.get('file', ''), line=entry.get('line', ''), severity=entry.get('severity', ''), rule=entry.get('semgrep_rule', ''), pattern=entry.get('analyzer_pattern', ''), cwe=entry.get('cwe', '')).rstrip())
    lines.append('')
    lines.append('## Semgrep-Only Findings')
    semgrep_only = report.get('semgrep_only', []) or []
    if not semgrep_only:
        lines.append('- (none)')
    else:
        for entry in semgrep_only:
            lines.append('- {file}:{line} [{severity}] {rule}'.format(file=entry.get('file', ''), line=entry.get('line', ''), severity=entry.get('severity', ''), rule=entry.get('rule_short', entry.get('rule_id', ''))))
    lines.append('')
    lines.append('## Scanner-Only Findings')
    scanner_only = report.get('scanner_only', []) or []
    if not scanner_only:
        lines.append('- (none)')
    else:
        for entry in scanner_only:
            lines.append('- {file}:{line} [{severity}] {ident}'.format(file=entry.get('file', ''), line=entry.get('line', ''), severity=entry.get('severity', ''), ident=entry.get('id', '')))
    lines.append('')
    warnings = report.get('warnings', []) or []
    if warnings:
        lines.append('## Warnings')
        for warning in warnings:
            lines.append('- {}'.format(warning))
        lines.append('')
    return '\n'.join(lines)