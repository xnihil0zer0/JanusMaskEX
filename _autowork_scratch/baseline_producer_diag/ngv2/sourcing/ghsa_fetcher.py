"""ngv2/sourcing/ghsa_fetcher.py — GitHub Security Advisories producer.

Injected-seam producer + pure parser for GitHub Security Advisories
(``GET https://api.github.com/advisories?ecosystem=pip``).

Mirrors the injected-seam pattern from ``ngv2/sourcing/huntr_client.py``::

    Fetcher = Callable[[url: str, headers: dict], tuple[int, str, dict]]

``fetch_ghsa`` performs no direct network I/O: it builds the advisories URL
with the ``ecosystem`` query param and the already-authenticated gh token
header, passes the request through the injected fetcher seam, and routes the
response body to the pure :func:`parse_ghsa`.

``parse_ghsa`` is pure over the response body (a JSON list of advisories) and
emits enrichment records carrying ``cve_id`` / ``ghsa_id`` join keys plus
``cwe`` / ``cvss`` / ``fix_commit`` and a ``vulnerable_functions`` reachability
signal. These records join huntr records on ``cve_id`` / ``ghsa_id`` and merge
cleanly into the ``build_repo_bounties`` ``huntr_repo_bounties`` shape.
"""
from __future__ import annotations
import json
from typing import Any, Callable, Dict, List, Tuple
Fetcher = Callable[[str, Dict[str, str]], Tuple[int, str, Dict[str, str]]]
ADVISORIES_URL = 'https://api.github.com/advisories'

def _as_float(value: Any) -> float:
    """Best-effort coerce a CVSS score to float, defaulting to 0.0."""
    try:
        if value is None or value == '':
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0

def _first_cwe(advisory: Dict[str, Any]) -> str:
    """Return the first ``CWE-NNN`` identifier from an advisory, or ''."""
    cwes = advisory.get('cwes')
    if not isinstance(cwes, list):
        return ''
    for entry in cwes:
        if isinstance(entry, dict):
            ident = entry.get('cwe_id')
            if isinstance(ident, str) and ident:
                return ident
        elif isinstance(entry, str) and entry:
            return entry
    return ''

def _cvss_score(advisory: Dict[str, Any]) -> float:
    """Extract the CVSS base score from an advisory, defaulting to 0.0."""
    cvss = advisory.get('cvss')
    if isinstance(cvss, dict):
        return _as_float(cvss.get('score'))
    return 0.0

def _vulnerabilities(advisory: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the advisory's vulnerabilities entries as a list of dicts."""
    vulns = advisory.get('vulnerabilities')
    if not isinstance(vulns, list):
        return []
    return [v for v in vulns if isinstance(v, dict)]

def _vulnerable_functions(advisory: Dict[str, Any]) -> List[str]:
    """Collect the reachability signal across all vulnerabilities entries.

    Defaults to an empty list when the advisory omits ``vulnerable_functions``.
    """
    functions: List[str] = []
    for vuln in _vulnerabilities(advisory):
        fns = vuln.get('vulnerable_functions')
        if isinstance(fns, list):
            for fn in fns:
                if isinstance(fn, str) and fn:
                    functions.append(fn)
    return functions

def _fix_commit(advisory: Dict[str, Any]) -> str:
    """Map the first patched-version reference to a ``fix_commit`` value."""
    for vuln in _vulnerabilities(advisory):
        patched = vuln.get('first_patched_version')
        if isinstance(patched, dict):
            ident = patched.get('identifier')
            if isinstance(ident, str) and ident:
                return ident
        elif isinstance(patched, str) and patched:
            return patched
    return ''

def parse_ghsa(body: str) -> List[Dict[str, Any]]:
    """Pure-parse a GitHub advisories response body into enrichment records.

    Each emitted record carries the ``cve_id`` / ``ghsa_id`` join keys plus
    ``cwe`` / ``cvss`` / ``cvss_score`` / ``fix_commit`` and a
    ``vulnerable_functions`` list (the reachability signal). Malformed or empty
    bodies, and non-list payloads (e.g. an error ``{"message": ...}``), yield an
    empty list rather than raising.
    """
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    records: List[Dict[str, Any]] = []
    for advisory in payload:
        if not isinstance(advisory, dict):
            continue
        ghsa_id = advisory.get('ghsa_id') or ''
        cve_id = advisory.get('cve_id') or ''
        cwe = _first_cwe(advisory)
        score = _cvss_score(advisory)
        records.append({'ghsa_id': ghsa_id, 'cve_id': cve_id, 'cwe': cwe, 'cvss': score, 'cvss_score': score, 'fix_commit': _fix_commit(advisory), 'vulnerable_functions': _vulnerable_functions(advisory)})
    return records

def fetch_ghsa(fetcher: Fetcher, ecosystem: str='pip') -> List[Dict[str, Any]]:
    """Fetch GitHub Security Advisories through the injected fetcher seam.

    Performs no direct network I/O: builds the advisories URL with the
    ``ecosystem`` query param and the already-authenticated gh token header,
    passes the request through ``fetcher``, then delegates body parsing to
    :func:`parse_ghsa`. A non-200 status raises.
    """
    url = '{base}?ecosystem={ecosystem}'.format(base=ADVISORIES_URL, ecosystem=ecosystem)
    headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
    status, body, _response_headers = fetcher(url, headers)
    if status != 200:
        raise RuntimeError('GHSA fetch failed: GET {url} returned status {status}'.format(url=url, status=status))
    return parse_ghsa(body)