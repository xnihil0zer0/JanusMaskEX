"""Pure, deterministic, stdlib-only local multi-agent debate synthesizer.

This module distills the durable capability of the legacy ``debate_pool.py``
``run_debate_local``: a PURE, stdlib-only, LLM-free triage that simulates a
three-agent debate (security_analyst / fp_detector / exploit_validator) over a
finding's grounding evidence and folds the per-round arguments into a weighted
consensus verdict.

There is NO clock, NO network, NO randomness, NO file I/O and NO LLM call: the
same input always yields the same output. The module imports only the Python
standard library and no sibling Epic-4 leaf module.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
__all__ = ['run_debate_local', 'DebateFinding', 'DebateRound', 'DebateResult', 'VERDICTS', 'DEFAULT_ROUNDS', 'MAX_ROUNDS']
VERDICTS = ('SUBMIT', 'REJECT', 'NEEDS_INVESTIGATION')
DEFAULT_ROUNDS = 2
MAX_ROUNDS = 3
_SUBMIT_VERDICTS = frozenset({'EXPLOITABLE', 'SUBMIT', 'UNLIKELY_FP'})
_REJECT_VERDICTS = frozenset({'NOT_EXPLOITABLE', 'REJECT', 'LIKELY_FP'})
_STATUS_FIELD = 'status'
_TAINT_CONFIRMED = 'taint_confirmed'
_KNOWN_FP = 'known_fp'
_CORROBORATED = 'corroborated'

class DebateFinding:
    """A borderline vulnerability finding fed into the local debate.

    Constructible by keyword arguments with deterministic defaults. The
    grounding evidence is normalised to a list of dicts so that downstream
    rounds can iterate it safely without mutating the caller's input.
    """

    def __init__(self, graphmert_confidence: float=0.5, grounding_evidence: Optional[Any]=(), code_window: str='') -> None:
        self.graphmert_confidence: float = graphmert_confidence
        self.grounding_evidence: List[Dict[str, Any]] = _normalize_evidence(grounding_evidence)
        self.code_window: str = code_window

    def to_dict(self) -> Dict[str, Any]:
        return {'graphmert_confidence': self.graphmert_confidence, 'grounding_evidence': [dict(ev) for ev in self.grounding_evidence], 'code_window': self.code_window}

def _normalize_evidence(evidence: Optional[Any]) -> List[Dict[str, Any]]:
    """Return a fresh list of dict-like evidence entries.

    ``None`` and the empty default collapse to an empty list. Any iterable of
    mappings is copied into a new list so the caller's object is never mutated
    and never aliased.
    """
    if evidence is None:
        return []
    normalized: List[Dict[str, Any]] = []
    for entry in evidence:
        if isinstance(entry, dict):
            normalized.append(dict(entry))
        else:
            normalized.append({'value': entry})
    return normalized

class DebateRound:
    """A single debate round holding the ordered agent arguments."""

    def __init__(self, round_num: int) -> None:
        self.round_num: int = round_num
        self.arguments: List[Dict[str, Any]] = []

    def add_argument(self, role: str, verdict: str, confidence: float, argument: str, evidence: Any) -> None:
        self.arguments.append({'role': role, 'verdict': verdict, 'confidence': confidence, 'argument': argument, 'evidence': evidence})
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {'round': self.round_num, 'arguments': self.arguments}

class DebateResult:
    """The folded outcome of a full local debate."""

    def __init__(self, finding: DebateFinding, rounds: List[DebateRound], final_verdict: str, final_confidence: float, reasoning: str) -> None:
        self.finding: DebateFinding = finding
        self.rounds: List[DebateRound] = rounds
        self.final_verdict: str = final_verdict
        self.final_confidence: float = final_confidence
        self.reasoning: str = reasoning

    def to_dict(self) -> Dict[str, Any]:
        return {'final_verdict': self.final_verdict, 'final_confidence': self.final_confidence, 'reasoning': self.reasoning, 'debate_rounds': [rnd.to_dict() for rnd in self.rounds]}

def _has_status(evidence: List[Dict[str, Any]], label: str) -> bool:
    """True if any evidence entry carries ``status == label`` (exact match)."""
    for entry in evidence:
        if entry.get(_STATUS_FIELD) == label:
            return True
    return False

def _evidence_labels(evidence: List[Dict[str, Any]]) -> List[str]:
    """Compact ``layer:status`` strings for argument provenance."""
    labels: List[str] = []
    for entry in evidence:
        layer = entry.get('layer', '?')
        status = entry.get(_STATUS_FIELD, '?')
        labels.append('{0}:{1}'.format(layer, status))
    return labels

def run_debate_local(finding: DebateFinding, n_rounds: int=DEFAULT_ROUNDS) -> DebateResult:
    """Run ``n_rounds`` deterministic debate rounds and fold a verdict.

    The input ``finding`` is never mutated. Each round adds exactly three
    arguments in order: ``security_analyst``, ``fp_detector`` and
    ``exploit_validator``. Per-round confidences are summed into submit,
    reject and investigate weights, normalised by their total, and compared
    against a 0.5 majority threshold to choose the final verdict.
    """
    evidence = finding.grounding_evidence
    taint_confirmed = _has_status(evidence, _TAINT_CONFIRMED)
    known_fp = _has_status(evidence, _KNOWN_FP)
    corroborated = _has_status(evidence, _CORROBORATED)
    labels = _evidence_labels(evidence)
    rounds: List[DebateRound] = []
    for index in range(int(n_rounds)):
        rnd = DebateRound(index + 1)
        if taint_confirmed:
            sa_verdict, sa_conf = ('EXPLOITABLE', 0.85)
            sa_argument = 'Taint flow confirmed end-to-end; likely exploitable.'
        else:
            sa_verdict, sa_conf = ('UNCLEAR', 0.4)
            sa_argument = 'No confirmed taint flow; exploitability unclear.'
        rnd.add_argument('security_analyst', sa_verdict, sa_conf, sa_argument, labels)
        if known_fp:
            fp_verdict, fp_conf = ('LIKELY_FP', 0.9)
            fp_argument = 'Matches a known false-positive pattern.'
        elif corroborated:
            fp_verdict, fp_conf = ('UNLIKELY_FP', 0.7)
            fp_argument = 'Independently corroborated; unlikely a false positive.'
        else:
            fp_verdict, fp_conf = ('UNCLEAR', 0.3)
            fp_argument = 'No false-positive signal either way.'
        rnd.add_argument('fp_detector', fp_verdict, fp_conf, fp_argument, labels)
        if taint_confirmed and finding.graphmert_confidence > 0.5:
            ev_verdict, ev_conf = ('SUBMIT', 0.8)
            ev_argument = 'Confirmed taint with high model confidence; submit.'
        elif known_fp:
            ev_verdict, ev_conf = ('REJECT', 0.5)
            ev_argument = 'Known false positive; reject.'
        else:
            ev_verdict, ev_conf = ('INVESTIGATE', 0.5)
            ev_argument = 'Insufficient signal to validate; investigate further.'
        rnd.add_argument('exploit_validator', ev_verdict, ev_conf, ev_argument, labels)
        rounds.append(rnd)
    submit_weight = 0.0
    reject_weight = 0.0
    investigate_weight = 0.0
    for rnd in rounds:
        for arg in rnd.arguments:
            verdict = arg['verdict']
            confidence = arg['confidence']
            if verdict in _SUBMIT_VERDICTS:
                submit_weight += confidence
            elif verdict in _REJECT_VERDICTS:
                reject_weight += confidence
            else:
                investigate_weight += confidence
    total_weight = submit_weight + reject_weight + investigate_weight
    if total_weight == 0:
        total_weight = 1.0
    submit_score = submit_weight / total_weight
    reject_score = reject_weight / total_weight
    investigate_score = investigate_weight / total_weight
    if submit_score > 0.5:
        final_verdict = 'SUBMIT'
        final_confidence = submit_score
    elif reject_score > 0.5:
        final_verdict = 'REJECT'
        final_confidence = reject_score
    else:
        final_verdict = 'NEEDS_INVESTIGATION'
        final_confidence = investigate_score
    reasoning = 'Folded {0} round(s): submit={1:.3f}, reject={2:.3f}, investigate={3:.3f} -> {4} (confidence {5:.3f}).'.format(len(rounds), submit_score, reject_score, investigate_score, final_verdict, final_confidence)
    return DebateResult(finding=finding, rounds=rounds, final_verdict=final_verdict, final_confidence=final_confidence, reasoning=reasoning)