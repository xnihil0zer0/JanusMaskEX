"""Pinned-Node resolution for the JS beachhead (Phase B, ac-js-node-version).

Pure, stdlib-only. The ONLY path Phase D ever binds into the agent jail is the
exact ``<nvm_dir>/versions/node/<version>/bin/node`` this module resolves —
never the global ``~/.nvm`` tree — so version strings are validated strictly
and path-escaping ``.nvmrc`` content can never become a path component.
"""
from __future__ import annotations

import os
import re

_VERSION_RE = re.compile(r'^v\d+\.\d+\.\d+$')


def validate_node_version(version) -> bool:
    """True ONLY for a full ``v<major>.<minor>.<patch>`` match on a str."""
    try:
        return isinstance(version, str) and bool(_VERSION_RE.fullmatch(version))
    except Exception:
        return False


def parse_nvmrc(content):
    """Strip an ``.nvmrc`` body and return the version iff it validates."""
    try:
        if not isinstance(content, str):
            return None
        version = content.strip()
        return version if validate_node_version(version) else None
    except Exception:
        return None


def resolve_node_bin(nvm_dir, version):
    """Exact ``<nvm_dir>/versions/node/<version>/bin/node`` or None.

    Defense in depth: even though the version regex already forbids path
    separators, the joined result is re-checked to normalize STRICTLY under
    ``nvm_dir`` (safe_subpath-style)."""
    try:
        if not isinstance(nvm_dir, str) or not nvm_dir or not validate_node_version(version):
            return None
        base = os.path.normpath(nvm_dir)
        candidate = os.path.join(base, 'versions', 'node', version, 'bin', 'node')
        norm = os.path.normpath(candidate)
        if not norm.startswith(base + os.sep) or '..' in norm.split(os.sep):
            return None
        return candidate
    except Exception:
        return None
