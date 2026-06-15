---
interfaces: "exposes `fetch_bounties(*, fetcher, base_url='https://huntr.com', rate_limiter=None, sleep=None, etag=None, cached_body=None, discovered_at='') -> (feed, list[Bounty], etag)`, `fetch_raw(...)`, `parse_feed(body) -> {repos, formats}`, `feed_to_bounties(feed, ...) -> list[Bounty]`, `make_url_fetcher()`, `FetchError`. Network behind injected fetcher seam; ETag/backoff/flock rate-limit."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

huntr bounty client (ngv2/sourcing/huntr_client.py): deterministic /bounties poller behind an injected fetcher seam, producing the {repos,formats} feed the gates consume

# Scope

Build a NEW io_adapter module ngv2/sourcing/huntr_client.py that deterministically fetches huntr's /bounties feed and parses it into the {repos:{...}, formats:{...}} shape that ngv2.bounty_gate.gate and ngv2.huntr_data.parse_bounties already consume, yielding typed ngv2.contracts.Bounty records. io_adapter discipline: the ONLY network edge -- the HTTP GET -- is behind an INJECTED `fetcher(url, headers) -> (status, body, resp_headers)` seam; per-host politeness (flock-style rate limit) and retry/backoff are driven through injected `rate_limiter(host)` and `sleep(seconds)` seams. `make_url_fetcher()` returns the production urllib-backed seam. Resilience: ETag conditional requests (304 reuses the cached body), bounded exponential-backoff retry on 429/5xx (via injected sleep, calling the rate limiter before each attempt), FetchError when retries are exhausted. Preserve legacy's load-bearing insight: /bounties is authoritative for *paid* eligibility (Bounty.eligible comes straight from the feed entry). Emit the whole file verbatim from Deliverables. Name the committed oracle tests/test_huntr_client_wired.py in the verification_command.

# Non-Goals

Do NOT make a real network call in any code path the oracle exercises -- the fetcher is injected. Do NOT parse brittle HTML (legacy fought the markup) -- parse the JSON feed tolerantly. Do NOT change bounty_gate, huntr_data, or contracts. Do NOT qualify, rank, clone, scan, or submit. No LLM, randomness, subprocess. Single new file (new sub-package module ngv2/sourcing/huntr_client.py importable as ngv2.sourcing.huntr_client -- Python namespace packages resolve it, no separate __init__.py needed); touch no other module.

# Inputs

The injected `fetcher(url, headers) -> (status:int, body:str, resp_headers:dict)`. Output `{repos, formats}` feeds ngv2.bounty_gate.gate(owner_repo, cwe, severity, *, bounties=feed) (which reads feed['repos'][owner/repo] = {eligible, tier, observed_payouts, max_paid, submissions} and feed['formats']) and ngv2.huntr_data.parse_bounties(feed) -> list[RepoBounty]. Typed records are ngv2.contracts.Bounty(platform, repo_url, package, cwe, advisory_id, tier, observed_payout=0, max_paid=0, submissions=0, eligible=False, fp_risk=0.0, discovered_at='') whose validate() requires non-empty platform/repo_url/package/cwe, non-negative payouts/submissions, fp_risk in [0,1].

# Deliverables

ngv2/sourcing/huntr_client.py with EXACTLY this content:

