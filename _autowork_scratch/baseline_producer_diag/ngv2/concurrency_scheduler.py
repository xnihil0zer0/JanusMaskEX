"""ngv2/concurrency_scheduler.py — Phase-8.2 concurrency-ceiling admission controller.

A pure, deterministic admission controller that fans qualified targets concurrently
while enforcing a HARD SPAWN CEILING (anti-spawn-storm), per-type CAPS, and a
clock-injected TokenBucket rate gate.

Stdlib-only. No real clock / network / randomness / threading / filesystem in any
path. The live worker census (total_active, type_active) and the current time
(now) are INJECTED — never probed.
"""
from __future__ import annotations
from typing import Dict, Optional
PHASE_CAPS: Dict[str, int] = {'hunt': 6, 'poc': 4, 'verify': 4, 'submit': 2}
HARD_SPAWN_CEILING: int = 8

class ConcurrencyScheduler:
    """Deterministic, pure admission controller.

    The HARD SPAWN CEILING is the first branch in :meth:`admit` so that
    ``force=True`` can never exceed it.
    """

    def __init__(self, *, phase_caps: Optional[Dict[str, int]]=None, hard_ceiling: int=8) -> None:
        self.phase_caps: Dict[str, int] = dict(PHASE_CAPS) if phase_caps is None else dict(phase_caps)
        self.hard_ceiling: int = int(hard_ceiling)

    def cap_for(self, worker_type: str) -> int:
        """Per-type cap, clamped so it never exceeds the hard ceiling."""
        return min(self.phase_caps.get(worker_type, self.hard_ceiling), self.hard_ceiling)

    def admit(self, *, worker_type: str, total_active: int, type_active: int, tokens_available: float=1.0, force: bool=False) -> Dict[str, object]:
        """Return an admission decision dict.

        Order of bounds:
          1. HARD SPAWN CEILING — structurally un-bypassable; ``force`` cannot exceed it.
          2. ``force=True`` short-circuits to admit.
          3. per-type cap (``blocked_by`` = ``"type_cap"``).
          4. token-bucket rate gate (``blocked_by`` = ``"rate_limit"``).
          5. admit.
        """
        if total_active >= self.hard_ceiling:
            return {'admit': False, 'blocked_by': 'hard_ceiling', 'reason': 'hard spawn ceiling reached'}
        if force:
            return {'admit': True, 'blocked_by': None, 'reason': 'forced'}
        if type_active >= self.cap_for(worker_type):
            return {'admit': False, 'blocked_by': 'type_cap', 'reason': 'per-type cap reached'}
        if tokens_available < 1.0:
            return {'admit': False, 'blocked_by': 'rate_limit', 'reason': 'insufficient tokens'}
        return {'admit': True, 'blocked_by': None, 'reason': 'ok'}

class TokenBucket:
    """Clock-injected token bucket with lazy monotonic refill."""

    def __init__(self, *, capacity: float, refill_per_s: float, tokens: Optional[float]=None, last: float=0.0) -> None:
        self.capacity: float = float(capacity)
        self.refill_per_s: float = float(refill_per_s)
        self.tokens: float = self.capacity if tokens is None else float(tokens)
        self.last: float = float(last)

    def _refill(self, now: float) -> None:
        """Lazily refill based on injected monotonic ``now``; no-op if now <= last."""
        if now > self.last:
            elapsed = now - self.last
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_s)
            self.last = now

    def available(self, now: float) -> float:
        """Tokens available after refilling to ``now``."""
        self._refill(now)
        return self.tokens

    def consume(self, now: float, amount: float=1.0) -> bool:
        """Refill to ``now`` then deduct ``amount`` if available; return success."""
        self._refill(now)
        if self.tokens >= amount:
            self.tokens -= amount
            return True
        return False