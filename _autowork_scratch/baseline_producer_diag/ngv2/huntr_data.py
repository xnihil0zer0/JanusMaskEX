"""Pure, deterministic, stdlib-only parsing of huntr eligibility/bounty and
submission JSON into typed records.

This module performs no file or network I/O of its own: callers pass in
already-loaded JSON (plain ``dict``/``list`` structures). All returned
collections are deterministically ordered so that repeated calls on equal
inputs yield equal results.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Mapping

@dataclass(frozen=True)
class RepoBounty:
    """A single repository's huntr eligibility / bounty metadata."""
    repo: str
    eligible: bool = False
    tier: str = ''
    observed_payouts: dict[str, int] = field(default_factory=dict)
    max_paid: int = 0
    total_advisories: int = 0
    submissions: int = 0

def parse_bounties(data: Mapping[str, Any] | None) -> list[RepoBounty]:
    """Convert already-loaded huntr eligibility/bounty JSON into a
    deterministically ordered ``list[RepoBounty]``.

    The list is sorted by repository name so that inputs given in differing
    iteration orders produce identically ordered outputs. Missing or null
    optional fields are defaulted (never raised on).
    """
    if not data:
        return []
    repos = data.get('repos') or {}
    if not isinstance(repos, Mapping):
        return []
    bounties: list[RepoBounty] = []
    for repo in sorted(repos):
        info = repos[repo]
        if not isinstance(info, Mapping):
            info = {}
        payouts_raw = info.get('observed_payouts')
        observed_payouts: dict[str, int] = dict(payouts_raw) if isinstance(payouts_raw, Mapping) else {}
        bounties.append(RepoBounty(repo=repo, eligible=bool(info.get('eligible', False)), tier=info.get('tier') or '', observed_payouts=observed_payouts, max_paid=int(info.get('max_paid') or 0), total_advisories=int(info.get('total_advisories') or 0), submissions=int(info.get('submissions') or 0)))
    return bounties

def parse_existing_submissions(data: Mapping[str, Any] | None) -> dict[str, list[str]]:
    """Convert huntr submission JSON into a mapping of repo identifier to the
    list of existing submission titles.

    The repo identifier key matches the one used by :func:`parse_bounties`
    (``RepoBounty.repo``), enabling dedup / cross-referencing. Missing titles
    default to an empty list. Output ordering is deterministic (sorted by repo).
    """
    if not data:
        return {}
    result: dict[str, list[str]] = {}
    for repo in sorted(data):
        info = data[repo]
        if not isinstance(info, Mapping):
            result[repo] = []
            continue
        titles_raw = info.get('titles')
        if isinstance(titles_raw, (list, tuple)):
            result[repo] = [str(t) for t in titles_raw]
        else:
            result[repo] = []
    return result