"""ngv2/spawn_preflight.py — Phase-8.2 5-gate spawn preflight.

Concept-ports legacy ``services/spawn_preflight.py`` (the guard that killed
the rate-limit cascade self-DoS) while DISCARDING all host probing: every
external fact is an injected keyword argument, so ``run_preflight`` is pure,
total, deterministic, and stdlib-only.

The five gates run IN ORDER and short-circuit on the first BLOCK:

    cascade -> memory -> capacity -> dedup -> cooldown
"""
from __future__ import annotations
from typing import Any, Dict, List, Mapping, Optional, Sequence
MAX_CONCURRENT_WORKERS: int = 8
CASCADE_FAILURE_THRESHOLD: float = 0.5
CASCADE_MIN_SAMPLE: int = 4
MEMORY_MIN_AVAILABLE_MB: int = 2048
DEDUP_COMPLETED_WINDOW_S: int = 300
COOLDOWN_BASE_S: int = 15
COOLDOWN_MAX_S: int = 180
_GATE_ORDER: List[str] = ['cascade', 'memory', 'capacity', 'dedup', 'cooldown']

def _cooldown_seconds(consecutive_failures: int) -> int:
    """Exponential backoff window: min(15 * 2**(n-1), 180); 0 when n <= 0."""
    if consecutive_failures <= 0:
        return 0
    return min(COOLDOWN_BASE_S * 2 ** (consecutive_failures - 1), COOLDOWN_MAX_S)

def _go() -> Dict[str, Any]:
    """All gates passed -> GO with the full ordered gate list."""
    return {'verdict': 'GO', 'blocked_by': '', 'reason': '', 'gates': list(_GATE_ORDER)}

def _block(gate: str, reason: str, passed: List[str]) -> Dict[str, Any]:
    """First failing gate -> BLOCKED, naming the gate and the passed prefix."""
    return {'verdict': 'BLOCKED', 'blocked_by': gate, 'reason': reason, 'gates': list(passed)}

def run_preflight(*, worker_type: str, task_target: Optional[str]=None, recent_completions: Optional[Sequence[Mapping[str, Any]]]=None, available_memory_mb: Optional[float]=None, active_workers: int=0, max_workers: int=MAX_CONCURRENT_WORKERS, running_targets: Optional[Sequence[str]]=None, recent_target_completions: Optional[Mapping[str, float]]=None, now: float=0.0, dedup_window_s: int=DEDUP_COMPLETED_WINDOW_S, consecutive_failures: int=0, last_failure_at: Optional[float]=None, force: bool=False) -> Dict[str, Any]:
    """Run the five spawn-preflight gates in order, short-circuiting on BLOCK.

    Returns a dict ``{'verdict', 'blocked_by', 'reason', 'gates'}``. On GO,
    ``gates`` is the full ordered list; on BLOCK, ``gates`` is the prefix of
    gate names that passed before the blocking gate.
    """
    if force:
        result = _go()
        result['reason'] = 'forced'
        return result
    passed: List[str] = []
    if recent_completions is not None and len(recent_completions) >= CASCADE_MIN_SAMPLE:
        failures = sum((1 for c in recent_completions if not c.get('success', True)))
        failed_fraction = failures / len(recent_completions)
        if failed_fraction > CASCADE_FAILURE_THRESHOLD:
            return _block('cascade', 'failure cascade: {:.0%} of recent completions failed'.format(failed_fraction), passed)
    passed.append('cascade')
    if available_memory_mb is not None and available_memory_mb < MEMORY_MIN_AVAILABLE_MB:
        return _block('memory', 'insufficient memory: {} MB < {} MB'.format(available_memory_mb, MEMORY_MIN_AVAILABLE_MB), passed)
    passed.append('memory')
    if active_workers >= max_workers:
        return _block('capacity', 'at capacity: {} active >= {} max'.format(active_workers, max_workers), passed)
    passed.append('capacity')
    if task_target is not None:
        running = running_targets or ()
        if task_target in running:
            return _block('dedup', 'target already running: {}'.format(task_target), passed)
        completions = recent_target_completions or {}
        if task_target in completions:
            elapsed = now - completions[task_target]
            if elapsed < dedup_window_s:
                return _block('dedup', 'target completed {}s ago < {}s window'.format(elapsed, dedup_window_s), passed)
    passed.append('dedup')
    if last_failure_at is not None:
        window = _cooldown_seconds(consecutive_failures)
        if window > 0:
            elapsed = now - last_failure_at
            if elapsed < window:
                return _block('cooldown', 'in cooldown: {}s elapsed < {}s window'.format(elapsed, window), passed)
    passed.append('cooldown')
    return _go()