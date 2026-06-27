"""ngv2.batch_qualify -- deterministic batch target-qualification shell.

This module orchestrates per-repo qualification over a list of targets. The
real qualifier (``ngv2.target_qualify`` / network) is **injected** as a callable
seam, so this shell performs no live qualification, network, clock, or threading
work of its own. It only collects targets, drives the injected qualifier once
per target, sorts the per-target results by decision priority then expected
bounty, and aggregates the GO/SKIP/UNKNOWN counts.

Stdlib only -- no third-party imports, no cross-leaf imports.
"""
from __future__ import annotations
import os
from typing import Any, Callable, Dict, List, Optional
Qualifier = Callable[[str, str, str], Dict[str, Any]]
DEFAULT_CWE: str = 'CWE-94'
DEFAULT_SEVERITY: str = 'HIGH'
DECISION_ORDER: Dict[str, int] = {'GO': 0, 'UNKNOWN': 1, 'SKIP': 2}

def _expected_bounty(result: Dict[str, Any]) -> int:
    """Return a result's expected bounty, treating missing/None as 0."""
    bounty = result.get('bounty') or {}
    expected = bounty.get('expected')
    return expected if isinstance(expected, (int, float)) else 0

def sort_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return a new list sorted by decision priority then expected bounty (desc).

    Pure: the input list is never mutated and a fresh list is returned.
    """
    return sorted(results, key=lambda r: (DECISION_ORDER.get(r.get('decision'), len(DECISION_ORDER)), -_expected_bounty(r)))

def qualify_single(repo: str, cwe: str, severity: str, qualifier: Qualifier) -> Dict[str, Any]:
    """Qualify one target via the injected qualifier seam.

    On any exception raised by the qualifier, a deterministic UNKNOWN/ERROR
    result shape is returned instead of propagating the failure.
    """
    try:
        return qualifier(repo, cwe, severity)
    except Exception as exc:
        return {'decision': 'UNKNOWN', 'target': repo, 'target_type': 'repo', 'bounty': {'expected': 0, 'status': 'ERROR'}, 'saturation': {'submissions': None, 'status': 'ERROR'}, 'reasoning': 'Error: ' + str(exc)}

def make_mock_qualifier(mapping: Dict[str, Dict[str, Any]], default: Optional[Dict[str, Any]]=None) -> Qualifier:
    """Build a scripted, deterministic qualifier callable for testing.

    Looks each repo up in ``mapping``. For an unmapped repo it returns ``default``
    when one is supplied, otherwise a deterministic UNKNOWN result for that repo.
    """

    def _qualifier(repo: str, cwe: str, severity: str) -> Dict[str, Any]:
        if repo in mapping:
            return mapping[repo]
        if default is not None:
            return default
        return {'decision': 'UNKNOWN', 'target': repo, 'target_type': 'repo', 'bounty': {'expected': 0}, 'saturation': {'submissions': None}}
    return _qualifier

def _parse_repos_arg(raw: str) -> List[str]:
    """Split a comma-separated repos string into trimmed, non-empty entries."""
    return [item.strip() for item in raw.split(',') if item.strip()]

def _read_repos_file(path: str) -> List[str]:
    """Read repos from a file, skipping blank lines and ``#`` comments."""
    repos: List[str] = []
    with open(path, 'r', encoding='utf-8') as handle:
        for line in handle:
            entry = line.strip()
            if not entry or entry.startswith('#'):
                continue
            repos.append(entry)
    return repos

def _dedup_case_insensitive(repos: List[str]) -> List[str]:
    """Drop case-insensitive duplicates while preserving first-seen order."""
    seen: set = set()
    out: List[str] = []
    for repo in repos:
        ident = repo.lower()
        if ident in seen:
            continue
        seen.add(ident)
        out.append(repo)
    return out

def run(args: Any, qualifier: Qualifier) -> Dict[str, Any]:
    """Orchestrate batch qualification and aggregate the outcome.

    ``args`` carries ``repos`` (comma-separated string), ``file`` (path to a repo
    list), ``cwe`` and ``severity``. The injected ``qualifier`` is the seam used
    to qualify each target; the real network qualifier is never imported here.
    """
    cwe = getattr(args, 'cwe', None) or DEFAULT_CWE
    severity = getattr(args, 'severity', None) or DEFAULT_SEVERITY
    repos_arg = getattr(args, 'repos', None)
    file_arg = getattr(args, 'file', None)
    if repos_arg:
        repos = _parse_repos_arg(repos_arg)
    elif file_arg:
        if not os.path.exists(file_arg):
            return {'status': 'error', 'error': 'File not found: ' + str(file_arg)}
        repos = _read_repos_file(file_arg)
    else:
        repos = []
    repos = _dedup_case_insensitive(repos)
    if not repos:
        return {'status': 'error', 'error': 'No repos specified'}
    results = [qualify_single(repo, cwe, severity, qualifier) for repo in repos]
    results = sort_results(results)
    go_count = sum((1 for r in results if r.get('decision') == 'GO'))
    skip_count = sum((1 for r in results if r.get('decision') == 'SKIP'))
    unknown_count = sum((1 for r in results if r.get('decision') == 'UNKNOWN'))
    return {'status': 'ok', 'cwe': cwe, 'severity': severity, 'total': len(results), 'go_count': go_count, 'skip_count': skip_count, 'unknown_count': unknown_count, 'results': results}