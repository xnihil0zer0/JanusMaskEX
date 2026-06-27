"""OSV.dev enrichment fetcher.

Injected-seam producer (``query_osv``) plus a pure parser (``parse_osv``) that
turns an OSV.dev ``{"vulns": [...]}`` response body into enrichment records.

The records carry the ``cve_id`` / ``ghsa_id`` join keys (plus ``cwe``,
``cvss`` and ``fix_commit`` signals) so they merge cleanly into the huntr
snapshot shape produced by ``build_repo_bounties`` without re-deriving that
shape here.

Network I/O is never performed directly: ``query_osv`` calls an injected
Fetcher seam mirroring ``ngv2/sourcing/huntr_client.py``::

    Fetcher = Callable[[url: str, headers: dict, payload: str | None],
                       tuple[int, str, dict]]

Standard library only; no nondeterministic sources.
"""
from __future__ import annotations
import json
from typing import Callable, Optional
Fetcher = Callable[[str, dict, Optional[str]], 'tuple[int, str, dict]']
OSV_QUERY_URL = 'https://api.osv.dev/v1/query'
DEFAULT_ECOSYSTEM = 'PyPI'

def _coerce_text(body: object) -> str:
    """Return ``body`` as text, decoding bytes when needed."""
    if isinstance(body, bytes):
        try:
            return body.decode('utf-8')
        except Exception:
            return ''
    if isinstance(body, str):
        return body
    return ''

def _first_alias(aliases: object, prefix: str) -> str:
    """Return the first alias starting with ``prefix`` (case-insensitive)."""
    if not isinstance(aliases, (list, tuple)):
        return ''
    needle = prefix.upper()
    for alias in aliases:
        if isinstance(alias, str) and alias.upper().startswith(needle):
            return alias
    return ''

def _extract_cwe(vuln: dict) -> str:
    """Pull the first ``CWE-NNN`` id from ``database_specific.cwe_ids``."""
    db_specific = vuln.get('database_specific')
    if not isinstance(db_specific, dict):
        return ''
    cwe_ids = db_specific.get('cwe_ids')
    if isinstance(cwe_ids, (list, tuple)):
        for ident in cwe_ids:
            if isinstance(ident, str) and ident:
                return ident
    single = db_specific.get('cwe_id')
    if isinstance(single, str):
        return single
    return ''

def _extract_cvss(vuln: dict) -> str:
    """Pull the CVSS vector/score string from the ``severity`` array."""
    severities = vuln.get('severity')
    if not isinstance(severities, (list, tuple)):
        return ''
    for entry in severities:
        if isinstance(entry, dict):
            score = entry.get('score')
            if isinstance(score, str) and score:
                return score
    return ''

def _extract_fix_commit(vuln: dict) -> str:
    """Pull the first GIT ``fixed`` event sha from the affected ranges."""
    affected = vuln.get('affected')
    if not isinstance(affected, (list, tuple)):
        return ''
    for entry in affected:
        if not isinstance(entry, dict):
            continue
        ranges = entry.get('ranges')
        if not isinstance(ranges, (list, tuple)):
            continue
        for rng in ranges:
            if not isinstance(rng, dict):
                continue
            if rng.get('type') != 'GIT':
                continue
            events = rng.get('events')
            if not isinstance(events, (list, tuple)):
                continue
            for event in events:
                if isinstance(event, dict):
                    fixed = event.get('fixed')
                    if isinstance(fixed, str) and fixed:
                        return fixed
    return ''

def _vuln_to_record(vuln: dict) -> dict:
    """Map a single OSV vuln object to an enrichment record."""
    osv_id = vuln.get('id')
    osv_id = osv_id if isinstance(osv_id, str) else ''
    aliases = vuln.get('aliases')
    cve_id = _first_alias(aliases, 'CVE-')
    if osv_id.upper().startswith('GHSA-'):
        ghsa_id = osv_id
    else:
        ghsa_id = _first_alias(aliases, 'GHSA-')
    return {'osv_id': osv_id, 'cve_id': cve_id, 'ghsa_id': ghsa_id, 'cwe': _extract_cwe(vuln), 'cvss': _extract_cvss(vuln), 'fix_commit': _extract_fix_commit(vuln)}

def parse_osv(body: str) -> list:
    """Pure-parse an OSV.dev response body into enrichment records.

    Malformed / empty bodies and absent ``vulns`` arrays yield ``[]`` rather
    than raising. Missing per-vuln fields degrade gracefully to safe defaults
    so the join keys remain usable.
    """
    text = _coerce_text(body)
    if not text:
        return []
    try:
        envelope = json.loads(text)
    except (ValueError, TypeError):
        return []
    if not isinstance(envelope, dict):
        return []
    vulns = envelope.get('vulns')
    if not isinstance(vulns, (list, tuple)):
        return []
    records = []
    for vuln in vulns:
        if isinstance(vuln, dict):
            records.append(_vuln_to_record(vuln))
    return records

def _build_payload(package: Optional[str], cve: Optional[str]) -> str:
    """Assemble the OSV query JSON payload from whichever input is given."""
    if package:
        query = {'package': {'name': package, 'ecosystem': DEFAULT_ECOSYSTEM}}
    elif cve:
        query = {'cve': cve, 'id': cve}
    else:
        query = {}
    return json.dumps(query)

def query_osv(fetcher: Fetcher, package: Optional[str]=None, cve: Optional[str]=None) -> list:
    """POST an OSV.dev query through the injected fetcher seam.

    No auth header is sent. A non-200 status raises. The response body is
    delegated to :func:`parse_osv`.
    """
    payload = _build_payload(package, cve)
    headers = {'Content-Type': 'application/json'}
    status, body, _resp_headers = fetcher(OSV_QUERY_URL, headers, payload)
    if status != 200:
        raise RuntimeError('OSV query failed with status {status}'.format(status=status))
    return parse_osv(body)