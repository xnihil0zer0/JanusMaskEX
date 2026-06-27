"""Pure staleness + polite rate-limit/backoff refresh policy.

Side-effect-free helpers over ISO-8601 ``fetched_at`` timestamps so the
entrypoint can decide whether to refetch and how long to wait between
requests.

Both functions are deterministic and importable without side effects:

* ``is_stale`` reads no clock -- ``now`` is injected as an explicit
  parameter.
* ``next_delay`` is plain arithmetic on its inputs.
"""
from __future__ import annotations
from datetime import datetime

def _parse_iso(value: str) -> datetime | None:
    """Parse an ISO-8601 timestamp, returning ``None`` if malformed/empty."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None

def is_stale(fetched_at: str, now: str, max_age_hours: float) -> bool:
    """Return True when ``now - fetched_at`` exceeds ``max_age_hours``.

    Equal or younger ages are considered fresh (False). A malformed or
    empty ``fetched_at`` is treated as stale (True) as a safe default so a
    snapshot we cannot date is refetched.
    """
    fetched = _parse_iso(fetched_at)
    current = _parse_iso(now)
    if fetched is None or current is None:
        return True
    elapsed_hours = (current - fetched).total_seconds() / 3600.0
    return elapsed_hours > max_age_hours

def next_delay(attempt: int, base_seconds: float) -> float:
    """Return a polite escalating backoff delay in seconds.

    The first attempt (``attempt == 0``) returns the base politeness delay
    (``~1 req/sec`` when ``base_seconds == 1.0``). Later attempts grow
    exponentially so the policy is rate-limit friendly. The result is never
    smaller than ``base_seconds`` and is non-decreasing in ``attempt``.
    """
    safe_attempt = attempt if attempt > 0 else 0
    safe_base = base_seconds if base_seconds > 0 else 0.0
    return float(safe_base) * 2.0 ** safe_attempt