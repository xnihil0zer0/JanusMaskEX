"""Per-mode procedure guidance for the overseer.

This module is the prompt-side companion to :mod:`overseer.modes`.  It holds the
per-mode procedure text (``MODE_PROMPTS``) and renders the SessionStart
``additionalContext`` analog (``render_mode_context``) that tells an operating
agent which mode it is in, which tier that mode belongs to, and what it may or
may not do.

Coverage of the mode set is sourced directly from :data:`overseer.modes.MODE_REGISTRY`
so the two stay in lockstep -- no parallel hardcoded list of modes is kept.  The
module is stdlib-only and performs no agent spawn, subprocess, model, network,
or SSE side effects.
"""
from __future__ import annotations
from typing import Any, Dict, Mapping
from overseer.modes import MODE_REGISTRY
__all__ = ['MODE_PROMPTS', 'render_mode_context']
_TIER_S_MODES = frozenset({'flag-steward', 'harness-self-fix', 'security-review', 'rebuild-factory', 'push'})
_READ_ONLY_MODES = frozenset({'observe'})
_DESCRIPTIONS: Dict[str, str] = {'observe': 'Read-only reconnaissance. Inspect state, logs, diffs, and artifacts to build a picture of the system. You may read anything in scope; you may NOT write, mutate, or take any action that changes state.', 'flag-steward': 'Steward submitted flags and scoring artifacts. Validate, record, and reconcile flag state with care -- this is a privileged, audited path.', 'harness-self-fix': 'Repair the harness itself. Apply minimal, well-scoped fixes to harness internals; every change is privileged and must be justified.', 'security-review': 'Conduct an authorized security review. Analyze code and configuration for vulnerabilities and report findings; act only within review scope.', 'rebuild-factory': 'Rebuild factory/build infrastructure from a known-good baseline. This is a high-impact, privileged operation gated behind an explicit unlock.', 'push': 'Publish or push artifacts outward. This is an outward-facing, irreversible action and is a privileged, unlock-gated operation.'}

def _tier_of(mode_obj: Any) -> str:
    """Return the tier label for a registry entry as a string."""
    tier = getattr(mode_obj, 'tier', '')
    return tier if isinstance(tier, str) else str(tier)

def _is_tier_s(name: str, mode_obj: Any) -> bool:
    """Whether ``name`` is a privileged (unlock-gated) Tier-S mode."""
    tier = _tier_of(mode_obj).strip().upper()
    if tier in {'S', 'TIER-S', 'TIER_S'}:
        return True
    return name in _TIER_S_MODES

def _is_read_only(name: str, mode_obj: Any) -> bool:
    """Whether ``name`` is a read-only mode that must not write."""
    for attr in ('read_only', 'readonly', 'is_read_only'):
        value = getattr(mode_obj, attr, None)
        if isinstance(value, bool):
            return value
    for attr in ('can_write', 'writes', 'writable'):
        value = getattr(mode_obj, attr, None)
        if isinstance(value, bool):
            return not value
    return name in _READ_ONLY_MODES

def _procedure_text(name: str, mode_obj: Any) -> str:
    """Build the per-mode procedure-guidance text for ``name``."""
    base = _DESCRIPTIONS.get(name)
    if base is None:
        tier = _tier_of(mode_obj)
        base = f"Operate strictly within the constraints of the '{name}' mode (tier {tier}). Take only actions this mode authorizes and stop at its boundaries."
    if _is_read_only(name, mode_obj) and 'read' not in base.lower():
        base = base + ' This is a read-only mode; no writes are permitted.'
    return base
MODE_PROMPTS: Dict[str, str] = {name: _procedure_text(name, MODE_REGISTRY[name]) for name in MODE_REGISTRY}

def render_mode_context(mode: str, state: Mapping[str, Any]) -> str:
    """Render the SessionStart-style context block for ``mode``.

    The returned string names the active mode and its tier, restates the mode's
    procedure guidance, and surfaces the privileged-unlock requirement for
    Tier-S modes and the no-writes constraint for read-only modes.

    Raises:
        KeyError: if ``mode`` is not a registered mode.
    """
    if mode not in MODE_REGISTRY:
        raise KeyError(mode)
    text = MODE_PROMPTS[mode]
    mode_obj = MODE_REGISTRY[mode]
    tier = _tier_of(mode_obj)
    lines = [f'You are operating in mode={mode} (tier={tier}).', text]
    if _is_tier_s(mode, mode_obj):
        lines.append(f"Tier-S mode: '{mode}' is privileged and must be explicitly unlocked before use. Do not proceed unless the unlock requirement for this tier has been satisfied.")
    if _is_read_only(mode, mode_obj):
        lines.append('Read-only mode: you may read and inspect, but no writes or state-changing actions are permitted.')
    return '\n'.join(lines)