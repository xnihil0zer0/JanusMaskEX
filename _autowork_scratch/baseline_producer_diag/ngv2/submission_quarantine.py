"""P6.3 submission quarantine + dedup.

Pure, stdlib-only port of the legacy ``_not_eligible`` quarantine. Partitions an
iterable of finding dicts into an ``eligible`` (submittable) bucket and a
``quarantined`` bucket, routing ineligible (explicit ``eligible=False``),
unconfirmed (present ``verdict`` != ``confirmed``), and duplicate (already
submitted, or a within-batch collision) findings to quarantine annotated with a
``quarantine_reason``.

No file/network I/O, no subprocess, no LLM, no wall-clock, no randomness. The
already-submitted corpus is injected as ``existing_keys`` rather than read from
disk.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional, Tuple
REASON_INELIGIBLE = 'ineligible'
REASON_NOT_CONFIRMED = 'not_confirmed'
REASON_DUPLICATE_EXISTING = 'duplicate_existing'
REASON_DUPLICATE_BATCH = 'duplicate_batch'
__all__ = ['partition_findings', 'dedup_key', 'REASON_INELIGIBLE', 'REASON_NOT_CONFIRMED', 'REASON_DUPLICATE_EXISTING', 'REASON_DUPLICATE_BATCH']

def _norm(value: Any) -> str:
    """Normalize a value to a lowercased, whitespace-stripped string."""
    if value is None:
        return ''
    return str(value).strip().lower()

def dedup_key(finding: Dict[str, Any]) -> Tuple[str, str]:
    """Return a canonical, normalized ``(repo, cwe)`` dedup key for a finding."""
    repo = finding.get('repo') or finding.get('repo_url')
    cwe = finding.get('cwe') or finding.get('category')
    return (_norm(repo), _norm(cwe))

def _is_eligible(finding: Dict[str, Any]) -> bool:
    """True unless the finding carries an explicit ``eligible=False``."""
    if 'eligible' not in finding:
        return True
    return bool(finding['eligible'])

def _is_confirmed(finding: Dict[str, Any]) -> bool:
    """True if there is no ``verdict`` gate, or the verdict is ``confirmed``."""
    if 'verdict' not in finding:
        return True
    return _norm(finding['verdict']) == 'confirmed'

def partition_findings(findings: Optional[Iterable[Dict[str, Any]]], existing_keys: Optional[Iterable[Tuple[Any, Any]]]=None) -> Dict[str, List[Dict[str, Any]]]:
    """Partition findings into eligible vs quarantined buckets.

    Reason precedence (first matching condition wins):
    ineligible > not_confirmed > duplicate_existing > duplicate_batch.
    Returned buckets contain shallow copies; caller dicts are never mutated.
    """
    eligible: List[Dict[str, Any]] = []
    quarantined: List[Dict[str, Any]] = []
    existing = set()
    if existing_keys is not None:
        for entry in existing_keys:
            repo, cwe = entry
            existing.add((_norm(repo), _norm(cwe)))
    seen = set()
    if findings is not None:
        for finding in findings:
            copy = dict(finding)
            key = dedup_key(finding)
            if not _is_eligible(finding):
                copy['quarantine_reason'] = REASON_INELIGIBLE
                quarantined.append(copy)
            elif not _is_confirmed(finding):
                copy['quarantine_reason'] = REASON_NOT_CONFIRMED
                quarantined.append(copy)
            elif key in existing:
                copy['quarantine_reason'] = REASON_DUPLICATE_EXISTING
                quarantined.append(copy)
            elif key in seen:
                copy['quarantine_reason'] = REASON_DUPLICATE_BATCH
                quarantined.append(copy)
            else:
                seen.add(key)
                eligible.append(copy)
    return {'eligible': eligible, 'quarantined': quarantined}