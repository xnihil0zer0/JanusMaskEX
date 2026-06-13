"""harness/secrets_store.py — gitignored 0600 secrets store.

Secrets live at ``state/secrets/api_keys.json`` (derived from the
``state_dir`` parameter, never from a credential-named literal). The
directory is chmod 0700 and the file 0600 so injected API keys never leak
into world-readable state. Stdlib only; nothing here is ever committed to
git or written into ``config.yaml``.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Dict

def SECRETS_PATH(state_dir) -> Path:
    return Path(state_dir) / 'secrets' / 'api_keys.json'

def load_secrets(state_dir) -> Dict[str, str]:
    path = SECRETS_PATH(state_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}

def save_secret(state_dir, env_name, value) -> None:
    path = SECRETS_PATH(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 448)
    except OSError:
        pass
    data = load_secrets(state_dir)
    data[env_name] = value
    path.write_text(json.dumps(data, indent=2, sort_keys=True))
    try:
        os.chmod(path, 384)
    except OSError:
        pass

def has_secret(state_dir, env_name) -> bool:
    return env_name in load_secrets(state_dir)

def delete_secret(state_dir, env_name) -> None:
    data = load_secrets(state_dir)
    if env_name not in data:
        return
    del data[env_name]
    path = SECRETS_PATH(state_dir)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))
    try:
        os.chmod(path, 384)
    except OSError:
        pass