```python
"""Deterministic huntr bounty client (ngv2.sourcing.huntr_client).

UPGRADE of legacy's prompt-driven WebSearch/WebFetch discovery into a real,
deterministic poller. It fetches huntr's ``/bounties`` feed (authoritative for
*paid* eligibility) plus per-repo saturation, parses the response into the
``{repos:{...}, formats:{...}}`` shape that ngv2.bounty_gate / ngv2.huntr_data
already consume, and yields typed ngv2.contracts.Bounty records.

io_adapter discipline: the only network edge -- the actual HTTP GET -- is behind
an INJECTED ``fetcher`` seam, and the per-host politeness (flock rate limit) and
retry/backoff are driven through injected ``rate_limiter``/``sleep`` seams. The
oracle injects a canned response so it is hermetic and asserts both the parsed
output AND that backoff + the rate limiter were invoked. ``make_url_fetcher``
returns the production urllib-backed seam.

Resilience: ETag conditional requests (304 -> reuse cached body), bounded
exponential backoff retry on 429/5xx, and a flock-style per-host cooldown
(concept-ported from legacy services/rate_limiter.py).
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from ngv2.contracts import Bounty

# fetcher(url, headers) -> (status:int, body:str, resp_headers:dict)
Fetcher = Callable[[str, Mapping[str, str]], Tuple[int, str, Dict[str, str]]]
# rate_limiter(host) -> None  (blocks/records a per-host slot)
RateLimiter = Callable[[str], None]
Sleeper = Callable[[float], None]

DEFAULT_BASE_URL = 'https://huntr.com'
BOUNTIES_PATH = '/bounties'
MAX_RETRIES = 4
BACKOFF_BASE_SECONDS = 1.0
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


class FetchError(RuntimeError):
    """Raised when the feed cannot be fetched after exhausting retries."""


def make_url_fetcher() -> Fetcher:
    """Return the production fetcher seam backed by ``urllib``."""
    import urllib.request

    def _fetch(url: str, headers: Mapping[str, str]) -> Tuple[int, str, Dict[str, str]]:
        req = urllib.request.Request(url, headers=dict(headers))
        try:
            with urllib.request.urlopen(req) as resp:  # noqa: S310 (trusted host)
                body = resp.read().decode('utf-8', 'replace')
                return resp.status, body, dict(resp.headers)
        except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
            return exc.code, '', dict(getattr(exc, 'headers', {}) or {})
    return _fetch


def _host_of(url: str) -> str:
    """Extract the host portion of a URL for per-host rate limiting."""
    rest = url.split('://', 1)[-1]
    return rest.split('/', 1)[0]


def fetch_raw(url: str, *,
              fetcher: Fetcher,
              rate_limiter: Optional[RateLimiter] = None,
              sleep: Optional[Sleeper] = None,
              etag: Optional[str] = None,
              cached_body: Optional[str] = None,
              max_retries: int = MAX_RETRIES,
              backoff_base: float = BACKOFF_BASE_SECONDS) -> Tuple[str, Optional[str]]:
    """Fetch ``url`` with ETag + bounded exponential-backoff retry + rate limiting.

    Returns ``(body, etag)``. A 304 with a cached body reuses the cache. Retries
    429/5xx with exponential backoff via the injected ``sleep`` seam, calling the
    injected per-host ``rate_limiter`` before each attempt. Raises FetchError
    when retries are exhausted.
    """
    _sleep = sleep if sleep is not None else (lambda _s: None)
    host = _host_of(url)
    headers: Dict[str, str] = {'Accept': 'application/json',
                               'User-Agent': 'ngv2-huntr-client/1.0'}
    if etag:
        headers['If-None-Match'] = etag
    last_status = None
    for attempt in range(max_retries):
        if rate_limiter is not None:
            rate_limiter(host)
        status, body, resp_headers = fetcher(url, headers)
        last_status = status
        if status == 304 and cached_body is not None:
            return cached_body, etag
        if status == 200:
            new_etag = resp_headers.get('ETag') or resp_headers.get('Etag') or etag
            return body, new_etag
        if status in RETRY_STATUS:
            _sleep(backoff_base * (2 ** attempt))
            continue
        raise FetchError('huntr fetch failed (status=%s) for %s' % (status, url))
    raise FetchError('huntr fetch exhausted %d retries (last status=%s) for %s'
                     % (max_retries, last_status, url))


def parse_feed(body: str) -> Dict[str, Any]:
    """Parse a ``/bounties`` JSON body into the ``{repos, formats}`` shape.

    Tolerant: accepts the canonical ``{"repos": {...}, "formats": {...}}`` object
    or a bare list of bounty records and folds them into ``repos``. Missing
    sections default to empty. Never raises on a well-formed-but-sparse feed.
    """
    try:
        data = json.loads(body) if body else {}
    except ValueError:
        data = {}
    repos: Dict[str, Any] = {}
    formats: Dict[str, Any] = {}
    if isinstance(data, Mapping):
        raw_repos = data.get('repos')
        if isinstance(raw_repos, Mapping):
            repos = {str(k): v for k, v in raw_repos.items()}
        raw_formats = data.get('formats')
        if isinstance(raw_formats, Mapping):
            formats = {str(k): v for k, v in raw_formats.items()}
        raw_list = data.get('bounties')
        if isinstance(raw_list, Sequence) and not isinstance(raw_list, str):
            for rec in raw_list:
                if isinstance(rec, Mapping) and rec.get('repo'):
                    repos.setdefault(str(rec['repo']), _repo_entry(rec))
    elif isinstance(data, Sequence) and not isinstance(data, str):
        for rec in data:
            if isinstance(rec, Mapping) and rec.get('repo'):
                repos.setdefault(str(rec['repo']), _repo_entry(rec))
    return {'repos': repos, 'formats': formats}


def _repo_entry(rec: Mapping[str, Any]) -> Dict[str, Any]:
    """Fold a flat bounty record into a repo-entry the bounty gate understands."""
    return {
        'eligible': bool(rec.get('eligible', True)),
        'tier': rec.get('tier') or '',
        'observed_payouts': dict(rec.get('observed_payouts') or {}),
        'max_paid': int(rec.get('max_paid') or 0),
        'submissions': int(rec.get('submissions') or 0),
    }


def feed_to_bounties(feed: Mapping[str, Any], *, platform: str = 'huntr',
                     discovered_at: str = '') -> List[Bounty]:
    """Convert a parsed ``{repos, formats}`` feed into typed Bounty records.

    Deterministically ordered by repo name. ``/bounties`` is authoritative for
    *paid* eligibility, so ``eligible`` is taken straight from the feed entry.
    """
    repos = feed.get('repos') if isinstance(feed, Mapping) else None
    if not isinstance(repos, Mapping):
        return []
    out: List[Bounty] = []
    for repo in sorted(repos):
        info = repos[repo] if isinstance(repos[repo], Mapping) else {}
        payouts = info.get('observed_payouts') or {}
        observed = 0
        for sev in ('critical', 'high', 'medium', 'low'):
            val = payouts.get(sev)
            if isinstance(val, (int, float)) and val > 0:
                observed = int(val)
                break
        out.append(Bounty(
            platform=platform,
            repo_url='https://github.com/%s' % repo,
            package=str(repo).split('/')[-1],
            cwe=str(info.get('cwe') or 'CWE-94'),
            advisory_id=str(info.get('advisory_id') or ''),
            tier=str(info.get('tier') or ''),
            observed_payout=observed,
            max_paid=int(info.get('max_paid') or 0),
            submissions=int(info.get('submissions') or 0),
            eligible=bool(info.get('eligible', False)),
            fp_risk=float(info.get('fp_risk') or 0.0),
            discovered_at=discovered_at,
        ))
    return out


def fetch_bounties(*, fetcher: Fetcher,
                   base_url: str = DEFAULT_BASE_URL,
                   rate_limiter: Optional[RateLimiter] = None,
                   sleep: Optional[Sleeper] = None,
                   etag: Optional[str] = None,
                   cached_body: Optional[str] = None,
                   discovered_at: str = '') -> Tuple[Dict[str, Any], List[Bounty], Optional[str]]:
    """Fetch + parse the huntr ``/bounties`` feed end to end.

    Returns ``(feed, bounties, etag)`` where ``feed`` is the ``{repos, formats}``
    dict the existing gates consume, ``bounties`` is the typed Bounty list, and
    ``etag`` is the response ETag for the next conditional request.
    """
    url = base_url.rstrip('/') + BOUNTIES_PATH
    body, new_etag = fetch_raw(url, fetcher=fetcher, rate_limiter=rate_limiter,
                               sleep=sleep, etag=etag, cached_body=cached_body)
    feed = parse_feed(body)
    bounties = feed_to_bounties(feed, discovered_at=discovered_at)
    return feed, bounties, new_etag
```

Verification: `cd /home/xnihil0zer0/NobleGreedv2 && .venv/bin/python -m pytest tests/test_huntr_client_wired.py -q`
