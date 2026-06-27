"""Wired ``huntr_refresh`` entrypoint.

Composes the sibling sourcing seams into one entrypoint:

    fetch_bounties_index -> parse_bounties_index   (eligibility authority)
    fetch_hacktivity     -> parse_hacktivity       (recent records)
    build_* + write_snapshots                      (the three snapshot files)

Eligibility comes ONLY from the /bounties index (a plain GET; the index repo
list is server-rendered HTML, not flight). A repo seen in hacktivity but absent
from the index is NOT eligible. A pre-existing eligible-cache snapshot whose
``fetched_at`` is still fresh short-circuits with zero fetcher calls. The
written files are consumed unchanged by ``ngv2.huntr_cache_loader.load_cache``.
"""
from __future__ import annotations
import json
import os
from typing import Any, Callable, Dict, List, Set, Tuple
from ngv2.huntr_cache_loader import ELIGIBLE_CACHE_FILE
from ngv2.sourcing.huntr_snapshot_schema import build_eligible_cache, build_repo_bounties, build_existing_submissions, write_snapshots
from ngv2.sourcing.huntr_page_parser import parse_hacktivity, parse_repo_page, parse_bounties_index
from ngv2.sourcing.browser_fetcher import fetch_bounties_index, fetch_hacktivity, fetch_repo_page
from ngv2.sourcing.refresh_policy import is_stale
_MAX_AGE_HOURS = 24.0

def _severity_bucket(amount: float) -> str:
    """Bucket an observed payout into a coarse severity band."""
    if amount >= 3000:
        return 'critical'
    if amount >= 1000:
        return 'high'
    if amount >= 500:
        return 'medium'
    return 'low'

def _build_records(records: List[Dict[str, Any]], eligible: Set[str]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Fold hacktivity records into per-repo bounty + submission inputs.

    Only repos present in the eligible index are surfaced; the repo identity is
    ``f"{owner}/{name}".lower()`` taken from each record's ``repository``.
    """
    repo_records: Dict[str, Any] = {}
    submission_records: Dict[str, Any] = {}
    for rec in records:
        repo = rec.get('repository') or {}
        owner = repo.get('owner')
        name = repo.get('name')
        if not owner or not name:
            continue
        slug = f'{owner}/{name}'.lower()
        if slug not in eligible:
            continue
        amount = (rec.get('disclosure') or {}).get('amount') or 0
        bounty = repo_records.get(slug)
        if bounty is None:
            bounty = {'eligible': True, 'tier': 'low', 'observed_payouts': {'critical': 0, 'high': 0, 'medium': 0, 'low': 0}, 'max_paid': 0, 'total_advisories': 0, 'submissions': 0, 'pool_note': None}
            repo_records[slug] = bounty
        band = _severity_bucket(amount)
        if amount > bounty['observed_payouts'][band]:
            bounty['observed_payouts'][band] = amount
        bounty['max_paid'] = max(bounty['max_paid'], amount)
        bounty['total_advisories'] += 1
        bounty['submissions'] += 1
        bounty['tier'] = _severity_bucket(bounty['max_paid'])
        sub = submission_records.get(slug)
        if sub is None:
            sub = {'status': 200, 'count': 0, 'titles': []}
            submission_records[slug] = sub
        title = rec.get('title')
        if title:
            sub['titles'].append(title)
            sub['count'] = len(sub['titles'])
    return (repo_records, submission_records)

def refresh(fetcher: Callable[..., Any], data_dir: str, now: str) -> Dict[str, Any]:
    """Fetch, parse, apply freshness policy, and write the three snapshots.

    Returns a summary dict that always reports ``eligible_count``.
    """
    cache_path = os.path.join(data_dir, ELIGIBLE_CACHE_FILE)
    if os.path.isfile(cache_path):
        with open(cache_path, 'r', encoding='utf-8') as fh:
            existing = json.load(fh)
        fetched_at = existing.get('fetched_at')
        if fetched_at and (not is_stale(fetched_at, now, _MAX_AGE_HOURS)):
            repos = existing.get('repos') or []
            return {'eligible_count': len(repos), 'repo_count': 0, 'submission_count': 0, 'fetched_at': fetched_at, 'short_circuited': True}
    index_body = fetch_bounties_index(fetcher)
    eligible_repos = sorted(set(parse_bounties_index(index_body)))
    feed_body = fetch_hacktivity(fetcher)
    records = parse_hacktivity(feed_body)
    repo_records, submission_records = _build_records(records, set(eligible_repos))
    eligible = build_eligible_cache(eligible_repos, now)
    bounties = build_repo_bounties(repo_records)
    submissions = build_existing_submissions(submission_records)
    write_snapshots(data_dir, eligible, bounties, submissions)
    return {'eligible_count': len(eligible_repos), 'repo_count': len(repo_records), 'submission_count': len(submission_records), 'fetched_at': now, 'short_circuited': False}