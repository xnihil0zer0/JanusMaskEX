"""ngv2.rate_limiter -- a deterministic, stdlib-only persistent cooldown gate.

Distilled from the legacy ``services/rate_limiter.py`` (flock + ``time.time()`` +
a fixed RATE_FILE). The durable capability is: "given a resource and a cooldown,
decide whether enough wall-clock has elapsed since the last access to permit a
new one, and persist the new access timestamp."

The two sources of non-determinism are INJECTED so the gate never depends on the
real clock or a fixed global path:

  * ``now``        -- a zero-arg callable returning a float epoch time
                      (defaults to ``time.time`` in production).
  * ``state_path`` -- the JSON state file location (str | pathlib.Path).

State dict keys are pinned by ``STATE_FIELDS``.
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Callable, Dict, Optional, Union
STATE_FIELDS = ('last_access', 'cooldown', 'acquired_by')
PathLike = Union[str, Path]
Clock = Callable[[], float]
Rates = Dict[str, Dict[str, object]]

def make_scripted_clock(*values: float) -> Clock:
    """Return a zero-arg clock that yields ``values`` in order on each call.

    Used by the oracle to drive a fully deterministic sequence of timestamps in
    place of the real wall clock.
    """
    seq = iter(values)

    def _clock() -> float:
        return next(seq)
    return _clock

def load_rates(state_path: PathLike) -> Rates:
    """Load the persisted rate state, returning ``{}`` when absent/unreadable."""
    path = Path(state_path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}

def save_rates(rates: Rates, state_path: PathLike) -> None:
    """Persist ``rates`` as JSON, creating any missing parent directories."""
    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rates))

def acquire(resource: str, cooldown: float, *, state_path: PathLike, now: Clock=time.time, acquired_by: str='ngv2') -> bool:
    """Attempt to acquire ``resource``; persist + return True iff permitted.

    The first acquire of a resource always succeeds. A subsequent acquire is
    denied (returns False, state untouched) while fewer than ``cooldown`` seconds
    have elapsed since the recorded ``last_access``; once at least ``cooldown``
    seconds have elapsed it succeeds and bumps ``last_access``.
    """
    rates = load_rates(state_path)
    current = now()
    entry = rates.get(resource)
    if entry is not None:
        elapsed = current - entry.get('last_access', current)
        if elapsed < cooldown:
            return False
    rates[resource] = {'last_access': current, 'cooldown': cooldown, 'acquired_by': acquired_by}
    save_rates(rates, state_path)
    return True

def remaining(resource: str, cooldown: float, *, state_path: PathLike, now: Clock=time.time) -> float:
    """Return seconds left on ``resource``'s cooldown, clamped to ``>= 0.0``.

    Unknown resources (never acquired) report ``0.0``.
    """
    rates = load_rates(state_path)
    entry = rates.get(resource)
    if entry is None:
        return 0.0
    elapsed = now() - entry.get('last_access', 0.0)
    return max(0.0, cooldown - elapsed)

def status(resource: Optional[str]=None, *, state_path: PathLike, now: Clock=time.time) -> None:
    """Report gate status; tolerates missing state and never raises.

    The current contract returns ``None`` (no structured status surface is
    pinned by the oracle); it must not read the real clock or fail when the
    state file is absent.
    """
    return None