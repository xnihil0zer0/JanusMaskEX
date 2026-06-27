"""Deterministic atomic JSON state ledger for ngv2.

A flock-guarded read-modify-write over a JSON state file, plus pure dot-path
getters/setters and a ``get``/``set``/``inc`` CLI. The flock and the file paths
are the only external seam and are injected, so the ledger can be driven
entirely against a temporary directory and never touches real orchestrator
state. Standard-library only (json, fcntl, os, pathlib, sys).
"""
from __future__ import annotations
import fcntl
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional, Sequence
__all__ = ['locked_read_modify_write', 'get_nested', 'set_nested', 'main', 'DEFAULT_STATE_PATH', 'DEFAULT_LOCK_PATH']
DEFAULT_STATE_PATH: Path = Path('/tmp/ngv2/state.json')
DEFAULT_LOCK_PATH: Path = Path('/tmp/ngv2/state.lock')

def get_nested(data: dict, dotted: str) -> Any:
    """Return the value at ``dotted`` (e.g. ``'a.b.c'``) within ``data``.

    Returns ``None`` if any key along the path is missing or if traversal
    would descend into a non-dict value.
    """
    current: Any = data
    for part in dotted.split('.'):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current

def set_nested(data: dict, dotted: str, value: Any) -> None:
    """Set the value at ``dotted`` within ``data``, creating intermediate dicts.

    Any non-dict value encountered along the intermediate path is replaced with
    a fresh dict. When ``value`` is a string it is parsed via ``json.loads`` so
    that ``'5'`` becomes ``5`` and ``'true'`` becomes ``True``; an unparseable
    string is stored verbatim. Non-string values are stored as-is.
    """
    parts = dotted.split('.')
    current = data
    for part in parts[:-1]:
        nxt = current.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            current[part] = nxt
        current = nxt
    parsed: Any = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            parsed = value
    current[parts[-1]] = parsed

def _read_state(state_path: Path) -> dict:
    """Load the JSON state, treating missing/empty/corrupt files as empty."""
    try:
        text = state_path.read_text()
    except FileNotFoundError:
        return {}
    if not text.strip():
        return {}
    try:
        loaded = json.loads(text)
    except (ValueError, TypeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}

def _atomic_write(state_path: Path, state: dict) -> None:
    """Serialize ``state`` to a sibling temp file, fsync, then atomically replace.

    A crash between the temp write and the replace leaves the prior ledger file
    untouched, so the on-disk state is never partially written.
    """
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.parent / (state_path.name + '.tmp')
    with open(tmp_path, 'w', encoding='utf-8') as handle:
        json.dump(state, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, state_path)

def locked_read_modify_write(modifier: Callable[[dict], dict], *, state_path: Path=DEFAULT_STATE_PATH, lock_path: Path=DEFAULT_LOCK_PATH) -> dict:
    """Run ``modifier`` over the current state under an exclusive flock.

    The lock parent directory is created, an exclusive ``flock`` is taken for
    the whole read-modify-write, the modified state is written atomically, and
    the lock is always released (even on error) via ``try/finally``.
    """
    state_path = Path(state_path)
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = open(lock_path, 'w', encoding='utf-8')
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        state = _read_state(state_path)
        new_state = modifier(state)
        _atomic_write(state_path, new_state)
        return new_state
    finally:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        finally:
            lock_handle.close()

def main(argv: Optional[Sequence[str]]=None, *, state_path: Path=DEFAULT_STATE_PATH, lock_path: Path=DEFAULT_LOCK_PATH) -> int:
    """``get``/``set``/``inc`` CLI over the JSON ledger; returns an exit code."""
    if argv is None:
        argv = sys.argv[1:]
    argv = list(argv)
    if not argv:
        print('usage: state_ledger {get|set|inc} <dot.path> [value]', file=sys.stderr)
        return 2
    verb, rest = (argv[0], argv[1:])
    if verb == 'get':
        if len(rest) < 1:
            print('usage: state_ledger get <dot.path>', file=sys.stderr)
            return 2
        state = _read_state(Path(state_path))
        print(get_nested(state, rest[0]))
        return 0
    if verb == 'set':
        if len(rest) < 2:
            print('usage: state_ledger set <dot.path> <value>', file=sys.stderr)
            return 2
        dotted, value = (rest[0], rest[1])

        def _set(state: dict) -> dict:
            set_nested(state, dotted, value)
            return state
        locked_read_modify_write(_set, state_path=state_path, lock_path=lock_path)
        return 0
    if verb == 'inc':
        if len(rest) < 1:
            print('usage: state_ledger inc <dot.path> [amount]', file=sys.stderr)
            return 2
        dotted = rest[0]
        amount = int(rest[1]) if len(rest) > 1 else 1

        def _inc(state: dict) -> dict:
            current = get_nested(state, dotted)
            base = current if isinstance(current, (int, float)) else 0
            set_nested(state, dotted, str(base + amount))
            return state
        locked_read_modify_write(_inc, state_path=state_path, lock_path=lock_path)
        return 0
    print(f'unknown verb: {verb}', file=sys.stderr)
    return 2
if __name__ == '__main__':
    raise SystemExit(main())