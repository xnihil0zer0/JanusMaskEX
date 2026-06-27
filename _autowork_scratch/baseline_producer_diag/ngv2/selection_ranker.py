"""Selection ranker: merge the live HARD 5-gate with a saturation-dominant SOFT score.

This module turns a list of injected bounty candidates into a deterministic ranked
work queue. It does NOT reimplement qualification logic: the hard 5-gate is delegated
to :func:`ngv2.target_qualify.qualify` (aliased ``_qualify``) and invoked once per
candidate. Candidates whose gate verdict is not ``GO`` are dropped; survivors are
scored with the legacy "pickle fatigue" priority tables ported from
``services/tools/target_priority_scorer.py``.

The weight tables encode two lessons:

* **Saturation dominates bounty.** A virgin target (0 submissions) is worth far more
  than a high-bounty but heavily-mined one.
* **Same-CWE prior work zeroes the marginal bounty credit**, so targets whose CWE we
  have already mined sink in the ranking.

The module is pure: standard library + ngv2 only. No network, clock, disk,
subprocess, randomness, or threading.
"""
from __future__ import annotations
from collections.abc import Iterable, Mapping
from typing import Any, List, Optional, Tuple
from ngv2.target_qualify import qualify as _qualify
__all__ = ['rank_candidates', 'score_candidate']

def _saturation_score(submissions: Optional[int]) -> int:
    """Saturation-dominant weight: fewer prior submissions is worth far more."""
    count = submissions or 0
    if count <= 0:
        return 25
    if count <= 3:
        return 20
    if count <= 10:
        return 12
    if count <= 20:
        return 5
    return 0

def _bounty_score(expected_payout: Optional[int]) -> int:
    """Deliberately MINOR bounty weight: money is a tie-breaker, not a driver."""
    payout = expected_payout or 0
    if payout >= 1500:
        return 10
    if payout >= 900:
        return 7
    if payout >= 600:
        return 5
    if payout > 0:
        return 3
    return 1

def _freshness_score(days_since_audit: Optional[int]) -> int:
    """Freshness weight by audit age; unknown age scores a neutral +5."""
    if days_since_audit is None:
        return 5
    if days_since_audit < 7:
        return 0
    if days_since_audit < 30:
        return 3
    if days_since_audit < 90:
        return 5
    if days_since_audit < 365:
        return 8
    return 10

def score_candidate(
    expected_payout: int,
    submissions: int,
    days_since_audit,
    *,
    cwe_already_seen: bool = False,
    demand_score: int = 0,
    confirmability: float = 1.0,
) -> int:
    """Soft, saturation-dominant score in 0..100 for a candidate target.

    The ranking weights are deliberately ordered so that *saturation* (how
    heavily a repo has already been mined) dominates the comparatively minor
    bounty / recency / demand nudges -- a virgin target should outrank a
    saturated, high-bounty one.

    Parameters
    ----------
    expected_payout:
        Expected bounty payout; contributes a small additive bounty credit.
    submissions:
        Prior submissions against the repo; more submissions => lower score.
    days_since_audit:
        Days since the last audit (``None`` == never audited, most stale and
        therefore most attractive).
    cwe_already_seen:
        When ``True`` we have already submitted this CWE for the target, so
        the marginal bounty credit is zeroed (dedup).
    demand_score:
        Keyword-only, additive under the 100 cap. A minor demand nudge that
        defaults to ``0`` so existing call sites are byte-identical.
    confirmability:
        Keyword-only final multiplier applied to the (capped) score; defaults
        to ``1.0`` (identity). ``0.0`` zeroes the score.
    """
    # --- saturation (dominant weight, max 25): virgin repos earn the full
    # weight, decaying as the repo accumulates submissions.
    saturation = 25 - 5 * ((submissions + 3) // 4)
    if saturation < 0:
        saturation = 0

    # --- bounty credit (minor): zeroed when this CWE was already submitted.
    if cwe_already_seen:
        bounty = 0
    else:
        bounty = (expected_payout * 3) // 500

    # --- recency (minor, max 6): never-audited (None) is most attractive;
    # older audits beat more recent ones.
    if days_since_audit is None:
        recency = 6
    else:
        recency = days_since_audit // 6
        if recency > 6:
            recency = 6
        elif recency < 0:
            recency = 0

    # Base score plus the additive demand nudge, clamped to the 100 cap
    # *before* the confirmability multiplier is applied.
    base = saturation + bounty + recency + int(demand_score)
    if base > 100:
        base = 100
    elif base < 0:
        base = 0

    final = int(base * confirmability)
    if final > 100:
        final = 100
    elif final < 0:
        final = 0
    return final

def _coerce_payout(bounty: Any) -> int:
    """Robustly extract expected_payout from an injected bounty mapping.

    A missing/non-Mapping bounty, or a None/non-int payout, yields 0.
    """
    if not isinstance(bounty, Mapping):
        return 0
    raw = bounty.get('expected_payout')
    if isinstance(raw, bool) or not isinstance(raw, int):
        return 0
    return raw

def _cwe_already_seen(cwe: str, known_cwes: Any) -> bool:
    """Case-insensitive, whitespace-stripped membership test against known CWEs."""
    if not known_cwes or not isinstance(known_cwes, Iterable) or isinstance(known_cwes, (str, bytes)):
        return False
    needle = str(cwe).strip().lower()
    return any((str(known).strip().lower() == needle for known in known_cwes))

def _is_go(oracle_result: Any) -> bool:
    """True only for a GO verdict; SKIP/UNKNOWN and anything else are dropped."""
    if isinstance(oracle_result, Mapping):
        decision = oracle_result.get('decision')
    else:
        decision = getattr(oracle_result, 'decision', None)
    return str(decision).strip().upper() == 'GO'

def rank_candidates(candidates: Iterable[Mapping[str, Any]], *, cwe: str='CWE-94', severity: str='HIGH', purpose: str='hunt') -> List[Tuple[str, int, Any]]:
    """Rank injected candidates into a GO-only, deterministically sorted work queue.

    Each candidate is a mapping that may override ``cwe``/``severity`` and carries the
    injected facts (repo, bounty mapping, submissions, days_ago, fp_patterns,
    known_cwes). The hard 5-gate is delegated to :func:`_qualify`; only GO survivors
    are scored and returned, sorted by score descending then repo name ascending.
    """
    queue: List[Tuple[str, int, Any]] = []
    for candidate in candidates:
        repo = candidate.get('repo')
        cand_cwe = candidate.get('cwe', cwe)
        cand_severity = candidate.get('severity', severity)
        bounty = candidate.get('bounty')
        submissions = candidate.get('submissions') or 0
        days_ago = candidate.get('days_ago')
        fp_patterns = candidate.get('fp_patterns')
        expected_payout = _coerce_payout(bounty)
        cwe_seen = _cwe_already_seen(cand_cwe, candidate.get('known_cwes'))
        oracle_result = _qualify(repo, cand_cwe, cand_severity, purpose, bounty=bounty, submissions=submissions, days_ago=days_ago, fp_patterns=fp_patterns)
        if not _is_go(oracle_result):
            continue
        score = score_candidate(expected_payout, submissions, days_ago, cwe_already_seen=cwe_seen)
        queue.append((repo, score, oracle_result))
    queue.sort(key=lambda row: (-row[1], row[0]))
    return queue