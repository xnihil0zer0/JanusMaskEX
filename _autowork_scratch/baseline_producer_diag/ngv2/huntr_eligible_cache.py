"""Deterministic huntr.com bounty eligibility lookup.

A repo is "eligible" if its normalized ``owner/repo`` string appears in a
previously-fetched huntr bounties cache. Cache I/O is an INJECTED SEAM: this
module is a pure shell driven by a zero-argument ``load_cache()`` callable that
returns either a cache dict ``{"repos": [...], "fetched_at": str}`` or ``None``
when no cache exists. The real fetch/file-read lives at NGv2 runtime; every
function here is pure, deterministic, and performs no file or network I/O.

Stdlib-only.
"""
from typing import Callable, Dict, List, Optional
ELIGIBLE_RESULT_FIELDS = ('repo', 'eligible', 'total_eligible_repos', 'cache_date', 'reason')
NO_CACHE_REASON = 'no huntr bounties cache available'

def normalize_repo(owner_repo: str) -> str:
    """Strip surrounding whitespace and lowercase the repo identifier."""
    return owner_repo.strip().lower()

def make_mock_cache(repos: List[str], fetched_at: str='unknown') -> Callable[[], Dict[str, object]]:
    """Return a zero-argument callable yielding a cache dict.

    The returned callable always produces a fresh dict containing a copy of
    ``repos`` under ``'repos'`` and the ``fetched_at`` value, so callers cannot
    mutate the original inputs through the cache.
    """
    snapshot = list(repos)

    def _loader() -> Dict[str, object]:
        return {'repos': list(snapshot), 'fetched_at': fetched_at}
    return _loader

def check_eligible(owner_repo: str, load_cache: Optional[Callable[[], Optional[Dict[str, object]]]]=None) -> Dict[str, object]:
    """Decide huntr bounty eligibility for ``owner_repo`` using a cache seam.

    Returns a fresh dict keyed by :data:`ELIGIBLE_RESULT_FIELDS`. When no cache
    is available (``load_cache`` is ``None`` or returns ``None``), ``eligible``
    is ``None`` and ``reason`` is :data:`NO_CACHE_REASON`.
    """
    target = normalize_repo(owner_repo)
    cache = load_cache() if load_cache is not None else None
    if cache is None:
        return {'repo': target, 'eligible': None, 'total_eligible_repos': 0, 'cache_date': 'unknown', 'reason': NO_CACHE_REASON}
    raw_repos = cache.get('repos') or []
    distinct = {normalize_repo(r) for r in raw_repos}
    fetched_at = cache.get('fetched_at')
    cache_date = fetched_at if fetched_at else 'unknown'
    return {'repo': target, 'eligible': target in distinct, 'total_eligible_repos': len(distinct), 'cache_date': cache_date, 'reason': ''}