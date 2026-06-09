"""Durable candidate population store for the autocompiler.

Mirrors the durable-JSON-state pattern of ``overseer/procedure_state.py``:
a JSON-serializable :class:`Candidate` record and a :class:`PopulationDB`
that round-trips candidates as JSON under an injected ``state_dir``.

Standard library only. No process/model/network I/O -- all filesystem
access is confined to the injected ``state_dir``.
"""
from __future__ import annotations
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union
__all__ = ['Candidate', 'PopulationDB']
_STORE_NAME = 'population.json'

@dataclass
class Candidate:
    """A single candidate program in the population.

    Attributes:
        id: Stable identifier for the candidate.
        code: The primary source of the candidate.
        files: Mapping of repo-relative path -> file source.
        fitness: Arbitrary JSON-serializable fitness payload.
        elo: Current Elo rating of the candidate.
        n_selected: Visit count -- number of times the candidate was selected.
        parent_ids: Identifiers of the candidate's parents (lineage).
    """
    id: str
    code: str
    files: Dict[str, str] = field(default_factory=dict)
    fitness: Dict = field(default_factory=dict)
    elo: float = 1200.0
    n_selected: int = 0
    parent_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        """Return a JSON-serializable dict representation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'Candidate':
        """Reconstruct a :class:`Candidate` from a plain dict.

        Unknown keys are ignored and missing keys fall back to the
        dataclass defaults so that loading tolerates schema drift.
        """
        return cls(id=data['id'], code=data.get('code', ''), files=dict(data.get('files') or {}), fitness=dict(data.get('fitness') or {}), elo=float(data.get('elo', 1200.0)), n_selected=int(data.get('n_selected', 0)), parent_ids=list(data.get('parent_ids') or []))

class PopulationDB:
    """A persistent, in-memory store of :class:`Candidate` records.

    Candidates are held in memory and persisted as a single JSON file
    (:data:`_STORE_NAME`) under the injected ``state_dir`` via :meth:`save`.
    :meth:`load` restores the state, yielding an empty DB when the store is
    absent or corrupted rather than raising.
    """

    def __init__(self, state_dir: Union[str, Path]) -> None:
        self.state_dir = Path(state_dir)
        self._candidates: Dict[str, Candidate] = {}

    def add(self, candidate: Candidate) -> None:
        """Insert or replace ``candidate`` keyed by its ``id``."""
        self._candidates[candidate.id] = candidate

    def get(self, candidate_id: str) -> Optional[Candidate]:
        """Return the candidate with ``candidate_id`` or ``None``."""
        return self._candidates.get(candidate_id)

    def candidates(self) -> List[Candidate]:
        """Return all stored candidates as a list."""
        return list(self._candidates.values())

    def __len__(self) -> int:
        return len(self._candidates)

    def __contains__(self, candidate_id: object) -> bool:
        return candidate_id in self._candidates

    @property
    def _store_path(self) -> Path:
        return self.state_dir / _STORE_NAME

    def save(self) -> None:
        """Persist the population as JSON under the injected ``state_dir``."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        payload = {'candidates': [c.to_dict() for c in self._candidates.values()]}
        tmp_path = self._store_path.with_suffix('.json.tmp')
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp_path.replace(self._store_path)

    @classmethod
    def load(cls, state_dir: Union[str, Path]) -> 'PopulationDB':
        """Restore a :class:`PopulationDB` from ``state_dir``.

        A missing directory/file or corrupted JSON yields an empty DB
        instead of raising.
        """
        db = cls(state_dir)
        store_path = db._store_path
        try:
            raw = store_path.read_text()
        except (OSError, ValueError):
            return db
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return db
        records = data.get('candidates') if isinstance(data, dict) else data
        if not isinstance(records, list):
            return db
        for record in records:
            if not isinstance(record, dict):
                continue
            try:
                candidate = Candidate.from_dict(record)
            except (KeyError, TypeError, ValueError):
                continue
            db._candidates[candidate.id] = candidate
        return db