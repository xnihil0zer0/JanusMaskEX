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

def dispatch_action(
    mode: str,
    command: str,
    args: Any,
    *,
    seams: Any,
    phase: str | None = None,
    phase_policy: Mapping[str, Any] = globals().setdefault('PHASE_COMMAND_POLICY', {}),
) -> Dict[str, Any]:
    """Verify mode authority *and* phase sequence-lock, then route ``command``.

    Two fail-closed authority checks precede every side effect, evaluated in
    order before any seam is resolved or invoked:

    * **(mode, command)** -- an unknown ``mode`` or an out-of-mode ``command``
      raises :class:`ModeViolation` before any seam touch (unchanged behaviour).
    * **(phase, command)** -- *additively*, when a procedure ``phase`` is active
      (``phase is not None``), a ``command`` not sanctioned by that phase under
      ``phase_policy`` raises :class:`ModeViolation` before any seam touch. With
      ``phase is None`` this check is skipped and prior behaviour is preserved.

    ``phase_policy`` maps a phase name to the set/collection of commands that
    phase sanctions; it defaults to the module-level :data:`PHASE_COMMAND_POLICY`
    registry. The phase gate is consulted *before* any seam call, so a refusal
    is guaranteed to be side-effect free.

    On a valid ``(mode, command)`` pair that is also sanctioned by the active
    phase (or with no active phase), the resolved seam is called with ``args``
    forwarded verbatim and its dict result is returned unchanged. Exactly one
    seam fires per permitted command; zero seams fire on any rejection.
    """
    routes: Mapping[str, str] | None = ACTION_ROUTES.get(mode)
    if routes is None:
        raise ModeViolation(f'mode {mode!r} is not authorized to dispatch actions')
    if command not in routes:
        raise ModeViolation(f'command {command!r} is not permitted under mode {mode!r}')
    # Beside the (mode, command) authority check: a fail-closed (phase, command)
    # sequence-lock. While a procedure phase is active, only commands sanctioned
    # by the CURRENT phase may proceed; refusal happens before any seam resolves.
    if phase is not None:
        policy: Mapping[str, Any] = phase_policy if phase_policy is not None else PHASE_COMMAND_POLICY
        sanctioned = policy.get(phase, frozenset())
        if command not in sanctioned:
            raise ModeViolation(
                f'command {command!r} is not sanctioned by phase {phase!r}'
            )
    seam_key = routes[command]
    seam = _resolve_seam(seams, seam_key)
    return seam(args)