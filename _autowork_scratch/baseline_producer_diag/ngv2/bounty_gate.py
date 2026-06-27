"""Deterministic economic GO/SKIP/UNKNOWN gate over injected bounty data.

``bounty_gate`` decides whether hunting an owner/repo for a given CWE +
severity is economically worth it. The decision is computed *solely* from
an injected bounty-data dict supplied via the keyword argument ``bounties``.

The module is pure and stdlib-only: no disk, no network, no clock, no
randomness, no subprocess. Identical inputs always yield identical outputs.
"""
from __future__ import annotations
from typing import Any, Dict, Mapping, Optional, Tuple
__all__ = ['gate', 'normalize_repo', 'normalize_cwe', 'get_severity_payout', 'check_zero_override', 'ZERO_PAYOUT_OVERRIDES', 'GATE_RESULT_FIELDS', 'DECISIONS']
GATE_RESULT_FIELDS: Tuple[str, ...] = ('decision', 'expected_payout', 'tier', 'reasoning')
DECISIONS: Tuple[str, ...] = ('GO', 'SKIP', 'UNKNOWN')
ZERO_PAYOUT_OVERRIDES: Dict[str, set] = {}
_FORMAT_PREFIX = 'FORMAT:'

def normalize_repo(owner_repo: Any) -> str:
    """Return a canonical ``owner/repo`` string: stripped and lowercased."""
    return str(owner_repo).strip().lower()

def normalize_cwe(cwe: Any) -> str:
    """Return a canonical uppercase CWE identifier (e.g. ``CWE-502``)."""
    return str(cwe).strip().upper()

def _normalize_severity(severity: Any) -> str:
    return str(severity).strip().lower()

def _lookup_ci(mapping: Any, name: str) -> Optional[Any]:
    """Case-insensitive read of ``mapping[name]``; ``None`` if absent/malformed."""
    if not isinstance(mapping, Mapping):
        return None
    target = name.strip().lower()
    for stored, value in mapping.items():
        if str(stored).strip().lower() == target:
            return value
    return None

def get_severity_payout(repo_data: Any, severity: Any) -> Optional[Any]:
    """Read the observed payout for ``severity`` from a repo entry.

    Returns the observed value (which may legitimately be ``0``) when the
    severity is present in ``observed_payouts`` case-insensitively, otherwise
    ``None``.
    """
    if not isinstance(repo_data, Mapping):
        return None
    observed = repo_data.get('observed_payouts')
    return _lookup_ci(observed, _normalize_severity(severity))

def check_zero_override(owner_repo: Any, cwe: Any, severity: Any) -> bool:
    """Return True when a zero-payout override matches this repo + CWE/severity."""
    repo = normalize_repo(owner_repo)
    triggers = ZERO_PAYOUT_OVERRIDES.get(repo)
    if not triggers:
        return False
    if normalize_cwe(cwe) in triggers:
        return True
    if _normalize_severity(severity) in triggers:
        return True
    return False

def _result(decision: str, expected_payout: Optional[Any], tier: Optional[Any], reasoning: str) -> Dict[str, Any]:
    return {'decision': decision, 'expected_payout': expected_payout, 'tier': tier, 'reasoning': reasoning}

def _gate_format(fmt: str, cwe: Any, severity: Any, bounties: Mapping[str, Any]) -> Dict[str, Any]:
    """Decide for a synthetic ``FORMAT:<fmt>`` target via the formats tables."""
    fmt_data = _lookup_ci(bounties.get('formats'), fmt)
    if not isinstance(fmt_data, Mapping):
        return _result('UNKNOWN', None, None, "no bounty data for format '%s'" % fmt)
    tier = fmt_data.get('tier')
    tier_table = _lookup_ci(bounties.get('format_tiers'), str(tier)) if tier is not None else None
    payout = _lookup_ci(tier_table, _normalize_severity(severity))
    if payout is None:
        payout = fmt_data.get('bounty')
    if payout is None:
        return _result('UNKNOWN', None, tier, "no payout basis for format '%s' at severity %s" % (fmt, severity))
    try:
        positive = payout > 0
    except TypeError:
        return _result('UNKNOWN', None, tier, "malformed payout for format '%s'" % fmt)
    if not positive:
        return _result('SKIP', 0, tier, "zero expected payout for format '%s' at severity %s" % (fmt, severity))
    return _result('GO', payout, tier, "format '%s' tier %s pays %s at severity %s" % (fmt, tier, payout, severity))

def gate(owner_repo: Any, cwe: Any, severity: Any, *, bounties: Optional[Mapping[str, Any]]=None) -> Dict[str, Any]:
    """Decide GO / SKIP / UNKNOWN for ``owner_repo`` at ``cwe`` + ``severity``.

    The decision is computed purely from the injected ``bounties`` mapping.

    Returns a dict with exactly the keys in :data:`GATE_RESULT_FIELDS`.
    """
    data: Mapping[str, Any] = bounties if isinstance(bounties, Mapping) else {}
    raw = str(owner_repo).strip()
    if raw.upper().startswith(_FORMAT_PREFIX):
        fmt = raw[len(_FORMAT_PREFIX):].strip()
        return _gate_format(fmt, cwe, severity, data)
    repo = normalize_repo(owner_repo)
    confirmed = data.get('not_eligible_confirmed') or []
    try:
        confirmed_norm = {normalize_repo(r) for r in confirmed}
    except TypeError:
        confirmed_norm = set()
    if repo in confirmed_norm:
        return _result('SKIP', 0, None, "repo '%s' is on the not-eligible-confirmed list" % repo)
    repos = data.get('repos')
    repo_data = _lookup_ci(repos, repo) if isinstance(repos, Mapping) else None
    if not isinstance(repo_data, Mapping):
        return _result('UNKNOWN', None, None, "no bounty data for repo '%s'" % repo)
    tier = repo_data.get('tier')
    if not repo_data.get('eligible', False):
        return _result('SKIP', 0, tier, "repo '%s' is marked ineligible" % repo)
    if check_zero_override(repo, cwe, severity):
        return _result('SKIP', 0, tier, "repo '%s' has a zero-payout override for %s/%s" % (repo, normalize_cwe(cwe), severity))
    payout = get_severity_payout(repo_data, severity)
    if payout is None:
        tier_table = _lookup_ci(data.get('tiers'), str(tier)) if tier is not None else None
        payout = _lookup_ci(tier_table, _normalize_severity(severity))
    if payout is None:
        max_paid = repo_data.get('max_paid')
        if isinstance(max_paid, (int, float)) and max_paid > 0:
            payout = max_paid
    if payout is None:
        return _result('UNKNOWN', None, tier, "no payout basis for repo '%s' at severity %s" % (repo, severity))
    try:
        positive = payout > 0
    except TypeError:
        return _result('UNKNOWN', None, tier, "malformed payout for repo '%s'" % repo)
    if not positive:
        return _result('SKIP', 0, tier, "zero expected payout for repo '%s' at severity %s" % (repo, severity))
    return _result('GO', payout, tier, "repo '%s' tier %s pays %s at severity %s" % (repo, tier, payout, severity))