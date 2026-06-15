---
interfaces: "NEW orchestration module ngv2/concurrency_scheduler.py exposing class ConcurrencyScheduler(*, phase_caps=None, hard_ceiling=8) with .cap_for(worker_type) -> int and .admit(*, worker_type, total_active, type_active, tokens_available=1.0, force=False) -> dict (enforces the HARD SPAWN CEILING first — force CANNOT bypass it — then the per-type cap then a token-bucket rate gate); class TokenBucket(*, capacity, refill_per_s, tokens=None, last=0.0) with .available(now) and .consume(now, amount=1.0); module constants PHASE_CAPS={'hunt':6,'poc':4,'verify':4,'submit':2} and HARD_SPAWN_CEILING=8"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
meta_task_type: io_adapter
---

# Title

ngv2/concurrency_scheduler.py — NEW Phase-8.2 concurrency-ceiling admission controller (per-type caps + HARD SPAWN CEILING + deterministic token bucket)

# Scope

Build a NEW orchestration module ngv2/concurrency_scheduler.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). This is the Phase-8.2 concurrency-ceiling scheduler that fans qualified targets concurrently while enforcing hard bounds. It ports the legacy per-phase CAPS (hunt<=6, poc/verify<=4, submit<=2 — huntr rate-limit aware) and adds the MANDATORY SAFETY guard: a HARD SPAWN CEILING (default 8) on the TOTAL live worker census of ANY type that kills the legacy spawn-storm self-DoS. The ConcurrencyScheduler.admit method is pure (the live census and token-bucket state are injected) and checks bounds in this order: (1) the HARD SPAWN CEILING — checked FIRST and STRUCTURALLY un-bypassable, force=True CANNOT exceed it; (2) per-type cap (clamped to never exceed the hard ceiling); (3) a token-bucket rate gate (tokens_available < 1.0 -> BLOCK). The TokenBucket is a deterministic, clock-injected rate limiter (time passed as ``now`` to .available/.consume; no real clock). Emit the whole file VERBATIM from Deliverables. Name the committed oracle tests/test_concurrency_scheduler_wired.py in the verification_command. Required plan shape: EXACTLY ONE impl task building this one new single file.

# Non-Goals

This is a NEW single-file module, not an edit; integration is out of scope — do NOT author or modify any test (the oracle tests/test_concurrency_scheduler_wired.py is committed and authoritative) and do NOT add integration/e2e tests. Do NOT touch, import, or alter ngv2/worker_registry.py, ngv2/dynamic_scheduler.py, ngv2/spawn_preflight.py, or any other module — this module is self-contained and the loop wires it externally. Do NOT call the network, a real clock (time.time/datetime.now), randomness, threading, multiprocessing, sqlite, psutil, the filesystem, or subprocess in any path — the worker census and current time are injected. No LLM, no third-party imports (stdlib only). Touch exactly the one new file ngv2/concurrency_scheduler.py.

# Inputs

ConcurrencyScheduler(*, phase_caps=None, hard_ceiling=8): phase_caps defaults to PHASE_CAPS; hard_ceiling is the absolute total-worker bound. .cap_for(worker_type) returns min(phase_caps.get(worker_type, hard_ceiling), hard_ceiling) so no per-type cap can exceed the ceiling. .admit(*, worker_type, total_active, type_active, tokens_available=1.0, force=False) returns {'admit': bool, 'blocked_by': str, 'reason': str}: if total_active >= hard_ceiling -> admit False, blocked_by 'hard_ceiling' (even when force=True); elif force=True -> admit True, reason 'forced'; elif type_active >= cap_for(worker_type) -> blocked_by 'type_cap'; elif tokens_available < 1.0 -> blocked_by 'rate_limit'; else admit True. TokenBucket(*, capacity, refill_per_s, tokens=None, last=0.0): refills lazily on a monotonic injected ``now`` (tokens += (now-last)*refill_per_s, capped at capacity, last advanced); .available(now) returns current tokens after refill; .consume(now, amount=1.0) refills then deducts amount if available (returns bool).

# Deliverables

ngv2/concurrency_scheduler.py with EXACTLY this content:

