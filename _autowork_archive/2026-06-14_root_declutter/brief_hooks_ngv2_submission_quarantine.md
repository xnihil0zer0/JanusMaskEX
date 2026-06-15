---
dependencies: []
interfaces: "exposes `partition_findings(findings, existing_keys=None) -> {\"eligible\": [...], \"quarantined\": [...]}` routing ineligible/unconfirmed/duplicate findings to quarantine (each annotated with quarantine_reason) and passing only genuinely submittable findings; plus `dedup_key(finding) -> (repo, cwe)` and the reason constants REASON_INELIGIBLE / REASON_NOT_CONFIRMED / REASON_DUPLICATE_EXISTING / REASON_DUPLICATE_BATCH."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
verification_command: ".venv/bin/python -m pytest tests/ngv2/test_submission_quarantine_wired.py -q"
---

# Title

P6.3 _not_eligible quarantine + dedup — partition findings into eligible vs quarantined (pure, injected existing-corpus)

# Scope

Build a new pure, stdlib-only module `ngv2/submission_quarantine.py` porting the legacy `_not_eligible/` quarantine: route ineligible findings (explicit `eligible=False`), unconfirmed findings (a present `verdict` not equal to 'confirmed'), and duplicate findings (same `(repo, cwe)` already in the injected existing-submissions corpus, OR a same-`(repo, cwe)` collision within the current batch where the FIRST occurrence passes and subsequent ones are quarantined) into a quarantine bucket — so only genuinely submittable findings pass. Each quarantined finding is annotated with a `quarantine_reason`. Pure, deterministic, and the existing-submissions corpus is an INJECTED parameter (hermetic; no file/network I/O). Must NOT mutate the caller's finding dicts in place (return annotated copies). The implementation below is VALIDATED (oracle proven green against it) — ship it VERBATIM as the whole file `ngv2/submission_quarantine.py`.

# Non-Goals

No file or network I/O — the "already submitted" corpus is passed in as `existing_keys`. No subprocess, LLM, wall-clock, or randomness. Do NOT render the submission document (P6.1) or pin permalinks (P6.2). Do not perform any submission.

# Inputs

`findings`: an iterable of finding dicts (each carrying at least `repo`/`repo_url` and `cwe`/`category`; richer keys `id`, `eligible`, `verdict` refine the decision). `existing_keys`: an optional iterable of already-submitted `(repo, cwe)` tuples (e.g. derived from `huntr_existing_submissions.json` at runtime). The committed RED oracle is `tests/ngv2/test_submission_quarantine_wired.py`.

# Deliverables

New file `ngv2/submission_quarantine.py` — ship this VALIDATED implementation verbatim:

```python
"""Eligibility + dedup quarantine for huntr findings (P6.3).

Ports the legacy ``_not_eligible/`` quarantine: route ineligible findings
(repo not bounty-eligible, finding not live-confirmed, or below the bounty
floor) AND duplicate findings (same repo+CWE already submitted, or a
same-repo+CWE collision within the current batch) into a quarantine bucket,
so only genuinely submittable findings pass. Legacy caught 124 such findings
(real $ saved by not wasting submission slots on dups/ineligibles).

Pure and deterministic. The "already submitted" corpus is an INJECTED
parameter (hermetic) -- no file/network I/O here.

A finding is a dict carrying at least ``repo`` and ``cwe``; richer keys
(``id``, ``eligible``, ``verdict``) refine the decision.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Quarantine reason codes (precedence order).
REASON_INELIGIBLE = 'ineligible'
REASON_NOT_CONFIRMED = 'not_confirmed'
REASON_DUPLICATE_EXISTING = 'duplicate_existing'
REASON_DUPLICATE_BATCH = 'duplicate_batch'

__all__ = ['dedup_key', 'partition_findings', 'REASON_INELIGIBLE',
           'REASON_NOT_CONFIRMED', 'REASON_DUPLICATE_EXISTING',
           'REASON_DUPLICATE_BATCH']


def _norm(value: Any) -> str:
    return str(value or '').strip().lower()


def dedup_key(finding: Dict[str, Any]) -> Tuple[str, str]:
    """Canonical (repo, cwe) dedup key for a finding."""
    repo = _norm(finding.get('repo') or finding.get('repo_url'))
    cwe = _norm(finding.get('cwe') or finding.get('category'))
    return (repo, cwe)


def _is_eligible(finding: Dict[str, Any]) -> bool:
    """Default-eligible unless an explicit eligible=False is present."""
    return finding.get('eligible', True) is not False


def _is_confirmed(finding: Dict[str, Any]) -> bool:
    """If a verdict is present it must be 'confirmed'; absent => not gated here."""
    if 'verdict' not in finding:
        return True
    return _norm(finding.get('verdict')) == 'confirmed'


def partition_findings(
    findings: Iterable[Dict[str, Any]],
    existing_keys: Optional[Iterable[Tuple[str, str]]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Split findings into ``eligible`` (submittable) and ``quarantined``.

    ``existing_keys`` is an iterable of already-submitted ``(repo, cwe)`` keys
    (e.g. derived from ``huntr_existing_submissions.json``). Each quarantined
    finding is annotated with a ``quarantine_reason`` key. Within-batch
    duplicates: the FIRST occurrence of a key passes, subsequent ones are
    quarantined as ``duplicate_batch``. Returns a fresh dict; never mutates the
    caller's finding dicts in place (annotated copies are returned).
    """
    existing = {(_norm(r), _norm(c)) for (r, c) in (existing_keys or [])}
    eligible: List[Dict[str, Any]] = []
    quarantined: List[Dict[str, Any]] = []
    seen: set = set()

    for finding in findings or []:
        reason: Optional[str] = None
        key = dedup_key(finding)
        if not _is_eligible(finding):
            reason = REASON_INELIGIBLE
        elif not _is_confirmed(finding):
            reason = REASON_NOT_CONFIRMED
        elif key in existing:
            reason = REASON_DUPLICATE_EXISTING
        elif key in seen:
            reason = REASON_DUPLICATE_BATCH

        if reason is None:
            seen.add(key)
            eligible.append(dict(finding))
        else:
            annotated = dict(finding)
            annotated['quarantine_reason'] = reason
            quarantined.append(annotated)

    return {'eligible': eligible, 'quarantined': quarantined}
```

Plus the already-committed RED oracle `tests/ngv2/test_submission_quarantine_wired.py` (do not modify it).
