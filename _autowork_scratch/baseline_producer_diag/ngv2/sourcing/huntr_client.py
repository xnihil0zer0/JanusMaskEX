from __future__ import annotations
import json
from ngv2.contracts import Bounty
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
var_0 = Callable[[str, Mapping[str, str]], Tuple[int, str, Dict[str, str]]]
var_1 = Callable[[str], None]
var_2 = Callable[[float], None]
var_3 = 'https://huntr.com'
var_4 = '/bounties'
var_5 = 4
var_6 = 1.0
var_7 = frozenset({429, 500, 502, 503, 504})

class FetchError(RuntimeError):
    pass

def make_url_fetcher() -> var_0:
    import urllib.request

    def _fetch(url: str, headers: Mapping[str, str]) -> Tuple[int, str, Dict[str, str]]:
        var_8 = urllib.request.Request(url, headers=dict(headers))
        try:
            with urllib.request.urlopen(var_8) as var_9:
                var_10 = var_9.read().decode('utf-8', 'replace')
                return (var_9.status, var_10, dict(var_9.headers))
        except urllib.error.HTTPError as exc:
            return (exc.code, '', dict(getattr(exc, 'headers', {}) or {}))
    return _fetch

def _host_of(url: str) -> str:
    var_8 = url.split('://', 1)[-1]
    return var_8.split('/', 1)[0]

def _bounties_url(base_url: str=var_3) -> str:
    return base_url.rstrip('/') + var_4

def fetch_raw(url: str, *, fetcher: var_0, rate_limiter: Optional[var_1]=None, sleep: Optional[var_2]=None, etag: Optional[str]=None, cached_body: Optional[str]=None, max_retries: int=var_5, backoff_base: float=var_6) -> Tuple[str, Optional[str]]:
    var_8 = sleep if sleep is not None else lambda _s: None
    var_9 = _host_of(url)
    var_10: Dict[str, str] = {'Accept': 'application/json', 'User-Agent': 'ngv2-huntr-client/1.0'}
    if etag:
        var_10['If-None-Match'] = etag
    var_11 = None
    for var_12 in range(max_retries):
        if rate_limiter is not None:
            rate_limiter(var_9)
        var_13, var_14, var_15 = fetcher(url, var_10)
        var_11 = var_13
        if var_13 == 304 and cached_body is not None:
            return (cached_body, etag)
        if var_13 == 200:
            var_16 = var_15.get('ETag') or var_15.get('Etag') or etag
            return (var_14, var_16)
        if var_13 in var_7:
            var_8(backoff_base * 2 ** var_12)
            continue
        raise FetchError('huntr fetch failed (status=%s) for %s' % (var_13, url))
    raise FetchError('huntr fetch exhausted %d retries (last status=%s) for %s' % (max_retries, var_11, url))

def parse_feed(body: str) -> Dict[str, Any]:
    try:
        var_10 = json.loads(body) if body else {}
    except ValueError:
        var_10 = {}
    var_8: Dict[str, Any] = {}
    var_9: Dict[str, Any] = {}
    if isinstance(var_10, Mapping):
        var_11 = var_10.get('repos')
        if isinstance(var_11, Mapping):
            var_8 = {str(var_15): var_16 for var_15, var_16 in var_11.items()}
        var_12 = var_10.get('formats')
        if isinstance(var_12, Mapping):
            var_9 = {str(var_15): var_16 for var_15, var_16 in var_12.items()}
        var_13 = var_10.get('bounties')
        if isinstance(var_13, Sequence) and (not isinstance(var_13, str)):
            for var_14 in var_13:
                if isinstance(var_14, Mapping) and var_14.get('repo'):
                    var_8.setdefault(str(var_14['repo']), _repo_entry(var_14))
    elif isinstance(var_10, Sequence) and (not isinstance(var_10, str)):
        for var_14 in var_10:
            if isinstance(var_14, Mapping) and var_14.get('repo'):
                var_8.setdefault(str(var_14['repo']), _repo_entry(var_14))
    return {'repos': var_8, 'formats': var_9}

def _repo_entry(rec: Mapping[str, Any]) -> Dict[str, Any]:
    return {'eligible': bool(rec.get('eligible', True)), 'tier': rec.get('tier') or '', 'observed_payouts': dict(rec.get('observed_payouts') or {}), 'max_paid': int(rec.get('max_paid') or 0), 'submissions': int(rec.get('submissions') or 0)}

def feed_to_bounties(feed: Mapping[str, Any], *, platform: str='huntr', discovered_at: str='') -> List[Bounty]:
    var_8 = feed.get('repos') if isinstance(feed, Mapping) else None
    if not isinstance(var_8, Mapping):
        return []
    var_9: List[Bounty] = []
    for var_10 in sorted(var_8):
        var_11 = var_8[var_10] if isinstance(var_8[var_10], Mapping) else {}
        var_12 = var_11.get('observed_payouts') or {}
        var_13 = 0
        for var_14 in ('critical', 'high', 'medium', 'low'):
            var_15 = var_12.get(var_14)
            if isinstance(var_15, (int, float)) and var_15 > 0:
                var_13 = int(var_15)
                break
        var_9.append(Bounty(platform=platform, repo_url='https://github.com/%s' % var_10, package=str(var_10).split('/')[-1], cwe=str(var_11.get('cwe') or 'CWE-94'), advisory_id=str(var_11.get('advisory_id') or ''), tier=str(var_11.get('tier') or ''), observed_payout=var_13, max_paid=int(var_11.get('max_paid') or 0), submissions=int(var_11.get('submissions') or 0), eligible=bool(var_11.get('eligible', False)), fp_risk=float(var_11.get('fp_risk') or 0.0), discovered_at=discovered_at))
    return var_9

def fetch_bounties(*, fetcher: var_0, base_url: str=var_3, rate_limiter: Optional[var_1]=None, sleep: Optional[var_2]=None, etag: Optional[str]=None, cached_body: Optional[str]=None, discovered_at: str='') -> Tuple[Dict[str, Any], List[Bounty], Optional[str]]:
    var_8 = _bounties_url(base_url)
    var_11, var_12 = fetch_raw(var_8, fetcher=fetcher, rate_limiter=rate_limiter, sleep=sleep, etag=etag, cached_body=cached_body)
    var_9 = parse_feed(var_11)
    var_10 = feed_to_bounties(var_9, discovered_at=discovered_at)
    return (var_9, var_10, var_12)