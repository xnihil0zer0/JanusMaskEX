"""Deterministic model-fallback engine for ngv2.

The legacy service cascades across model rate-limit boundaries
(sonnet -> opus -> codex -> gemini), tracking per-model recovery times so it can
switch back when a preferred model recovers. The durable capability is a PURE
state machine over an injected CLOCK seam: given the current time and recorded
limits, decide the active model and the next fallback.

This module is stdlib-only and deterministic -- it never reads disk, the
network, the wall clock, or any randomness. All time comes from an injected
zero-arg ``clock`` callable returning a float ``now``.
"""
from __future__ import annotations
import re
from typing import Callable, Dict, List, Optional, Tuple
CASCADE_ORDER: List[str] = ['sonnet', 'opus', 'codex', 'gemini']
MODEL_BACKENDS: Dict[str, Tuple[str, Optional[str]]] = {'sonnet': ('claude', 'sonnet'), 'opus': ('claude', 'opus'), 'codex': ('codex', None), 'gemini': ('gemini', None)}
DEFAULT_RECOVERY_SECONDS: float = 300.0
RATE_LIMIT_PATTERNS: List[str] = ['429', 'rate limit', 'rate_limit', 'too many requests', 'overloaded', 'quota exceeded', 'try again later']
_MAX_ERROR_LEN: int = 500
_RECOVERY_RE = re.compile('(\\d+(?:\\.\\d+)?)\\s*(minutes?|mins?|seconds?|secs?|m|s)\\b', re.IGNORECASE)

def is_rate_limit_error(text: Optional[str]) -> bool:
    """Return True if ``text`` looks like a rate-limit / overload error."""
    if not text:
        return False
    lowered = text.lower()
    return any((pattern in lowered for pattern in RATE_LIMIT_PATTERNS))

def parse_recovery_time(text: Optional[str]) -> float:
    """Parse a recovery window (in seconds) from an error/hint string.

    Understands "<n> seconds" and "<n> minutes" (and common abbreviations).
    Falls back to :data:`DEFAULT_RECOVERY_SECONDS` when nothing parses.
    """
    if text:
        match = _RECOVERY_RE.search(text)
        if match is not None:
            value = float(match.group(1))
            unit = match.group(2).lower()
            if unit.startswith('m'):
                return value * 60.0
            return value
    return DEFAULT_RECOVERY_SECONDS

def _fresh_limit() -> Dict[str, Optional[float]]:
    """A blank per-model limit record."""
    return {'hit_at': None, 'recovery_at': None, 'error': None}

def make_default_state() -> Dict[str, object]:
    """Return a fresh default cascade state dict (no shared mutable defaults)."""
    return {'active_model': CASCADE_ORDER[0], 'cascade': list(CASCADE_ORDER), 'last_updated': None, 'limits': {model: _fresh_limit() for model in CASCADE_ORDER}}

class ModelCascade:
    """Pure state machine deciding the active model over an injected clock."""

    def __init__(self, clock: Optional[Callable[[], float]]=None):
        if clock is None:
            clock = lambda: 0.0
        self._clock: Callable[[], float] = clock
        self._limits: Dict[str, Dict[str, Optional[float]]] = {model: _fresh_limit() for model in CASCADE_ORDER}
        self._active: str = CASCADE_ORDER[0]

    def _now(self) -> float:
        return float(self._clock())

    def _is_limited(self, model: str) -> bool:
        return self._limits[model]['recovery_at'] is not None

    def _clear_recovered(self, now: float) -> None:
        for model in CASCADE_ORDER:
            recovery_at = self._limits[model]['recovery_at']
            if recovery_at is not None and now >= recovery_at:
                self._limits[model] = _fresh_limit()

    def _refresh_active(self) -> str:
        now = self._now()
        self._clear_recovered(now)
        for model in CASCADE_ORDER:
            if not self._is_limited(model):
                self._active = model
                return model
        soonest = min(CASCADE_ORDER, key=lambda m: self._limits[m]['recovery_at'])
        self._limits[soonest] = _fresh_limit()
        self._active = soonest
        return soonest

    def get_active_model(self) -> str:
        return self._refresh_active()

    def get_backend_config(self) -> Tuple[str, Optional[str]]:
        return MODEL_BACKENDS[self.get_active_model()]

    def report_rate_limit(self, model: str, error_text: Optional[str]=None, recovery_seconds: Optional[float]=None) -> str:
        """Record a rate-limit hit for ``model`` and return the new active model."""
        now = self._now()
        if recovery_seconds is None:
            recovery_seconds = DEFAULT_RECOVERY_SECONDS
        recovery_seconds = float(recovery_seconds)
        stored_error: Optional[str] = None
        if error_text is not None:
            stored_error = str(error_text)[:_MAX_ERROR_LEN]
        self._limits[model] = {'hit_at': now, 'recovery_at': now + recovery_seconds, 'error': stored_error}
        return self._refresh_active()

    def status(self) -> Dict[str, object]:
        active = self._refresh_active()
        now = self._now()
        models: Dict[str, Dict[str, object]] = {}
        for model in CASCADE_ORDER:
            limit = self._limits[model]
            recovery_at = limit['recovery_at']
            if recovery_at is not None:
                entry: Dict[str, object] = {'status': 'rate_limited', 'recovery_in_seconds': float(recovery_at) - now}
                if limit['error'] is not None:
                    entry['error'] = str(limit['error'])[:_MAX_ERROR_LEN]
                models[model] = entry
            else:
                models[model] = {'status': 'available'}
        return {'active_model': active, 'cascade': list(CASCADE_ORDER), 'models': models}

    def reset(self) -> None:
        self._limits = {model: _fresh_limit() for model in CASCADE_ORDER}
        self._active = CASCADE_ORDER[0]
_CASCADE: Optional[ModelCascade] = None

def reset_cascade(clock: Optional[Callable[[], float]]=None) -> ModelCascade:
    """(Re)create the module-level cascade singleton with an injected clock."""
    global _CASCADE
    _CASCADE = ModelCascade(clock=clock)
    return _CASCADE

def _get_cascade() -> ModelCascade:
    global _CASCADE
    if _CASCADE is None:
        _CASCADE = ModelCascade()
    return _CASCADE

def get_active_model() -> str:
    return _get_cascade().get_active_model()

def get_backend_config() -> Tuple[str, Optional[str]]:
    return _get_cascade().get_backend_config()

def report_rate_limit(model: str, error_text: Optional[str]=None, recovery_seconds: Optional[float]=None) -> str:
    return _get_cascade().report_rate_limit(model, error_text=error_text, recovery_seconds=recovery_seconds)

def status() -> Dict[str, object]:
    return _get_cascade().status()