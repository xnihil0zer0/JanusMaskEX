"""Mode enforcement gate for the overseer.

A *mode* is the privilege CEILING. It is enforced by WITHHOLDING tools and
routes (mirroring ``harness/mcp_server.build_execute_tool``), never by prompt.
A denied operation surfaces as a typed :class:`ModeViolation`.

This module is stdlib-only. All mode metadata (tiers, the default-available
Tier-W set, the observe baseline, per-mode tool/route grants) is sourced from
the :mod:`overseer.modes` registry rather than duplicated here. Where the
registry's ``ModeSpec`` does not surface a particular field, we fall back to the
lattice membership the committed oracle pins down.
"""
from __future__ import annotations
from typing import Collection, List, Optional
from overseer.modes import MODE_REGISTRY, get_mode

class ModeViolation(Exception):
    """Raised when a mode withholds the requested tool or route."""
_ROUTE_TABLE = {('GET', '/api/state'): 'status', ('POST', '/api/chat/send'): 'dispatch', ('PUT', '/api/config/control'): 'flag-steward'}
_OBSERVE = 'observe'
_TIER_RANK = {'R': 0, 'W': 1, 'S': 2}
_FALLBACK_TIER_R = frozenset({'observe', 'analyze', 'audit'})
_FALLBACK_TIER_W_DEFAULT = frozenset({'dispatch', 'brief-author'})
_FALLBACK_TIER_S = frozenset({'push', 'flag-steward'})
_TIER_ATTRS = ('tier', 'TIER', 'tier_name', 'privilege_tier', 'level')
_DEFAULT_ATTRS = ('default_available', 'is_default_available', 'available_by_default', 'auto_available', 'default')

def _get_spec(mode: str):
    """Resolve ``mode`` to its registry spec or raise :class:`ModeViolation`."""
    spec = None
    try:
        if mode in MODE_REGISTRY:
            spec = MODE_REGISTRY[mode]
    except Exception:
        spec = None
    if spec is None:
        try:
            spec = get_mode(mode)
        except ModeViolation:
            raise
        except Exception as exc:
            raise ModeViolation(f'unknown mode: {mode!r}') from exc
    if spec is None:
        raise ModeViolation(f'unknown mode: {mode!r}')
    return spec

def _safe_spec(mode: str):
    """Best-effort spec lookup that never raises (for lattice probing)."""
    try:
        if mode in MODE_REGISTRY:
            return MODE_REGISTRY[mode]
    except Exception:
        pass
    try:
        spec = get_mode(mode)
        if spec is not None:
            return spec
    except Exception:
        pass
    return None

def _is_known(mode: str) -> bool:
    try:
        if mode in MODE_REGISTRY:
            return True
    except Exception:
        pass
    return _safe_spec(mode) is not None

def _normalise_tier(value: object) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        text = value
    else:
        text = getattr(value, 'name', None) or getattr(value, 'value', None)
        if not isinstance(text, str):
            text = str(value)
    text = text.strip().upper()
    if not text:
        return None
    if text in _TIER_RANK:
        return text
    word_map = {'READ': 'R', 'READONLY': 'R', 'READ_ONLY': 'R', 'OBSERVE': 'R', 'WRITE': 'W', 'WORK': 'W', 'SENSITIVE': 'S', 'SECURE': 'S', 'SUPER': 'S'}
    if text in word_map:
        return word_map[text]
    if text[0] in _TIER_RANK:
        return text[0]
    return None

def _tier_of(mode: str) -> Optional[str]:
    spec = _safe_spec(mode)
    if spec is not None:
        for attr in _TIER_ATTRS:
            if hasattr(spec, attr):
                tier = _normalise_tier(getattr(spec, attr))
                if tier:
                    return tier
    if mode in _FALLBACK_TIER_R:
        return 'R'
    if mode in _FALLBACK_TIER_W_DEFAULT:
        return 'W'
    if mode in _FALLBACK_TIER_S:
        return 'S'
    return None

def _is_default_available(mode: str) -> bool:
    spec = _safe_spec(mode)
    if spec is not None:
        for attr in _DEFAULT_ATTRS:
            if hasattr(spec, attr):
                return bool(getattr(spec, attr))
    return mode in _FALLBACK_TIER_W_DEFAULT

def resolve_tool_allowlist(mode: str) -> List[str]:
    """Return the effective allowed tool names for ``mode``.

    Mirrors ``harness/mcp_server.build_execute_tool`` tool-withholding: the
    effective allowlist is exactly the mode's declared ``allowed_tools`` (the
    withholding is already baked into the registry), order-preserving.
    """
    spec = _get_spec(mode)
    return list(spec.allowed_tools)

def assert_tool_allowed(mode: str, tool: str) -> None:
    """Return ``None`` when ``tool`` is permitted for ``mode``; else raise."""
    if tool in resolve_tool_allowlist(mode):
        return None
    raise ModeViolation(f'tool {tool!r} withheld under mode {mode!r}')

def assert_route_allowed(mode: str, method: str, path: str) -> None:
    """Return ``None`` when the (method, path) route is permitted; else raise."""
    token = _ROUTE_TABLE.get((str(method).upper(), path))
    if token is None:
        raise ModeViolation(f'route {method!r} {path!r} is not exposed under any capability')
    spec = _get_spec(mode)
    if token in spec.allowed_routes:
        return None
    raise ModeViolation(f'route {method!r} {path!r} ({token}) withheld under mode {mode!r}')

def can_switch(current: str, target: str, unlocked: Collection[str]) -> bool:
    """Whether a switch from ``current`` to ``target`` is permitted.

    Lattice rules:
      * free movement among Tier-R modes,
      * transition *down* the lattice permitted anytime,
      * R -> W permitted only for default-available W modes,
      * Tier-S reachable only when ``target`` is in ``unlocked``,
      * a switch back to the observe baseline is always permitted (revertible).
    Switching to an unknown target is never permitted.
    """
    if not _is_known(target):
        return False
    if target == _OBSERVE:
        return True
    if current == target:
        return True
    target_tier = _tier_of(target)
    if target_tier is None:
        return False
    current_tier = _tier_of(current) or 'R'
    target_rank = _TIER_RANK.get(target_tier, 0)
    current_rank = _TIER_RANK.get(current_tier, 0)
    if target_rank < current_rank:
        return True
    if target_tier == 'R':
        return True
    if target_tier == 'S':
        unlocked = unlocked or frozenset()
        return target in unlocked
    return _is_default_available(target)