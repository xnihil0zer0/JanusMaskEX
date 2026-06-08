"""overseer/modes.py — the overseer mode registry.

Pure DATA module (stdlib only): a frozen :class:`ModeSpec` per mode plus the
lookup / availability helpers. The 14 modes and their tier/unlock posture are
the security spine of the overseer:

* **Tier R** (read-only) modes are auto-granted and never require an unlock.
* **Tier W** (write) modes are auto-granted but carry authoring/dispatch
  authority.
* **Tier S** (security-gated) modes are *unlock-only* — they can never be
  self-selected or auto-available.

``observe`` is the default boot mode and the universal fallback: on ambiguity,
error, or an expired unlock every mode reverts to ``observe``.
"""
from __future__ import annotations
from dataclasses import dataclass, field, fields
from typing import Dict, Iterable, List, Optional, Tuple
__all__ = ['ModeSpec', 'MODE_REGISTRY', 'get_mode', 'list_available_modes', 'requires_unlock']

@dataclass(frozen=True)
class ModeSpec:
    """An immutable description of a single overseer mode.

    The field names and their order are pinned by the committed oracle and
    must not change. Collection fields are tuples so the dataclass stays
    hashable and free of mutable-default pitfalls.
    """
    name: str
    tier: str
    janusmask_mode: str
    allowed_tools: Tuple[str, ...] = field(default_factory=tuple)
    allowed_routes: Tuple[str, ...] = field(default_factory=tuple)
    allowed_meta_task_types: Tuple[str, ...] = field(default_factory=tuple)
    inbox_contract: str = ''
    outbox_contract: str = ''
    apply_authority: str = 'none'
    default_available: bool = False
    requires_unlock: bool = False
    fallback_mode: str = 'observe'
_FALLBACK = 'observe'

def _spec(name: str, tier: str, janusmask_mode: str, *, allowed_tools: Iterable[str]=(), allowed_routes: Iterable[str]=(), allowed_meta_task_types: Iterable[str]=(), inbox_contract: str='', outbox_contract: str='', apply_authority: str='none') -> ModeSpec:
    """Build a :class:`ModeSpec`, deriving availability from the tier.

    Tier R/W are default-available and never require unlock; Tier S is
    unlock-only and never auto-available. ``fallback_mode`` is always
    ``observe``.
    """
    is_tier_s = tier == 'S'
    return ModeSpec(name=name, tier=tier, janusmask_mode=janusmask_mode, allowed_tools=tuple(allowed_tools), allowed_routes=tuple(allowed_routes), allowed_meta_task_types=tuple(allowed_meta_task_types), inbox_contract=inbox_contract, outbox_contract=outbox_contract, apply_authority=apply_authority, default_available=not is_tier_s, requires_unlock=is_tier_s, fallback_mode=_FALLBACK)
