"""Campaign sourcing + rotation driver for NobleGreedv2 hunts.

Instead of hand-feeding a fixed list of targets, a *campaign* DISCOVERS fresh
eligible bounty repos on every run:

    refresh (best-effort, live snapshot)  ->  list eligible  ->  rank by
    expected payout  ->  EXCLUDE recently-hunted (rotation ledger)  ->  select
    top N  ->  clone each  ->  hunt each  ->  record the outcome in the ledger.

The next campaign reads the updated ledger and rotates onto the *next* N
eligible repos, so we sweep the eligible set over successive runs rather than
re-hunting the same handful.

Design: a PURE seam core (``select_targets`` + ``run_campaign``) where every
external effect -- refresh, eligibility listing, ranking, clone, hunt, ledger
I/O, and the clock -- is an injected callable. This keeps the oracle fully
hermetic (no network, no clone, no real hunt). The thin ``main`` at the bottom
wires the REAL ngv2 seams.

Ledger format (JSON, path injectable, lives under ``data/ngv2/`` in live use)::

    {"hunted": {"owner/repo": {"last": "<iso>", "count": int,
                               "outcome": "<str>"}, ...}}

``load_hunted`` returns the set of currently-excluded ``owner/repo`` strings,
honouring an optional cooldown so a repo becomes re-huntable after enough time.
``record_hunted`` appends/updates a single entry.

Stdlib only in the pure core; the live ``main`` imports ngv2 seams lazily.
"""
from __future__ import annotations
import json
import os
from typing import Any
from typing import Callable
from typing import Dict
from typing import Iterable
from typing import List
from typing import Optional
from typing import Set

def select_targets(ranked_repos: Iterable[str], hunted: Any, n: int) -> List[str]:
    """Return the top ``n`` repos from ``ranked_repos`` not already hunted.

    ``ranked_repos`` is in rank order, best first. ``hunted`` is any container
    supporting ``in`` membership (a set, dict, or list of ``owner/repo``).
    Selection is deterministic, order-preserving, and de-duplicates repeated
    entries in ``ranked_repos``. A non-positive ``n`` selects nothing.
    """
    if n <= 0:
        return []
    excluded: Set[str] = set(hunted or ())
    chosen: List[str] = []
    seen: Set[str] = set()
    for repo in ranked_repos:
        if repo in excluded or repo in seen:
            continue
        seen.add(repo)
        chosen.append(repo)
        if len(chosen) >= n:
            break
    return chosen

def _read_ledger(path: str) -> Dict[str, Any]:
    """Load the ledger JSON, returning an empty ledger on any I/O/parse error."""
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {'hunted': {}}
    if not isinstance(data, dict):
        return {'hunted': {}}
    hunted = data.get('hunted')
    if not isinstance(hunted, dict):
        data['hunted'] = {}
    return data

def _iso_seconds(value: Any) -> Optional[float]:
    """Best-effort parse of an ISO-8601 timestamp to epoch seconds, else None."""
    if not isinstance(value, str) or not value:
        return None
    import datetime
    text = value.strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        return datetime.datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None

def load_hunted(path: str, *, now: Optional[str]=None, cooldown_hours: Optional[float]=None) -> Set[str]:
    """Return the set of ``owner/repo`` to EXCLUDE from the next campaign.

    With no ``cooldown_hours`` every ledger entry is excluded permanently
    (rotate once through the eligible set). With a positive ``cooldown_hours``
    and a parseable ``now``, an entry whose last-hunt timestamp is older than
    the cooldown becomes re-huntable and is dropped from the exclusion set.
    """
    ledger = _read_ledger(path)
    hunted = ledger.get('hunted', {})
    if not cooldown_hours or cooldown_hours <= 0:
        return set(hunted.keys())
    now_s = _iso_seconds(now)
    if now_s is None:
        return set(hunted.keys())
    cutoff = now_s - cooldown_hours * 3600.0
    excluded: Set[str] = set()
    for repo, entry in hunted.items():
        last = entry.get('last') if isinstance(entry, dict) else None
        last_s = _iso_seconds(last)
        if last_s is None or last_s >= cutoff:
            excluded.add(repo)
    return excluded

