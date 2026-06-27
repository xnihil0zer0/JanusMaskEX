"""Deterministic SHA-256 integrity registry for protected prompt/template files.

A pure, stdlib-only tamper-detection registry distilled from the legacy
``services/prompt_integrity.py``. The module hashes the relative paths named in
:data:`PROTECTED_FILES` that exist under a ``base_dir``, round-trips the registry
as indent=2 JSON, and reports ``INTEGRITY VIOLATION`` entries on mismatch or
missing files while failing open when no registry exists.

All I/O and external effects (filesystem reads, existence checks, the wall clock)
are taken through injected seams with deterministic defaults, so the same inputs
always produce the same output.
"""
from __future__ import annotations
import hashlib
import json
import os
from typing import Callable, Dict, List, Optional, Tuple
__all__ = ['PROTECTED_FILES', 'build_registry', 'compute_hash', 'load_registry', 'save_registry', 'update_registry', 'verify_all', 'verify_file']
PROTECTED_FILES: List[str] = ['orchestrator/prompts/system.md', 'orchestrator/prompts/safety.md', 'orchestrator/prompts/tools.md']
_DEFAULT_TIMESTAMP = '1970-01-01T00:00:00Z'

def _default_now() -> str:
    """Deterministic default clock seam: a fixed ISO-8601 timestamp string."""
    return _DEFAULT_TIMESTAMP

def _read_bytes(filepath: str) -> bytes:
    """Default filesystem read seam: raw bytes of ``filepath``."""
    with open(filepath, 'rb') as fh:
        return fh.read()

def _violation_message(rel_path: str, status: str) -> str:
    """Render a human-readable integrity violation message."""
    return 'INTEGRITY VIOLATION: %s (%s)' % (rel_path, status)

def compute_hash(filepath: str, *, read_fn: Optional[Callable[[str], bytes]]=None) -> str:
    """Return the lowercase SHA-256 hex digest of the raw bytes of ``filepath``."""
    reader = read_fn or _read_bytes
    return hashlib.sha256(reader(filepath)).hexdigest()

def build_registry(base_dir: str, *, now_fn: Optional[Callable[[], str]]=None, exists_fn: Optional[Callable[[str], bool]]=None, read_fn: Optional[Callable[[str], bytes]]=None) -> Dict[str, object]:
    """Hash every existing protected file under ``base_dir`` into a registry.

    Files named in :data:`PROTECTED_FILES` that are absent are skipped (not an
    error). The returned mapping has the shape::

        {"version": 1, "updated_at": <str>, "hashes": {rel: {"sha256", "updated_at"}}}
    """
    now = now_fn or _default_now
    exists = exists_fn or os.path.isfile
    timestamp = now()
    hashes: Dict[str, Dict[str, str]] = {}
    for rel in PROTECTED_FILES:
        abs_path = os.path.join(base_dir, rel)
        if not exists(abs_path):
            continue
        hashes[rel] = {'sha256': compute_hash(abs_path, read_fn=read_fn), 'updated_at': timestamp}
    return {'version': 1, 'updated_at': timestamp, 'hashes': hashes}

def save_registry(registry: Dict[str, object], path: str) -> None:
    """Persist ``registry`` to ``path`` as indent=2 JSON, creating parent dirs."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(registry, fh, indent=2)

def load_registry(path: str) -> Dict[str, object]:
    """Load the registry at ``path``; return ``{}`` if missing or corrupt."""
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data

def update_registry(base_dir: str, path: Optional[str]=None, *, now_fn: Optional[Callable[[], str]]=None, exists_fn: Optional[Callable[[str], bool]]=None, read_fn: Optional[Callable[[str], bytes]]=None) -> Dict[str, object]:
    """Build the registry for ``base_dir`` and, if ``path`` is given, persist it."""
    registry = build_registry(base_dir, now_fn=now_fn, exists_fn=exists_fn, read_fn=read_fn)
    if path is not None:
        save_registry(registry, path)
    return registry

def _registered_hashes(registry: Optional[Dict[str, object]]) -> Dict[str, Dict[str, str]]:
    """Extract the ``hashes`` mapping from a registry, tolerating bad input."""
    if not isinstance(registry, dict):
        return {}
    hashes = registry.get('hashes')
    if not isinstance(hashes, dict):
        return {}
    return hashes

def verify_file(rel_path: str, *, registry: Optional[Dict[str, object]]=None, base_dir: str='.', exists_fn: Optional[Callable[[str], bool]]=None, read_fn: Optional[Callable[[str], bytes]]=None) -> Tuple[bool, str]:
    """Verify a single relative path against ``registry``.

    Fails open when no registry is present ``(True, "no registry")`` and skips
    paths that were never registered ``(True, "not registered")``.
    """
    hashes = _registered_hashes(registry)
    if not hashes:
        return (True, 'no registry')
    if rel_path not in hashes:
        return (True, 'not registered')
    exists = exists_fn or os.path.isfile
    abs_path = os.path.join(base_dir, rel_path)
    if not exists(abs_path):
        return (False, _violation_message(rel_path, 'missing'))
    expected = hashes[rel_path].get('sha256')
    actual = compute_hash(abs_path, read_fn=read_fn)
    if actual != expected:
        return (False, _violation_message(rel_path, 'mismatch'))
    return (True, 'ok')

def verify_all(base_dir: str, registry: Optional[Dict[str, object]], *, exists_fn: Optional[Callable[[str], bool]]=None, read_fn: Optional[Callable[[str], bytes]]=None) -> List[Dict[str, str]]:
    """Verify every registered file under ``base_dir``; return violation dicts.

    Each violation is ``{"file": rel, "status": "missing"|"mismatch", "message": str}``.
    An empty list means the registry is clean (or there is nothing to verify).
    """
    hashes = _registered_hashes(registry)
    exists = exists_fn or os.path.isfile
    violations: List[Dict[str, str]] = []
    for rel, entry in hashes.items():
        abs_path = os.path.join(base_dir, rel)
        if not exists(abs_path):
            violations.append({'file': rel, 'status': 'missing', 'message': _violation_message(rel, 'missing')})
            continue
        expected = entry.get('sha256') if isinstance(entry, dict) else None
        actual = compute_hash(abs_path, read_fn=read_fn)
        if actual != expected:
            violations.append({'file': rel, 'status': 'mismatch', 'message': _violation_message(rel, 'mismatch')})
    return violations