"""Mode-gated action dispatch for the overseer.

This module declares a routing table mapping each operating mode to the set of
commands it is permitted to issue, and the *seam key* each command resolves to.
``dispatch_action`` enforces mode authority **first** (fail-closed): an unknown
mode or an out-of-mode command raises :class:`overseer.mode_gate.ModeViolation`
*before* any seam is resolved or invoked, guaranteeing zero side effects on
rejection. Only after the authority check passes is the command routed to the
injected ``seams`` bundle, which is the sole side-effect path.

Read-only modes (``observe``/``analyze``/``audit``) only ever reference read
seam keys, never a write/mutating seam, by construction of ``ACTION_ROUTES``.
"""
from __future__ import annotations
from typing import Any, Dict, Mapping
from overseer.mode_gate import ModeViolation
from overseer.modes import MODE_REGISTRY
_DECLARED_ROUTES: Dict[str, Dict[str, str]] = {'observe': {'status': 'status', 'snapshot': 'snapshot', 'tail': 'tail_log'}, 'analyze': {'inspect': 'inspect', 'diff': 'read_diff'}, 'audit': {'report': 'audit_report', 'history': 'read_history'}, 'brief-author': {'author_brief': 'brief_author', 'author_oracle': 'oracle_author'}, 'dispatch': {'dispatch': 'dispatch', 'triage': 'triage'}, 'daemon-supervisor': {'pause': 'daemon_lifecycle', 'resume': 'daemon_lifecycle', 'steward_flags': 'flag_steward'}}
ACTION_ROUTES: Dict[str, Dict[str, str]] = {mode: dict(routes) for mode, routes in _DECLARED_ROUTES.items() if mode in MODE_REGISTRY}

def _resolve_seam(seams: Any, seam_key: str) -> Any:
    """Resolve a seam callable from the injected bundle.

    Supports both mapping-style bundles (``seams[seam_key]``) and
    attribute-style bundles (``seams.seam_key``). Resolution happens only
    after the mode-authority check has passed.
    """
    try:
        return seams[seam_key]
    except (TypeError, KeyError):
        return getattr(seams, seam_key)

def dispatch_action(mode: str, command: str, args: Any, *, seams: Any) -> Dict[str, Any]:
    """Verify mode authority, then route ``command`` to its seam.

    The authority check is fail-closed and precedes all side effects:

    * An unknown ``mode`` raises :class:`ModeViolation` before any seam touch.
    * A ``command`` not permitted under ``mode`` raises :class:`ModeViolation`
      before any seam touch.

    On a valid ``(mode, command)`` pair, the resolved seam is called with
    ``args`` forwarded verbatim and its dict result is returned unchanged.
    Exactly one seam fires per valid command; zero seams fire on rejection.
    """
    routes: Mapping[str, str] | None = ACTION_ROUTES.get(mode)
    if routes is None:
        raise ModeViolation(f'mode {mode!r} is not authorized to dispatch actions')
    if command not in routes:
        raise ModeViolation(f'command {command!r} is not permitted under mode {mode!r}')
    seam_key = routes[command]
    seam = _resolve_seam(seams, seam_key)
    return seam(args)