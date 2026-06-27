"""ngv2/verdict_store.py — append-only hunt-verdict persistence.

Closes the learn -> hunt -> verdict -> re-learn loop by persisting hunt
verdicts append-only to a JSON store (``data/ngv2/hunt_verdicts.json``).

Stdlib-only; no network, clock, or randomness dependencies.
"""
from __future__ import annotations
import json
import os

def load_verdicts(path: str) -> list[dict]:
    """Return all stored verdicts in insertion order.

    A missing (or empty) file loads as ``[]`` rather than raising.
    """
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as handle:
        text = handle.read()
    if not text.strip():
        return []
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError('verdict store must contain a JSON array of verdicts')
    return data

def append_verdict(path: str, verdict: dict) -> None:
    """Append one verdict to the JSON store at ``path``.

    Append-only: existing entries are never truncated or rewritten; their
    order is preserved. The file (and any missing parent directories) is
    created on first write.
    """
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    verdicts = load_verdicts(path)
    verdicts.append(verdict)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(verdicts, handle, ensure_ascii=False, indent=2)