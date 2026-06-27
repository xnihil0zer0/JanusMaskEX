"""Deterministic safety state machine for ngv2 (stdlib-only, injected seams).

A circuit-breaker + tool-quarantine + JSON-schema-validation + health-check
state machine distilled from the legacy ``services/safety.py``. Made fully
deterministic for the gated factory:

* No module-global on-disk state: every state-touching function takes an
  explicit ``state_path``.
* No wall clock: timestamps are caller-injected via a ``now`` string param
  (default ``""``) -- the module never calls ``datetime.now``.
* No subprocess/disk probes: ``health_check`` is PURE over an injected
  ``probes`` mapping (the seam).
"""
from __future__ import annotations
import json
import os
from typing import Any, Dict, Iterable, List, Mapping, Optional
MAX_CONSECUTIVE_FAILURES: int = 3
QUARANTINE_USES: int = 5
_MAX_ERROR_LEN: int = 500
SCHEMA_CHECKS: Dict[str, Dict[str, Any]] = {'orchestrator/state.json': {'required_keys': ['current_phase', 'cycle_count', 'time_tracking'], 'types': {'current_phase': str, 'cycle_count': int, 'time_tracking': dict}}, 'data/tool_catalog.json': {'required_keys': ['tools'], 'types': {'tools': list}}}

def _empty_state() -> Dict[str, Any]:
    return {'circuit_breakers': {}, 'quarantine': {}, 'updated_at': None}