def record_hunted(path: str, owner_repo: str, outcome: str, now: str) -> Dict[str, Any]:
    """Append/update one ledger entry and persist it; return the entry written.

    Increments the repo's hunt ``count``, stamps ``last`` with ``now``, and
    stores the latest ``outcome``. Creates the parent directory if needed.
    """
    ledger = _read_ledger(path)
    hunted = ledger['hunted']
    prev = hunted.get(owner_repo) if isinstance(hunted.get(owner_repo), dict) else {}
    count = int(prev.get('count', 0)) + 1
    entry = {'last': now, 'count': count, 'outcome': outcome}
    hunted[owner_repo] = entry
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(ledger, fh, indent=2, sort_keys=True)
    return entry

def run_campaign(*, refresh: Callable[[], Any], list_eligible: Callable[[], Iterable[str]], rank: Callable[[Iterable[str]], List[str]], load_hunted: Callable[[], Any], record_hunted: Callable[[str, str, str], Any], clone: Callable[[str], Any], hunt: Callable[[str, Any], Any], n: int, now: Callable[[], str]) -> Dict[str, Any]:
    """Drive one campaign over injected seams; return a summary dict.

    Order of effects:

    1. ``refresh()`` -- best-effort live snapshot; any exception is captured in
       the summary but is NEVER fatal.
    2. ``list_eligible()`` -- the current eligible ``owner/repo`` universe.
    3. ``rank(eligible)`` -- eligible repos in rank order (best payout first).
    4. ``load_hunted()`` -- already-hunted repos to exclude (rotation).
    5. ``select_targets(ranked, hunted, n)`` -- top N fresh targets.
    6. For each selected target: ``clone(repo)`` -> ``hunt(repo, clone)`` ->
       ``record_hunted(repo, outcome, now())``. A failure in clone or hunt for
       ONE target is caught, recorded as an error outcome, and does NOT abort
       the remaining targets.

    Every external effect is an injected seam, so the function performs no I/O
    of its own and is fully hermetic under test.
    """
    summary: Dict[str, Any] = {'refreshed': False, 'refresh_error': None, 'eligible_count': 0, 'selected': [], 'results': []}
    try:
        refresh()
        summary['refreshed'] = True
    except Exception as exc:
        summary['refresh_error'] = repr(exc)
    eligible = list(list_eligible() or [])
    summary['eligible_count'] = len(eligible)
    ranked = list(rank(eligible) or [])
    hunted = load_hunted()
    selected = select_targets(ranked, hunted, n)
    summary['selected'] = list(selected)
    for repo in selected:
        result: Dict[str, Any] = {'repo': repo, 'outcome': None, 'error': None, 'hunt_result': None}
        try:
            clone_obj = clone(repo)
            hunt_result = hunt(repo, clone_obj)
            result['hunt_result'] = hunt_result
            result['outcome'] = _outcome_of(hunt_result)
        except Exception as exc:
            result['error'] = repr(exc)
            result['outcome'] = 'error'
        try:
            record_hunted(repo, result['outcome'], now())
        except Exception as exc:
            result.setdefault('ledger_error', repr(exc))
        summary['results'].append(result)
    return summary

def _outcome_of(hunt_result: Any) -> str:
    """Derive a coarse outcome string from a hunt result dict.

    Reads the conductor loop's ``final_step`` phase/status when present;
    otherwise falls back to ``"completed"``. Never raises.
    """
    if isinstance(hunt_result, dict):
        final = hunt_result.get('final_step')
        if isinstance(final, dict):
            for key in ('phase', 'status', 'state'):
                val = final.get(key)
                if isinstance(val, str) and val:
                    return val
        for key in ('phase', 'status', 'state', 'outcome'):
            val = hunt_result.get(key)
            if isinstance(val, str) and val:
                return val
    return 'completed'
_LEDGER_FILE = 'campaign_ledger.json'

def _utc_now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

