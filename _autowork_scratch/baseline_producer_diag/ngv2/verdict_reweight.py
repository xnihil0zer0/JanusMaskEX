"""Phase-7.2b consumer: turn huntr SubmissionVerdicts into a prior-reweight map.

This module converts an iterable of huntr verdicts into a deterministic
``{repo_key: float}`` multiplier map meant to be multiplied into the Phase-1
prioritizer's expected_payout. It is a NEW consumer module only -- it does NOT
touch ngv2.prioritize / ngv2.selection_ranker (anti-seesaw).

Pure stdlib: no clock, network, randomness, LLM, or ngv2 sibling import.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, Mapping
ACCEPT_BONUS = 0.25
PAYOUT_BONUS = 0.25
REJECT_PENALTY = 0.3
NEUTRAL = 1.0
_MIN, _MAX = (0.1, 3.0)

def _clamp(value: float) -> float:
    """Clamp ``value`` into the closed interval [_MIN, _MAX]."""
    if value < _MIN:
        return _MIN
    if value > _MAX:
        return _MAX
    return value

def _state(v: Any) -> str:
    """Read the verdict state from a Mapping or an object exposing ``.state``.

    Normalizes to a stripped lowercase string; returns '' on failure.
    """
    if isinstance(v, Mapping):
        raw = v.get('state')
    else:
        raw = getattr(v, 'state', None)
    if raw is None:
        return ''
    try:
        return str(raw).strip().lower()
    except Exception:
        return ''

def _payout(v: Any) -> float:
    """Read the verdict payout from a Mapping or an object exposing ``.payout``.

    Returns a float, or 0.0 when missing / None / non-numeric.
    """
    if isinstance(v, Mapping):
        raw = v.get('payout')
    else:
        raw = getattr(v, 'payout', None)
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0

def _key(v: Any) -> str:
    """Resolve the repo key from a verdict.

    Reads a Mapping's ``repo`` (or nested ``raw['repo']``), or an object's
    ``.raw['repo']``. Returns '' when unresolvable.
    """
    if isinstance(v, Mapping):
        repo = v.get('repo')
        if repo is None:
            raw = v.get('raw')
            if isinstance(raw, Mapping):
                repo = raw.get('repo')
    else:
        repo = getattr(v, 'repo', None)
        if repo is None:
            raw = getattr(v, 'raw', None)
            if isinstance(raw, Mapping):
                repo = raw.get('repo')
    if repo is None:
        return ''
    try:
        return str(repo).strip()
    except Exception:
        return ''

def verdict_weight_delta(verdict: Any) -> float:
    """Return a per-verdict multiplicative weight around the neutral 1.0.

    * accepted -> > 1.0 (and strictly higher when payout > 0)
    * rejected / duplicate -> < 1.0
    * any other state -> exactly 1.0

    The result is clamped to [0.1, 3.0].
    """
    state = _state(verdict)
    if state == 'accepted':
        delta = NEUTRAL + ACCEPT_BONUS
        if _payout(verdict) > 0:
            delta += PAYOUT_BONUS
    elif state in ('rejected', 'duplicate'):
        delta = NEUTRAL - REJECT_PENALTY
    else:
        return NEUTRAL
    return _clamp(delta)

def reweight_from_verdicts(verdicts: Iterable[Any]) -> Dict[str, float]:
    """Aggregate verdicts into a ``{repo_key: weight}`` multiplier map.

    Keyless verdicts are skipped. Multiple verdicts for one key compound
    multiplicatively; each cumulative product is clamped to [0.1, 3.0].
    """
    weights: Dict[str, float] = {}
    for v in verdicts:
        key = _key(v)
        if not key:
            continue
        weights[key] = weights.get(key, 1.0) * verdict_weight_delta(v)
    return {k: _clamp(w) for k, w in weights.items()}