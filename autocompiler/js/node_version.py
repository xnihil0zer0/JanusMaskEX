"""Autocompiler pinned-Node resolver (Phase B).

Pure, stdlib-only resolution of the EXACT pinned Node binary under an nvm tree.
The resolved path is the only path the later owner-gated jail mount (Phase D)
ever binds -- never the global ``~/.nvm`` tree -- so version strings are
validated strictly and path-escaping ``.nvmrc`` content can never become a
path component.

Exposes:

- ``validate_node_version(version) -> bool`` -- True ONLY for a str fully
  matching ``^v\\d+\\.\\d+\\.\\d+$``.
- ``parse_nvmrc(content) -> str | None`` -- strips surrounding whitespace and
  returns the version iff it validates, else None.
- ``resolve_node_bin(nvm_dir, version) -> str | None`` -- exactly
  ``<nvm_dir>/versions/node/<version>/bin/node`` when ``version`` validates and
  the joined result still normalizes strictly under ``nvm_dir``, else None.

All three functions are total (never raise).
"""
from __future__ import annotations
import os
import re
_VERSION_RE = re.compile('^v\\d+\\.\\d+\\.\\d+$')

def validate_node_version(version: object) -> bool:
    """Return True iff ``version`` is a str fully matching ^v\\d+\\.\\d+\\.\\d+$."""
    try:
        return isinstance(version, str) and bool(_VERSION_RE.fullmatch(version))
    except Exception:
        return False

def parse_nvmrc(content: object) -> str | None:
    """Strip surrounding whitespace and return the version iff it validates."""
    try:
        if not isinstance(content, str):
            return None
        stripped = content.strip()
        if validate_node_version(stripped):
            return stripped
        return None
    except Exception:
        return None

def resolve_node_bin(nvm_dir: object, version: object) -> str | None:
    """Return the exact pinned Node binary path under ``nvm_dir`` or None."""
    try:
        if not isinstance(nvm_dir, str) or not nvm_dir:
            return None
        if not validate_node_version(version):
            return None
        base = os.path.normpath(nvm_dir)
        candidate = os.path.join(base, 'versions', 'node', version, 'bin', 'node')
        norm = os.path.normpath(candidate)
        if not norm.startswith(base + os.sep):
            return None
        if '..' in norm.split(os.sep):
            return None
        return candidate
    except Exception:
        return None