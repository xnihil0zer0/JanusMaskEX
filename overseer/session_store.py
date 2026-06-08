"""Deterministic, JSON-backed conversation store for the overseer.

Maps a conversation id -> record::

    {
        "claude_session_id": <str | None>,
        "current_mode":      <str>,
        "unlocked_modes":    <list[str]>,
        "model":             <str>,
        "agent_backend":     <str>,
        "transcript":        <list[dict]>,
    }

Persistence flows exclusively through an EXPLICIT ``store_path`` seam; there is
no real on-disk default location. Turns are stored duck-typed as plain dicts so
this module stays independent of ``overseer.transcript`` (which it must not
import). Stdlib-only and side-effect free beyond reading/writing ``store_path``.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
Record = Dict[str, Any]
PathLike = Union[str, Path]

class SessionStore:
    """A JSON-persisted mapping of conversation id -> conversation record.

    The store is constructed with an explicit ``store_path`` seam; all state is
    persisted to and loaded from that path so that a fresh ``SessionStore`` over
    the same path observes prior mutations.
    """

    def __init__(self, store_path: PathLike) -> None:
        if store_path is None:
            raise ValueError('store_path is required; there is no on-disk default')
        self._store_path: Path = Path(store_path)
        self._data: Dict[str, Record] = self._load()

    def _load(self) -> Dict[str, Record]:
        """Load the backing JSON, treating a missing path as an empty store."""
        if not self._store_path.exists():
            return {}
        with self._store_path.open('r', encoding='utf-8') as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            return {}
        return raw

    def _save(self) -> None:
        """Persist the current in-memory state to ``store_path`` as JSON."""
        parent = self._store_path.parent
        if parent and (not parent.exists()):
            parent.mkdir(parents=True, exist_ok=True)
        with self._store_path.open('w', encoding='utf-8') as fh:
            json.dump(self._data, fh)

    def create(self, cid: str, *, current_mode: str, model: str, agent_backend: str) -> Record:
        """Create and persist a new conversation record, returning it."""
        rec: Record = {'claude_session_id': None, 'current_mode': current_mode, 'unlocked_modes': [], 'model': model, 'agent_backend': agent_backend, 'transcript': []}
        self._data[cid] = rec
        self._save()
        return rec

    def get(self, cid: str) -> Record:
        """Return the stored record for ``cid`` or raise ``KeyError``."""
        return self._data[cid]

    def append_turn(self, cid: str, turn: Dict[str, Any]) -> None:
        """Append a plain-dict turn to the conversation transcript."""
        transcript: List[Dict[str, Any]] = self._data[cid]['transcript']
        transcript.append(turn)
        self._save()

    def set_mode(self, cid: str, mode: str) -> None:
        """Update the current mode for the conversation."""
        self._data[cid]['current_mode'] = mode
        self._save()

    def unlock_mode(self, cid: str, mode: str) -> None:
        """Record a per-session unlock; idempotent (no duplicates)."""
        unlocked: List[str] = self._data[cid]['unlocked_modes']
        if mode not in unlocked:
            unlocked.append(mode)
            self._save()

    def set_model(self, cid: str, model: str) -> None:
        """Update the model for the conversation."""
        self._data[cid]['model'] = model
        self._save()

    def set_session_id(self, cid: str, session_id: Optional[str]) -> None:
        """Update the claude_session_id for the conversation."""
        self._data[cid]['claude_session_id'] = session_id
        self._save()