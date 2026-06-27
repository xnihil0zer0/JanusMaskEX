"""Deterministic, flock-protected JSON run-state updater (ngv2.state_update).

A clean-room distillation of the legacy ``services/state_update.py``. This is
the one and only durable read/modify/write path for the run-state document.

Design notes
------------
* Pure standard library only (``json`` / ``fcntl`` / ``os`` / ``pathlib``).
* No network, clock, randomness, subprocess, or LLM use.
* The only impurity is an INJECTED ``state_path`` file-path seam; no run-state
  path is hard-coded into the read/modify/write logic. ``STATE_FILE`` and
  ``LOCK_FILE`` are merely the default on-disk locations callers may opt into.
* Every durable read and write is serialized by an advisory ``fcntl.flock``
  acquired on the open file handle and always released in a ``finally`` block,
  so a failing modifier or JSON step never leaks the lock.
* Imports nothing from sibling Epic-4 leaves or any super-epic leaf, and
  exports nothing those siblings consume -- a self-contained persistence leaf.
"""
from __future__ import annotations
import fcntl
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Union
STATE_FILE: Path = Path('/var/run/ngv2/run_state.json')
LOCK_FILE: Path = Path('/var/run/ngv2/run_state.lock')
PathLike = Union[str, 'os.PathLike[str]', Path]

def get_nested(d: Dict[str, Any], path: str) -> Any:
    """Walk ``path`` (dot-separated) through nested dicts.

    Returns the value at the path, or ``None`` if any key along the way is
    missing or an intermediate value is not a dict. Never raises.
    """
    current: Any = d
    for part in path.split('.'):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current

def set_nested(d: Dict[str, Any], path: str, value: Any) -> None:
    """Set ``value`` at ``path`` (dot-separated), mutating ``d`` in place.

    Intermediate dicts are created as needed; a non-dict value blocking the
    path is overwritten with a fresh dict. Returns ``None``.
    """
    parts = path.split('.')
    current: Dict[str, Any] = d
    for part in parts[:-1]:
        nxt = current.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            current[part] = nxt
        current = nxt
    current[parts[-1]] = value

def _load_state(handle) -> Dict[str, Any]:
    """Read and JSON-decode the open handle; empty/malformed yields ``{}``."""
    handle.seek(0)
    raw = handle.read()
    if not raw.strip():
        return {}
    try:
        loaded = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    return loaded

def locked_read_modify_write(modifier: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]], state_path: PathLike=STATE_FILE) -> Dict[str, Any]:
    """Atomically read, modify, and write the run-state JSON document.

    The document is loaded from ``state_path`` (a missing or empty/malformed
    file is treated as an empty dict), passed to ``modifier``, and the result
    is JSON-encoded back to ``state_path``. The whole sequence is serialized by
    an exclusive ``fcntl.flock`` on the file handle, always released in a
    ``finally`` block. If ``modifier`` raises, the on-disk file is left
    untouched and the exception propagates.

    Returns the resulting in-memory document.
    """
    sp = Path(os.fspath(state_path))
    sp.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(sp), os.O_RDWR | os.O_CREAT, 420)
    handle = os.fdopen(fd, 'r+')
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        state = _load_state(handle)
        new_state = modifier(state)
        if new_state is None:
            new_state = state
        encoded = json.dumps(new_state)
        handle.seek(0)
        handle.truncate()
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
        return new_state
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

def _coerce_value(raw: str) -> Any:
    """Parse ``raw`` as JSON, falling back to the literal string."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw

def main(argv: Sequence[str], state_path: PathLike=STATE_FILE) -> Any:
    """Dispatch ``set`` / ``inc`` / ``get`` against the run-state document.

    * ``set <dot.path> <value>`` -- JSON-coerce ``value`` and store it; ``0``.
    * ``inc <dot.path> [amount]`` -- add integer ``amount`` (default 1) to the
      (integer, default 0) value at the path; writes a real ``int``; ``0``.
    * ``get <dot.path>`` -- return the value at the path (or ``None``).

    Malformed / too-few-argument invocations return a non-zero ``int`` rather
    than raising.
    """
    if not argv:
        return 2
    command = argv[0]
    if command == 'set':
        if len(argv) < 3:
            return 2
        target = argv[1]
        value = _coerce_value(argv[2])

        def _apply_set(state: Dict[str, Any]) -> Dict[str, Any]:
            set_nested(state, target, value)
            return state
        locked_read_modify_write(_apply_set, state_path=state_path)
        return 0
    if command == 'inc':
        if len(argv) < 2:
            return 2
        target = argv[1]
        amount = 1
        if len(argv) >= 3:
            try:
                amount = int(argv[2])
            except (TypeError, ValueError):
                return 2

        def _apply_inc(state: Dict[str, Any]) -> Dict[str, Any]:
            current = get_nested(state, target)
            if not isinstance(current, int) or isinstance(current, bool):
                current = 0
            set_nested(state, target, current + amount)
            return state
        locked_read_modify_write(_apply_inc, state_path=state_path)
        return 0
    if command == 'get':
        if len(argv) < 2:
            return 2
        target = argv[1]
        state = locked_read_modify_write(lambda s: s, state_path=state_path)
        return get_nested(state, target)
    return 2