_SPECS: Tuple[ModeSpec, ...] = (_spec('observe', 'R', 'none', allowed_tools=('read', 'search', 'list'), allowed_routes=('status', 'inspect'), allowed_meta_task_types=('observation',), inbox_contract='none', outbox_contract='report', apply_authority='none'), _spec('analyze', 'R', 'none', allowed_tools=('read', 'search', 'list', 'diff'), allowed_routes=('status', 'inspect', 'analyze'), allowed_meta_task_types=('analysis',), inbox_contract='none', outbox_contract='report', apply_authority='none'), _spec('audit', 'R', 'none', allowed_tools=('read', 'search', 'list', 'diff'), allowed_routes=('status', 'inspect', 'audit'), allowed_meta_task_types=('audit',), inbox_contract='none', outbox_contract='report', apply_authority='none'), _spec('brief-author', 'W', 'planning', allowed_tools=('read', 'search', 'write'), allowed_routes=('author-brief',), allowed_meta_task_types=('brief', 'plan'), inbox_contract='brief-request', outbox_contract='brief', apply_authority='author'), _spec('oracle-author', 'W', 'synthesis', allowed_tools=('read', 'search', 'write'), allowed_routes=('author-oracle',), allowed_meta_task_types=('oracle', 'test_spec'), inbox_contract='oracle-request', outbox_contract='oracle', apply_authority='author'), _spec('dispatch', 'W', 'planning', allowed_tools=('read', 'search', 'write'), allowed_routes=('dispatch',), allowed_meta_task_types=('dispatch',), inbox_contract='task', outbox_contract='dispatch-record', apply_authority='dispatch'), _spec('triage', 'W', 'planning', allowed_tools=('read', 'search', 'write'), allowed_routes=('triage',), allowed_meta_task_types=('triage',), inbox_contract='signal', outbox_contract='triage-record', apply_authority='triage'), _spec('daemon-supervisor', 'W', 'reconciliation', allowed_tools=('read', 'search', 'write'), allowed_routes=('supervise',), allowed_meta_task_types=('supervision',), inbox_contract='daemon-state', outbox_contract='supervision-record', apply_authority='supervise'), _spec('ui-tester', 'W', 'synthesis', allowed_tools=('read', 'search', 'write', 'drive-ui'), allowed_routes=('ui-test',), allowed_meta_task_types=('ui_test',), inbox_contract='ui-test-request', outbox_contract='ui-test-record', apply_authority='author'), _spec('flag-steward', 'S', 'reconciliation', allowed_tools=('read', 'search', 'write'), allowed_routes=('flag-steward',), allowed_meta_task_types=('flag',), inbox_contract='flag-request', outbox_contract='flag-record', apply_authority='apply'), _spec('harness-self-fix', 'S', 'synthesis', allowed_tools=('read', 'search', 'write'), allowed_routes=('self-fix',), allowed_meta_task_types=('self_fix',), inbox_contract='self-fix-request', outbox_contract='self-fix-record', apply_authority='apply'), _spec('security-review', 'S', 'reconciliation', allowed_tools=('read', 'search'), allowed_routes=('security-review',), allowed_meta_task_types=('security_review',), inbox_contract='security-review-request', outbox_contract='security-review-record', apply_authority='apply'), _spec('rebuild-factory', 'S', 'synthesis', allowed_tools=('read', 'search', 'write'), allowed_routes=('rebuild-factory',), allowed_meta_task_types=('rebuild',), inbox_contract='rebuild-request', outbox_contract='rebuild-record', apply_authority='apply'), _spec('push', 'S', 'reconciliation', allowed_tools=('read', 'search', 'write', 'push'), allowed_routes=('push',), allowed_meta_task_types=('push',), inbox_contract='push-request', outbox_contract='push-record', apply_authority='apply'))
MODE_REGISTRY: Dict[str, ModeSpec] = {spec.name: spec for spec in _SPECS}
assert all((name == spec.name for name, spec in MODE_REGISTRY.items()))

def get_mode(name: Optional[str]) -> ModeSpec:
    """Return the :class:`ModeSpec` registered under ``name``.

    ``None`` and the sentinel ``"none"`` resolve to the default ``observe``
    mode. Any other unregistered name raises ``KeyError`` (the oracle requires
    unknown names to be rejected rather than silently coerced).
    """
    if name is None or name == 'none':
        return MODE_REGISTRY[_FALLBACK]
    return MODE_REGISTRY[name]

def list_available_modes(unlocked: Iterable[str]=frozenset()) -> List[str]:
    """Return the mode names available given the ``unlocked`` set.

    Always includes the default-available Tier R/W modes; additionally
    includes any Tier S (unlock-only) mode whose name appears in ``unlocked``.
    """
    unlocked_set = set(unlocked or ())
    available: List[str] = []
    for name, spec in MODE_REGISTRY.items():
        if spec.default_available or name in unlocked_set:
            available.append(name)
    return available

def requires_unlock(name: str) -> bool:
    """Return whether ``name`` is an unlock-only (Tier S) mode."""
    return MODE_REGISTRY[name].requires_unlock
_PINNED_FIELDS: Tuple[str, ...] = tuple((f.name for f in fields(ModeSpec)))