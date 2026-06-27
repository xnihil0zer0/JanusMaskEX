"""Aggregate normalized triage verdict dicts into counts and filter true positives.

Pure/deterministic and stdlib-only. Operates on plain verdict dicts whose shape
mirrors what ``parse_triage(debate)`` and ``Verdict.to_dict()`` produce: each
verdict carries a ``'label'`` field holding a TP/FP sentinel (``'TP'`` for a true
positive, ``'FP'`` for a false positive) and a ``'confidence'`` value (one of
``'HIGH'``, ``'MEDIUM'``, ``'LOW'``). Inputs are treated as read-only; outputs are
always freshly built so neither the input verdicts nor the input collection are
mutated.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Mapping
__all__ = ['aggregate', 'keep_true_positives']
_TP_LABEL = 'TP'
_CONFIDENCE_LEVELS = ('HIGH', 'MEDIUM', 'LOW')
Verdict = Mapping[str, Any]

def aggregate(verdicts: Iterable[Verdict]) -> Dict[str, Any]:
    """Return counts over a collection of verdict dicts.

    The returned structure has a stable shape::

        {
            'total': <int>,
            'tp': <int>,
            'fp': <int>,
            'by_confidence': {'HIGH': <int>, 'MEDIUM': <int>, 'LOW': <int>},
        }

    Every verdict (both TP and FP) contributes to ``total`` and to the
    ``by_confidence`` tally. The input is not mutated.
    """
    total = 0
    tp = 0
    fp = 0
    by_confidence: Dict[str, int] = {level: 0 for level in _CONFIDENCE_LEVELS}
    for verdict in verdicts:
        total += 1
        if verdict.get('label') == _TP_LABEL:
            tp += 1
        else:
            fp += 1
        confidence = verdict.get('confidence')
        if confidence in by_confidence:
            by_confidence[confidence] += 1
    return {'total': total, 'tp': tp, 'fp': fp, 'by_confidence': by_confidence}

def keep_true_positives(verdicts: Iterable[Verdict]) -> List[Verdict]:
    """Return only the true-positive verdicts, preserving input order.

    A new list is returned holding references to the original verdict dicts;
    neither the input collection nor the verdict objects are mutated.
    """
    return [verdict for verdict in verdicts if verdict.get('label') == _TP_LABEL]