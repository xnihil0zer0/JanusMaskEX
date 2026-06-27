"""Pure, deterministic, stdlib-only debate triage router.

Distilled from the legacy ``services/debate_triage/debate_pool.py`` routing
logic. Only the PURE, deterministic capability lives here: confidence-threshold
routing of a GraphMERT-scored finding into one of exactly three outcomes --
``'auto_submit'`` / ``'auto_reject'`` / ``'debate'`` -- plus the
``DebateFinding`` view-dataclass that normalizes a raw finding dict.

The LLM / MASFactory multi-agent debate machinery is intentionally NOT part of
this module (non-deterministic, external). There is no clock, network,
subprocess, disk I/O, or randomness, and nothing here is imported from a sibling
Epic-4 leaf. Standard library only.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
__all__ = ['route_finding', 'DebateFinding', 'AUTO_SUBMIT_THRESHOLD', 'AUTO_REJECT_THRESHOLD']
def calculate_shannon_entropy(probs: 'Sequence[float]') -> float:
    """Shannon entropy (in BITS, log base 2) of a discrete distribution.

    Zero-probability terms contribute nothing under the ``0 * log(0) = 0``
    convention, so a degenerate / single-element distribution has entropy 0.
    """
    import math
    total = 0.0
    for p in probs:
        if p > 0.0:
            total -= p * math.log2(p)
    if total < 0.0:
        total = 0.0
    return total

def calculate_kl_divergence(p: 'Sequence[float]', q: 'Sequence[float]') -> float:
    """KL divergence D(p || q) in bits.

    Returns 0 when ``p == q`` and is strictly positive otherwise (Gibbs'
    inequality). Zero-probability entries in ``p`` contribute nothing; a zero
    in ``q`` where ``p`` is nonzero is handled with a small epsilon floor so
    the result stays finite and deterministic.
    """
    import math
    epsilon = 1e-12
    total = 0.0
    for pi, qi in zip(p, q):
        if pi > 0.0:
            qi_safe = qi if qi > 0.0 else epsilon
            total += pi * math.log2(pi / qi_safe)
    if total < 0.0:
        total = 0.0
    return total

def early_stop(history: 'Sequence[Sequence[float]]', h_thresh: float=0.1, kl_thresh: float=0.05) -> bool:
    """Decide whether a debate has converged enough to stop early.

    Returns ``True`` when the latest belief distribution is low-entropy
    (below ``h_thresh``) AND stable round-over-round (KL between the last two
    distributions below ``kl_thresh``). A history with fewer than two rounds
    has no KL pair yet and therefore returns ``False``. The decision is
    monotone over a converging history: as entropy and round-to-round KL keep
    shrinking, once the thresholds are met they remain met.
    """
    if history is None or len(history) < 2:
        return False
    latest = history[-1]
    previous = history[-2]
    if calculate_shannon_entropy(latest) >= h_thresh:
        return False
    if calculate_kl_divergence(latest, previous) >= kl_thresh:
        return False
    return True
AUTO_SUBMIT_THRESHOLD = 0.9
AUTO_REJECT_THRESHOLD: float = 0.1
ROUTE_AUTO_SUBMIT: str = 'auto_submit'
ROUTE_AUTO_REJECT: str = 'auto_reject'
ROUTE_DEBATE: str = 'debate'

@dataclass
class DebateFinding:
    """Normalized read-only view over a raw finding dict.

    Constructed from a single mapping; missing keys fall back to deterministic
    defaults. The original mapping is retained verbatim as ``finding``.
    """
    finding: Dict[str, Any]
    graphmert_confidence: float = field(init=False, default=0.5)
    code_window: str = field(init=False, default='')
    file: str = field(init=False, default='')
    line: int = field(init=False, default=0)
    cwe: str = field(init=False, default='')
    description: str = field(init=False, default='')
    grounding_evidence: List[Any] = field(init=False, default_factory=list)
    confidence: str = field(init=False, default='MEDIUM')

    def __post_init__(self) -> None:
        raw = self.finding if isinstance(self.finding, dict) else {}
        self.graphmert_confidence = raw.get('graphmert_confidence', 0.5)
        self.code_window = raw.get('code_window', '')
        self.file = raw.get('file', '')
        self.line = raw.get('line', 0)
        self.cwe = raw.get('cwe', '')
        self.description = raw.get('description', '')
        self.grounding_evidence = raw.get('grounding_evidence', [])
        self.confidence = raw.get('confidence', 'MEDIUM')

def _coerce_score(value: Any) -> Optional[float]:
    """Return ``value`` as a float score, or ``None`` if it is not a usable
    real-number confidence. ``bool`` is rejected (it is an ``int`` subtype but
    never a meaningful confidence here)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None

def _extract_confidence(finding: Dict[str, Any]) -> Optional[float]:
    """Recover a numeric confidence from a raw finding mapping.

    Primary source is the top-level ``graphmert_confidence`` field. When that is
    absent/None, fall back to the highest-priority GraphMERT layer inside
    ``grounding_evidence`` and use its ``tp_probability``. Returns ``None`` when
    no usable confidence is available.
    """
    direct = _coerce_score(finding.get('graphmert_confidence'))
    if direct is not None:
        return direct
    evidence = finding.get('grounding_evidence')
    if isinstance(evidence, list):
        for entry in evidence:
            if not isinstance(entry, dict):
                continue
            layer = entry.get('layer', '')
            if isinstance(layer, str) and 'graphmert' in layer.lower():
                probability = _coerce_score(entry.get('tp_probability'))
                if probability is not None:
                    return probability
    return None

def route_finding(finding: Union[DebateFinding, Dict[str, Any]]) -> str:
    """Deterministically route a finding to exactly one outcome.

    Returns ``'auto_submit'`` when the recovered confidence is strictly above
    ``AUTO_SUBMIT_THRESHOLD``, ``'auto_reject'`` when strictly below
    ``AUTO_REJECT_THRESHOLD``, and ``'debate'`` for everything in between
    (boundaries inclusive of the debate band) or when no usable confidence can
    be recovered. The input mapping is never mutated.
    """
    if isinstance(finding, DebateFinding):
        finding = finding.finding
    if not isinstance(finding, dict):
        return ROUTE_DEBATE
    confidence = _extract_confidence(finding)
    if confidence is None:
        return ROUTE_DEBATE
    if confidence > AUTO_SUBMIT_THRESHOLD:
        return ROUTE_AUTO_SUBMIT
    if confidence < AUTO_REJECT_THRESHOLD:
        return ROUTE_AUTO_REJECT
    return ROUTE_DEBATE