def _build_real_seams(args: Any) -> Dict[str, Any]:
    """Assemble the REAL ngv2 seams for a live campaign.

    Imports are lazy so importing this module (and running the hermetic oracle)
    never pulls in the live ngv2 sourcing/clone/hunt stack.
    """
    from ngv2.sourcing import huntr_refresh
    from ngv2.sourcing.huntr_client import make_url_fetcher
    from ngv2 import huntr_cache_loader
    from ngv2 import prioritize
    from ngv2.acquisition.cloner import clone_target
    from ngv2 import run_hunt as run_hunt_mod
    data_dir = args.data_dir
    ledger_path = os.path.join(data_dir, _LEDGER_FILE)
    fetcher = make_url_fetcher()

    def _refresh() -> Any:
        if args.no_refresh:
            return {'short_circuited': True, 'skipped': True}
        return huntr_refresh.refresh(fetcher, data_dir, _utc_now_iso())

    def _list_eligible() -> List[str]:
        cache = huntr_cache_loader.load_cache(data_dir) or {}
        repos = cache.get('repos') or []
        return [str(r).strip().lower() for r in repos if str(r).strip()]

    def _rank(eligible: Iterable[str]) -> List[str]:
        from ngv2.demand_source_merge import merge_expected_payout
        bounties_raw = (huntr_cache_loader.load_repo_bounties(data_dir) or {}).get('repos') or {}
        sev = str(args.severity).strip().lower()
        rankable: List[Dict[str, Any]] = []
        for slug in eligible:
            rec = bounties_raw.get(slug) if isinstance(bounties_raw.get(slug), dict) else {}
            payout = merge_expected_payout(None, rec, sev)
            entry: Dict[str, Any] = {'repo': slug, 'observed_payouts': {sev: int(payout)}, 'max_paid': int(rec.get('max_paid') or 0), 'total_advisories': int(rec.get('total_advisories') or 0)}
            rankable.append(entry)
        ranked = prioritize.rank_targets(rankable, severity=sev)
        return [b['repo'] for b in ranked]

    def _load_hunted() -> Set[str]:
        return load_hunted(ledger_path, now=_utc_now_iso(), cooldown_hours=args.cooldown_hours)

    def _record(owner_repo: str, outcome: str, now_iso: str) -> Any:
        return record_hunted(ledger_path, owner_repo, outcome, now_iso)

    def _clone(owner_repo: str) -> Any:
        repo_url = 'https://github.com/%s' % owner_repo
        return clone_target(repo_url, dest_root=args.clone_root)

    def _hunt(owner_repo: str, target: Any) -> Any:
        repo_root = getattr(target, 'repo_root')
        session_id = 'campaign-%s' % owner_repo.replace('/', '-')
        db_path = os.path.join(args.db_dir, '%s.sqlite' % session_id)
        out_dir = os.path.join(args.out_dir, session_id)
        os.makedirs(args.db_dir, exist_ok=True)
        os.makedirs(out_dir, exist_ok=True)
        return run_hunt_mod.run_hunt(session_id, repo_root, repo_root, db_path, out_dir, max_steps=args.max_steps)
    return {'refresh': _refresh, 'list_eligible': _list_eligible, 'rank': _rank, 'load_hunted': _load_hunted, 'record_hunted': _record, 'clone': _clone, 'hunt': _hunt, 'now': _utc_now_iso}

def parse_args(argv: Optional[List[str]]=None) -> Any:
    import argparse
    p = argparse.ArgumentParser(prog='ngv2.campaign')
    p.add_argument('--targets', type=int, default=6, dest='targets', help='number of fresh targets to hunt this campaign')
    p.add_argument('--max-steps', type=int, default=50, dest='max_steps')
    p.add_argument('--db-dir', default='state/campaign/db', dest='db_dir')
    p.add_argument('--out-dir', default='state/campaign/out', dest='out_dir')
    p.add_argument('--data-dir', default='data/ngv2', dest='data_dir')
    p.add_argument('--clone-root', default='tmp/campaign', dest='clone_root')
    p.add_argument('--severity', default='critical', dest='severity')
    p.add_argument('--cooldown-hours', type=float, default=None, dest='cooldown_hours', help='re-hunt a repo only after this many hours; omit for permanent rotation')
    p.add_argument('--no-refresh', action='store_true', dest='no_refresh')
    return p.parse_args(argv)

def main(argv: Optional[List[str]]=None) -> int:
    args = parse_args(argv)
    seams = _build_real_seams(args)
    summary = run_campaign(n=args.targets, **seams)
    print(json.dumps(summary, default=str, sort_keys=True))
    return 0
if __name__ == '__main__':
    import sys
    sys.exit(main())