def load_safety_state(state_path: str) -> Dict[str, Any]:
    """Read JSON safety state from disk, defaulting to the empty shell."""
    try:
        with open(state_path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return _empty_state()
    if not isinstance(data, dict):
        return _empty_state()
    data.setdefault('circuit_breakers', {})
    data.setdefault('quarantine', {})
    data.setdefault('updated_at', None)
    return data

def save_safety_state(state: Mapping[str, Any], state_path: str, now: str='') -> Dict[str, Any]:
    """Atomically write ``state`` as formatted JSON, stamping ``updated_at``."""
    out: Dict[str, Any] = dict(state)
    out.setdefault('circuit_breakers', {})
    out.setdefault('quarantine', {})
    out['updated_at'] = now
    parent = os.path.dirname(state_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp_path = state_path + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as handle:
        json.dump(out, handle, indent=2, sort_keys=True)
    os.replace(tmp_path, state_path)
    return out

def circuit_breaker_check(tool: str, state_path: str) -> Dict[str, Any]:
    """Return the public circuit-breaker view for ``tool`` (safe defaults)."""
    state = load_safety_state(state_path)
    record = state.get('circuit_breakers', {}).get(tool)
    if not isinstance(record, dict):
        return {'tool': tool, 'tripped': False, 'consecutive_failures': 0, 'last_error': '', 'tripped_at': ''}
    return {'tool': tool, 'tripped': bool(record.get('tripped', False)), 'consecutive_failures': int(record.get('consecutive_failures', 0)), 'last_error': record.get('last_error', ''), 'tripped_at': record.get('tripped_at', '')}

def circuit_breaker_trip(tool: str, error: str, state_path: str, now: str='') -> Dict[str, Any]:
    """Record a tool failure, tripping at the consecutive-failure threshold."""
    state = load_safety_state(state_path)
    breakers = state.setdefault('circuit_breakers', {})
    record = breakers.get(tool)
    if not isinstance(record, dict):
        record = {'consecutive_failures': 0, 'total_failures': 0, 'last_error': '', 'tripped': False, 'tripped_at': ''}
        breakers[tool] = record
    record['consecutive_failures'] = int(record.get('consecutive_failures', 0)) + 1
    record['total_failures'] = int(record.get('total_failures', 0)) + 1
    record['last_error'] = (error or '')[:_MAX_ERROR_LEN]
    if record['consecutive_failures'] >= MAX_CONSECUTIVE_FAILURES:
        record['tripped'] = True
        record['tripped_at'] = now
    save_safety_state(state, state_path, now)
    return dict(record)

def circuit_breaker_reset(tool: str, state_path: str) -> Dict[str, Any]:
    """Clear failure counters for ``tool``; a no-op for unknown tools."""
    state = load_safety_state(state_path)
    breakers = state.get('circuit_breakers', {})
    record = breakers.get(tool)
    if not isinstance(record, dict):
        return circuit_breaker_check(tool, state_path)
    record['consecutive_failures'] = 0
    record['tripped'] = False
    record['tripped_at'] = ''
    record['last_error'] = ''
    save_safety_state(state, state_path)
    return circuit_breaker_check(tool, state_path)

def quarantine_status(tool: str, state_path: str) -> Dict[str, Any]:
    """Return quarantine progress for ``tool`` (uses, successes, rate)."""
    state = load_safety_state(state_path)
    entry = state.get('quarantine', {}).get(tool)
    if not isinstance(entry, dict):
        entry = {}
    uses = int(entry.get('uses', 0))
    successes = int(entry.get('successes', 0))
    remaining = max(0, QUARANTINE_USES - uses)
    success_rate: float = successes / uses if uses > 0 else 0
    return {'tool': tool, 'in_quarantine': uses < QUARANTINE_USES, 'uses': uses, 'successes': successes, 'remaining': remaining, 'success_rate': success_rate}

def quarantine_record(tool: str, outcome: str, state_path: str, now: str='') -> Dict[str, Any]:
    """Record one quarantine use; only ``"success"`` counts as a success."""
    state = load_safety_state(state_path)
    quarantine = state.setdefault('quarantine', {})
    entry = quarantine.get(tool)
    if not isinstance(entry, dict):
        entry = {'uses': 0, 'successes': 0, 'last_used': ''}
        quarantine[tool] = entry
    entry['uses'] = int(entry.get('uses', 0)) + 1
    if outcome == 'success':
        entry['successes'] = int(entry.get('successes', 0)) + 1
    entry['last_used'] = now
    save_safety_state(state, state_path, now)
    return quarantine_status(tool, state_path)

def validate_json(path: str, rel_path: Optional[str]=None) -> Dict[str, Any]:
    """Validate a JSON file: existence, parseability, and schema (if known)."""
    file_label = rel_path if rel_path is not None else path
    errors: List[str] = []
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            raw = handle.read()
    except OSError:
        return {'file': file_label, 'valid': False, 'errors': [f'File not found: {path}']}
    try:
        data = json.loads(raw)
    except ValueError as exc:
        return {'file': file_label, 'valid': False, 'errors': [f'JSON parse error: {exc}']}
    schema = SCHEMA_CHECKS.get(rel_path) if rel_path else None
    if schema:
        for required in schema.get('required_keys', []):
            if not isinstance(data, dict) or required not in data:
                errors.append(f'Missing required key: {required}')
        if isinstance(data, dict):
            for field_name, expected in schema.get('types', {}).items():
                if field_name in data and (not isinstance(data[field_name], expected)):
                    errors.append(f'Type mismatch for {field_name}: expected {getattr(expected, '__name__', expected)}')
    return {'file': file_label, 'valid': len(errors) == 0, 'errors': errors}

def make_scripted_probes(entries: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Build a deterministic ``probes`` seam from scripted check entries."""
    checks: List[Dict[str, Any]] = [dict(entry) for entry in entries]
    return {'checks': checks}

def health_check(probes: Mapping[str, Any]) -> Dict[str, Any]:
    """Roll scripted probe statuses up into an overall health verdict (pure)."""
    if isinstance(probes, Mapping):
        checks = list(probes.get('checks', []))
    else:
        checks = list(probes)
    statuses = [str(check.get('status', 'fail')) for check in checks]
    if any((status == 'fail' for status in statuses)):
        overall = 'UNHEALTHY'
    elif any((status == 'warn' for status in statuses)):
        overall = 'DEGRADED'
    else:
        overall = 'HEALTHY'
    return {'overall': overall, 'checks': checks}