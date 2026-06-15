---
interfaces: "exposes `rank_candidates(candidates, *, cwe='CWE-94', severity='HIGH', purpose='hunt') -> list[(repo, score, oracle_result)]` (GO survivors only, sorted score desc then repo) and `score_candidate(expected_payout, submissions, days_since_audit, *, cwe_already_seen=False) -> int` (saturation-dominant 0..100)."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

Selection ranker + work queue (ngv2/selection_ranker.py): hard 5-gate filter merged with the saturation-dominant soft score

# Scope

Build a NEW pure, stdlib+ngv2-only module ngv2/selection_ranker.py that turns a list of sourced bounty candidates into a ranked work queue. It (a) runs the live ngv2.target_qualify.qualify HARD 5-gate per candidate (bounty -> saturation>50 -> freshness<7d -> fp-advisory) and DROPS any non-GO (ineligible / saturated / recently-audited) candidate; (b) scores each GO survivor with the saturation-dominant soft weights ported from legacy services/tools/target_priority_scorer.py (0 subs -> +25, <=3 -> +20, <=10 -> +12, <=20 -> +5, else 0; bounty $ deliberately MINOR: >=1500 -> +10, >=900 -> +7, >=600 -> +5, >0 -> +3, else +1; freshness by audit age); (c) models same-CWE dedup/consolidation (legacy "pickle fatigue": N same-CWE findings != N payouts) so a repo already submitted for that CWE loses its marginal bounty credit; and (d) emits a deterministic list of (repo, score, oracle_result) sorted by score descending then repo name. All facts are injected per candidate so the module is pure, total, and hermetic. Emit the whole file verbatim from Deliverables. Name the committed oracle tests/test_selection_ranker_wired.py in the verification_command.

# Non-Goals

Do NOT re-implement the qualification gate -- call ngv2.target_qualify.qualify. Do NOT scrape, read files, or hit the network/clock (every fact is an injected candidate field). Do NOT change target_qualify, bounty_gate, batch_qualify, or source_qualify_gate. No LLM, subprocess, randomness, or threading. Single new file; touch no other module.

# Inputs

Consumes ngv2.target_qualify.qualify(target, cwe, severity, purpose, *, bounty=None, submissions=0, days_ago=None, fp_patterns=None, cap_newer=False) -> {"decision":"GO"|"SKIP"|"UNKNOWN", "target":..., ...}. The injected per-candidate ``bounty`` is the bounty-gate decision dict carrying keys ``decision`` and ``expected_payout``. Each candidate mapping has: ``repo`` (str), ``bounty`` (dict|None), ``submissions`` (int), ``days_ago`` (float|None), ``fp_patterns`` (list|None), optional ``cwe``/``severity`` overrides, and optional ``known_cwes`` (CWEs already submitted for that repo -> dedup).

# Deliverables

ngv2/selection_ranker.py with EXACTLY this content:

```python
"""Selection ranker + work queue for sourced bounty candidates.

Merges the HARD 5-gate (ngv2.target_qualify.qualify: bounty -> saturation>50 ->
freshness<7d -> fp-advisory) with a SOFT, saturation-dominant priority score
(ported from legacy services/tools/target_priority_scorer.py weights: a virgin
target with 0 submissions outweighs a high-bounty saturated one). Only GO
candidates enter the queue; SKIP/UNKNOWN (ineligible, saturated, recently
audited) drop. The queue is sorted by score descending, ties broken by repo name
for determinism.

Pure + stdlib-only: every external fact (the bounty decision, saturation count,
audit age, FP patterns) is injected per candidate. No network/clock/disk.

Dedup/consolidation (legacy "pickle fatigue" lesson: N same-CWE findings != N
payouts): a candidate carries a ``known_cwes`` set; if its CWE is already
represented for that repo the consolidation factor zeroes the marginal bounty
contribution so saturated-by-our-own-prior-work targets sink.
"""
from __future__ import annotations
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ngv2.target_qualify import qualify as _qualify

# Saturation weight table (submissions -> score), saturation-dominant.
def _saturation_score(submissions: int) -> int:
    if submissions <= 0:
        return 25
    if submissions <= 3:
        return 20
    if submissions <= 10:
        return 12
    if submissions <= 20:
        return 5
    return 0


# Bounty weight table (expected payout $ -> score), deliberately MINOR.
def _bounty_score(expected_payout: int) -> int:
    if expected_payout >= 1500:
        return 10
    if expected_payout >= 900:
        return 7
    if expected_payout >= 600:
        return 5
    if expected_payout > 0:
        return 3
    return 1


# Freshness weight table (days since last audit -> score).
def _freshness_score(days_since_audit: Optional[float]) -> int:
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


def score_candidate(expected_payout: int, submissions: int,
                    days_since_audit: Optional[float], *,
                    cwe_already_seen: bool = False) -> int:
    """Compute the soft priority score for a GO candidate (0..100)."""
    sat = _saturation_score(submissions)
    bounty = 0 if cwe_already_seen else _bounty_score(expected_payout)
    fresh = _freshness_score(days_since_audit)
    return min(sat + bounty + fresh, 100)


def rank_candidates(candidates: Sequence[Mapping[str, Any]], *,
                    cwe: str = 'CWE-94', severity: str = 'HIGH',
                    purpose: str = 'hunt') -> List[Tuple[str, int, Dict[str, Any]]]:
    """Qualify + score + rank candidate repos into a work queue.

    Each candidate is a mapping with: ``repo`` (str), ``bounty`` (the bounty-gate
    decision dict or None), ``submissions`` (int), ``days_ago`` (float|None),
    ``fp_patterns`` (list|None), and optionally ``cwe``/``severity`` overrides and
    ``known_cwes`` (a set/list of CWEs already submitted for that repo -> dedup).

    Returns a list of ``(repo, score, oracle_result)`` for the GO candidates only,
    sorted by score descending then repo name. ``oracle_result`` is the full
    target_qualify result dict so downstream consumers keep the gate trace.
    """
    queue: List[Tuple[str, int, Dict[str, Any]]] = []
    for cand in candidates:
        repo = str(cand.get('repo', ''))
        c_cwe = str(cand.get('cwe') or cwe)
        c_sev = str(cand.get('severity') or severity)
        bounty = cand.get('bounty')
        submissions = int(cand.get('submissions') or 0)
        days_ago = cand.get('days_ago')
        fp_patterns = cand.get('fp_patterns')
        result = _qualify(repo, c_cwe, c_sev, purpose,
                          bounty=bounty, submissions=submissions,
                          days_ago=days_ago, fp_patterns=fp_patterns)
        if result.get('decision') != 'GO':
            continue
        expected = bounty.get('expected_payout') if isinstance(bounty, Mapping) else 0
        try:
            expected = int(expected) if expected else 0
        except (TypeError, ValueError):
            expected = 0
        known = cand.get('known_cwes') or ()
        cwe_seen = any(str(k).strip().upper() == c_cwe.strip().upper() for k in known)
        score = score_candidate(expected, submissions, days_ago, cwe_already_seen=cwe_seen)
        queue.append((repo, score, result))
    queue.sort(key=lambda item: (-item[1], item[0]))
    return queue
```

Verification: `cd /home/xnihil0zer0/NobleGreedv2 && .venv/bin/python -m pytest tests/test_selection_ranker_wired.py -q`
