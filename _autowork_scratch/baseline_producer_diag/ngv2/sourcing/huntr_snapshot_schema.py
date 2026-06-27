"""Pure snapshot schema builders and deterministic writers for the three
huntr snapshot JSON files consumed by the unchanged cache loaders.

This module is pure stdlib (``json`` + ``pathlib``). It performs no network or
browser IO and never imports ``ngv2/sourcing/huntr_client.py``. Output shapes
match exactly what ``ngv2.huntr_cache_loader`` / ``ngv2.huntr_data`` /
``ngv2.huntr_eligible_cache`` consume:

    huntr_eligible_cache.json      = {"repos": [sorted "owner/repo"],
                                      "fetched_at": iso8601}
    huntr_repo_bounties.json       = {"repos": {"owner/repo": {eligible, tier,
                                      observed_payouts{critical,high,medium,low},
                                      max_paid, total_advisories, submissions,
                                      pool_note}}}
    huntr_existing_submissions.json = {"owner/repo": {"status": int,
                                       "count": int, "titles": [str, ...]}}

Writers are deterministic: byte-identical output for identical input.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List
try:
    from ngv2.huntr_cache_loader import ELIGIBLE_CACHE_FILE, EXISTING_SUBMISSIONS_FILE, REPO_BOUNTIES_FILE
except Exception:
    ELIGIBLE_CACHE_FILE = 'huntr_eligible_cache.json'
    REPO_BOUNTIES_FILE = 'huntr_repo_bounties.json'
    EXISTING_SUBMISSIONS_FILE = 'huntr_existing_submissions.json'
_PAYOUT_SEVERITIES = ('critical', 'high', 'medium', 'low')

def build_eligible_cache(repos: List[str], fetched_at: str) -> Dict[str, Any]:
    """Assemble the eligible-cache snapshot.

    ``repos`` is sorted and de-duplicated; ``fetched_at`` is passed through as
    the provided ISO8601 string (no wall-clock is read here).
    """
    unique_sorted = sorted({str(repo) for repo in repos})
    return {'repos': unique_sorted, 'fetched_at': fetched_at}

def build_repo_bounties(repo_records: Dict[str, Any]) -> Dict[str, Any]:
    """Assemble the repo-bounties snapshot from already-shaped per-repo records.

    Records are normalised to the exact expected shape with stable key order so
    the output is loader-consumable and deterministic.
    """
    repos: Dict[str, Any] = {}
    for repo in sorted(repo_records):
        record = repo_records[repo] or {}
        payouts = record.get('observed_payouts') or {}
        repos[repo] = {'eligible': bool(record.get('eligible', False)), 'tier': record.get('tier', ''), 'observed_payouts': {severity: payouts.get(severity, 0) for severity in _PAYOUT_SEVERITIES}, 'max_paid': record.get('max_paid', 0), 'total_advisories': record.get('total_advisories', 0), 'submissions': record.get('submissions', 0), 'pool_note': record.get('pool_note', '')}
    return {'repos': repos}

def build_existing_submissions(submission_records: Dict[str, Any]) -> Dict[str, Any]:
    """Assemble the existing-submissions snapshot keyed by ``owner/repo``."""
    out: Dict[str, Any] = {}
    for repo in sorted(submission_records):
        record = submission_records[repo] or {}
        out[repo] = {'status': int(record.get('status', 0)), 'count': int(record.get('count', 0)), 'titles': [str(title) for title in record.get('titles', [])]}
    return out

def write_snapshots(data_dir: str, eligible: Dict[str, Any], bounties: Dict[str, Any], submissions: Dict[str, Any]) -> None:
    """Write the three snapshot files into ``data_dir`` deterministically.

    Each file is serialised with ``sort_keys=True`` and a stable indent so that
    identical inputs always yield byte-identical files.
    """
    base = Path(data_dir)
    base.mkdir(parents=True, exist_ok=True)
    snapshots = ((ELIGIBLE_CACHE_FILE, eligible), (REPO_BOUNTIES_FILE, bounties), (EXISTING_SUBMISSIONS_FILE, submissions))
    for name, payload in snapshots:
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False)
        (base / name).write_text(text + '\n', encoding='utf-8')