"""4-tier confidence scoring from multi-tool agreement signals.

Pure, deterministic, standard-library-only. Exposes the ordered tuple of
confidence tiers (``CONFIDENCE_TIERS``) and ``classify(signals)`` which maps a
multi-tool agreement signal mapping to exactly one of those tiers.
"""
from __future__ import annotations
from typing import Any, Mapping, Tuple
CONFIDENCE_TIERS: Tuple[str, str, str, str] = ('CONFIRMED', 'HIGH', 'MEDIUM', 'LOW')

def classify(signals: Mapping[str, Any]) -> str:
    """Map multi-tool agreement ``signals`` to one of ``CONFIDENCE_TIERS``.

    ``signals`` is a mapping that may contain:
      * ``proof``: truthy when a formal proof exists (taint flow / PoC run).
      * ``tools_agree``: number of independent tools that agree on the finding.
      * ``known_fp``: truthy when the finding is a known false positive.

    Missing keys default to the no-signal case. The function is pure and
    deterministic: equal inputs always yield equal outputs.

    Rules (highest precedence first):
      * a known false positive is always ``LOW``;
      * a formal proof is ``CONFIRMED``;
      * two or more agreeing tools is ``HIGH``;
      * exactly one agreeing tool is ``MEDIUM``;
      * otherwise ``LOW``.
    """
    if not isinstance(signals, Mapping):
        raise TypeError('signals must be a mapping')
    known_fp = bool(signals.get('known_fp', False))
    if known_fp:
        return 'LOW'
    proof = bool(signals.get('proof', False))
    if proof:
        return 'CONFIRMED'
    tools_agree = signals.get('tools_agree', 0)
    try:
        agree_count = int(tools_agree)
    except (TypeError, ValueError):
        agree_count = 0
    if agree_count >= 2:
        return 'HIGH'
    if agree_count == 1:
        return 'MEDIUM'
    return 'LOW'