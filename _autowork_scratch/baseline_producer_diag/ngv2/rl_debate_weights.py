"""Stateful, in-memory UCB1 debate-agent weight controller.

This module distills the durable capability of the legacy ``rl_controller``:
learn which debate agents are most reliable from triage outcomes using a UCB1
bandit, and emit per-agent (and per-CWE) weights.

It is deliberately *pure*: standard library only, holding state exclusively in
memory with NO file I/O, NO clock/``datetime`` access, and NO randomness, so the
same inputs always produce the same outputs.
"""
from __future__ import annotations
import math
from typing import Any, Dict, List
DEFAULT_ROLES: List[str] = ['security_analyst', 'fp_detector', 'exploit_validator']
UCB_C: float = 1.41
_TP_STANCE = frozenset({'EXPLOITABLE', 'UNLIKELY_FP', 'SUBMIT'})
_FP_STANCE = frozenset({'NOT_EXPLOITABLE', 'LIKELY_FP', 'REJECT'})

def _verdict_is_correct(verdict: str, actual_outcome: str) -> bool:
    """Return True when an agent verdict matches the ground-truth outcome."""
    if actual_outcome == 'TP':
        return verdict in _TP_STANCE
    if actual_outcome == 'FP':
        return verdict in _FP_STANCE
    return False

def _debate_is_correct(final_verdict: str, actual_outcome: str) -> bool:
    """Return True when the debate's final verdict matches the outcome.

    ``SUBMIT`` is correct for a true positive; ``REJECT`` for a false positive.
    """
    if final_verdict == 'SUBMIT' and actual_outcome == 'TP':
        return True
    if final_verdict == 'REJECT' and actual_outcome == 'FP':
        return True
    return False

class RLState:
    """In-memory accumulator of debate outcomes and UCB1 weight emitter."""

    def __init__(self) -> None:
        self.records: List[Dict[str, Any]] = []
        self.agent_stats: Dict[str, Dict[str, int]] = {role: {'correct': 0, 'total': 0} for role in DEFAULT_ROLES}
        self.cwe_stats: Dict[str, Dict[str, Dict[str, int]]] = {}
        self.round_stats: Dict[int, Dict[str, int]] = {}

    def record_outcome(self, debate_result: Dict[str, Any], actual_outcome: str) -> None:
        """Ingest one debate and update all statistics in place."""
        self.records.append(debate_result)
        cwe = debate_result.get('finding_cwe', '') or 'unknown'
        final_verdict = debate_result.get('final_verdict', '')
        debate_rounds = debate_result.get('debate_rounds', []) or []
        n_rounds = len(debate_rounds)
        rstat = self.round_stats.setdefault(n_rounds, {'correct': 0, 'total': 0})
        rstat['total'] += 1
        if _debate_is_correct(final_verdict, actual_outcome):
            rstat['correct'] += 1
        flat_arguments: List[Dict[str, Any]] = [arg for rnd in debate_rounds for arg in rnd.get('arguments', [])]
        for arg in flat_arguments[:len(DEFAULT_ROLES)]:
            role = arg.get('role')
            verdict = arg.get('verdict', '')
            correct = _verdict_is_correct(verdict, actual_outcome)
            astat = self.agent_stats.setdefault(role, {'correct': 0, 'total': 0})
            astat['total'] += 1
            if correct:
                astat['correct'] += 1
            bucket = self.cwe_stats.setdefault(cwe, {})
            cstat = bucket.setdefault(role, {'correct': 0, 'total': 0})
            cstat['total'] += 1
            if correct:
                cstat['correct'] += 1

    def get_weights(self, cwe: str='') -> Dict[str, float]:
        """Return per-role weights normalized to sum to ``len(DEFAULT_ROLES)``."""
        total_obs = sum((stat['total'] for stat in self.agent_stats.values()))
        if total_obs < 10:
            return {role: 1.0 for role in DEFAULT_ROLES}
        raw: Dict[str, float] = {}
        for role in DEFAULT_ROLES:
            source = None
            if cwe and cwe in self.cwe_stats and (role in self.cwe_stats[cwe]):
                source = self.cwe_stats[cwe][role]
            else:
                source = self.agent_stats.get(role, {'correct': 0, 'total': 0})
            role_total = source['total']
            if role_total == 0:
                raw[role] = 1.0
                continue
            accuracy = source['correct'] / role_total
            raw[role] = accuracy + UCB_C * math.sqrt(math.log(total_obs) / role_total)
        total_weight = sum(raw.values())
        if total_weight == 0:
            return {role: 1.0 for role in DEFAULT_ROLES}
        scale = len(DEFAULT_ROLES) / total_weight
        return {role: value * scale for role, value in raw.items()}

    def get_stats(self) -> Dict[str, Any]:
        """Return a summary statistics dictionary."""
        agent_accuracy: Dict[str, Dict[str, Any]] = {}
        for role, stat in self.agent_stats.items():
            total = stat['total']
            accuracy = stat['correct'] / total if total else 0.0
            agent_accuracy[role] = {'accuracy': accuracy, 'correct': stat['correct'], 'total': total}
        round_accuracy: Dict[str, Dict[str, Any]] = {}
        for n_rounds, stat in self.round_stats.items():
            total = stat['total']
            accuracy = stat['correct'] / total if total else 0.0
            round_accuracy[str(n_rounds)] = {'accuracy': accuracy, 'correct': stat['correct'], 'total': total}
        return {'total_records': len(self.records), 'agent_accuracy': agent_accuracy, 'round_accuracy': round_accuracy, 'cwe_coverage': sorted(self.cwe_stats.keys()), 'weights': self.get_weights()}