"""Fail-closed flag reader for the ``autocompiler:`` config subtree.

Pure, stdlib-only, side-effect-free. Clones the fail-closed gate idiom
(``_wire_up_gate_enabled``) plus the ``_reap_spent_briefs_safe`` try/except
bridge: the entire read + parse + lookup body is wrapped in a broad
try/except that collapses every error path to ``False``.

``ac_enabled(key, state_dir=None, config=None) -> bool`` returns ``True``
ONLY when the master gate ``autocompiler.enabled`` is the Python bool
``True`` AND the (possibly dotted) ``key`` resolves to the Python bool
``True`` under the ``autocompiler:`` subtree. Any missing key / missing
subtree / non-bool value / parse error / internal exception => ``False``.
The function NEVER raises.
"""
from __future__ import annotations
import os
from typing import Any, Optional

def _default_state_dir() -> str:
    """Deterministic config home used when ``state_dir`` is not injected."""
    return os.environ.get('AC_STATE_DIR') or os.getcwd()

def load_config(state_dir: Optional[str]=None) -> dict:
    """Read the ``autocompiler:`` config subtree via plain filesystem reads.

    Module-level so tests can monkeypatch it to inject failures. Returns an
    empty dict (never raises) when the config file/subtree is absent or the
    content cannot be parsed -- the caller still treats that as fail-closed.
    """
    if state_dir is None:
        state_dir = _default_state_dir()
    path = os.path.join(str(state_dir), 'config', 'autocompiler.yaml')
    if not os.path.isfile(path):
        return {}
    with open(path, 'r', encoding='utf-8') as fh:
        raw = fh.read()
    data: Any = None
    try:
        import yaml
        data = yaml.safe_load(raw)
    except Exception:
        try:
            import json
            data = json.loads(raw)
        except Exception:
            return {}
    return data if isinstance(data, dict) else {}

def ac_enabled(key: str, state_dir=None, config=None) -> bool:
    """Fail-closed resolver for an ``autocompiler:`` boolean flag.

    True iff the master gate is exactly ``True`` and ``key`` resolves to the
    Python bool ``True`` under the subtree. Any error / missing key / non-bool
    value => False. Never raises.
    """
    try:
        if config is None:
            config = load_config(state_dir)
        if not isinstance(config, dict):
            return False
        subtree = config.get('autocompiler')
        if not isinstance(subtree, dict):
            return False
        if subtree.get('enabled') is not True:
            return False
        if not isinstance(key, str) or not key:
            return False
        node: Any = subtree
        for part in key.split('.'):
            if not isinstance(node, dict) or part not in node:
                return False
            node = node[part]
        return node is True
    except Exception:
        return False