```python
"""ngv2.concurrency_scheduler — Phase-8.2 concurrency-ceiling admission control.

Fans qualified targets concurrently while enforcing hard bounds. Ports the
legacy per-phase CAPS (hunt<=6, poc/verify<=4, submit<=2 — huntr rate-limit
aware) and adds the MANDATORY SAFETY guard: a HARD SPAWN CEILING on the total
live worker census that kills the legacy spawn-storm self-DoS. Pure &
deterministic: the live census and the token-bucket clock are INJECTED, never
probed. DISCARDS legacy's bash spawn_worker.sh coupling and cron self-chaining.
"""
from __future__ import annotations
from typing import Any, Dict, Mapping, Optional

# Per-worker-type concurrency caps (huntr rate-limit aware).
PHASE_CAPS: Dict[str, int] = {'hunt': 6, 'poc': 4, 'verify': 4, 'submit': 2}

# HARD SPAWN CEILING — the absolute upper bound on concurrently live workers of
# ANY type. This is the SAFETY guard that kills the legacy spawn-storm self-DoS.
HARD_SPAWN_CEILING: int = 8


class ConcurrencyScheduler:
    """Pure, deterministic admission controller for the hunt scheduler.

    No clock/network/subprocess: the live worker census and the token-bucket
    state are injected. ``admit`` answers GO/BLOCKED for a single candidate
    spawn, enforcing (a) the HARD SPAWN CEILING, (b) the per-type cap, and
    (c) a token-bucket rate limit. The hard ceiling is checked FIRST and can
    never be exceeded — not even by force.
    """

    def __init__(self, *, phase_caps: Optional[Mapping[str, int]] = None,
                 hard_ceiling: int = HARD_SPAWN_CEILING) -> None:
        self.phase_caps = dict(phase_caps) if phase_caps is not None else dict(PHASE_CAPS)
        self.hard_ceiling = int(hard_ceiling)

    def cap_for(self, worker_type: str) -> int:
        """The effective per-type cap, clamped to never exceed the hard ceiling."""
        return min(self.phase_caps.get(worker_type, self.hard_ceiling), self.hard_ceiling)

    def admit(self, *, worker_type: str, total_active: int,
              type_active: int, tokens_available: float = 1.0,
              force: bool = False) -> Dict[str, Any]:
        """Decide whether one more ``worker_type`` worker may spawn now.

        Returns ``{'admit': bool, 'blocked_by': str, 'reason': str}``. The HARD
        SPAWN CEILING is enforced FIRST and is structurally un-bypassable — even
        ``force=True`` cannot exceed it (anti-spawn-storm).
        """
        # HARD CEILING — structural, force CANNOT bypass it (anti-spawn-storm).
        if total_active >= self.hard_ceiling:
            return {'admit': False, 'blocked_by': 'hard_ceiling',
                    'reason': 'total active %d at hard spawn ceiling %d'
                              % (total_active, self.hard_ceiling)}
        if force:
            return {'admit': True, 'blocked_by': '', 'reason': 'forced'}
        cap = self.cap_for(worker_type)
        if type_active >= cap:
            return {'admit': False, 'blocked_by': 'type_cap',
                    'reason': '%s active %d at cap %d' % (worker_type, type_active, cap)}
        if tokens_available < 1.0:
            return {'admit': False, 'blocked_by': 'rate_limit',
                    'reason': 'token bucket empty (%.2f < 1.0)' % tokens_available}
        return {'admit': True, 'blocked_by': '', 'reason': ''}


class TokenBucket:
    """Deterministic token-bucket rate limiter; time is injected via ``now``."""

    def __init__(self, *, capacity: float, refill_per_s: float,
                 tokens: Optional[float] = None, last: float = 0.0) -> None:
        self.capacity = float(capacity)
        self.refill_per_s = float(refill_per_s)
        self.tokens = float(capacity if tokens is None else tokens)
        self.last = float(last)

    def _refill(self, now: float) -> None:
        if now > self.last:
            self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.refill_per_s)
            self.last = now

    def available(self, now: float) -> float:
        """Tokens currently available at injected ``now`` (after lazy refill)."""
        self._refill(now)
        return self.tokens

    def consume(self, now: float, amount: float = 1.0) -> bool:
        """Refill to ``now`` then deduct ``amount`` if available; returns success."""
        self._refill(now)
        if self.tokens >= amount:
            self.tokens -= amount
            return True
        return False
```

DISPATCH DIRECTIVE — this is a NEW single-file module. Emit it as a single whole-file deliverable for ngv2/concurrency_scheduler.py reproducing the Deliverables content BYTE-FOR-BYTE (it already imports everything it needs from the stdlib; no ngv2 sibling imports). Do NOT emit a `__JANUSMASK_PATCHES__` list — this is a new file, not a symbol patch. meta_task_type=io_adapter (external NGv2 target; the diff-fuzzer cannot resolve external imports, so use the fuzzer-bypassed, smoke-gated io_adapter meta-type). Use this task_id VERBATIM: `ngv2-concurrency-scheduler`. priority: high. dependencies: []. files_touched: `["ngv2/concurrency_scheduler.py"]` ONLY. verification_command (CWD-relative, NO `cd`): `.venv/bin/python -m pytest tests/test_concurrency_scheduler_wired.py -q`. The committed oracle tests/test_concurrency_scheduler_wired.py is the authoritative acceptance contract; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from this brief's committed oracle (plan descriptors referencing the committed oracle — this does NOT authorize authoring tests), e.g. `test_hard_ceiling_blocks` and `test_hard_ceiling_cannot_be_forced` (also good: `test_type_cap_blocks`, `test_token_bucket_refill_and_consume`).
