"""Deterministic knowledge-graph / store configuration for ngv2.

A typed :class:`Settings` object carrying the SQLite / Chroma store paths, the
embedding-model name, and the two similarity thresholds, plus a module-level
``settings`` singleton.

The durable capability is: typed fields with documented defaults, overridable
by explicit keyword arguments and by ``NGV2_``-prefixed environment variables
with type coercion. Implemented with the standard library only (no pydantic /
pydantic_settings), and fully deterministic -- no wall-clock, network, or
randomness is touched.
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any, Callable, List, Tuple
ENV_PREFIX = 'NGV2_'

def _coerce_str(value: Any) -> str:
    return str(value)

def _coerce_float(value: Any) -> float:
    return float(value)

def _coerce_path(value: Any) -> Path:
    return value if isinstance(value, Path) else Path(value)
_FIELDS: List[Tuple[str, Callable[[Any], Any], Any]] = [('embedding_model', _coerce_str, 'all-MiniLM-L6-v2'), ('similarity_threshold', _coerce_float, 0.82), ('opportunity_match_threshold', _coerce_float, 0.7), ('sqlite_path', _coerce_path, Path('data/ngv2/kg.sqlite')), ('chroma_path', _coerce_path, Path('data/ngv2/chroma'))]

class Settings:
    """Typed, immutable-by-convention knowledge-graph store configuration.

    Resolution order for each field (highest precedence first):

    1. an explicit keyword argument passed to :class:`Settings`,
    2. the matching ``NGV2_<FIELD_NAME>`` environment variable,
    3. the documented default.

    Whatever the source, the raw value is coerced to the field's declared type,
    so string environment values become ``float`` / :class:`~pathlib.Path`
    instances as appropriate.
    """
    embedding_model: str
    similarity_threshold: float
    opportunity_match_threshold: float
    sqlite_path: Path
    chroma_path: Path

    def __init__(self, **overrides: Any) -> None:
        unknown = set(overrides) - {field_name for field_name, _, _ in _FIELDS}
        if unknown:
            raise TypeError('Unexpected Settings field(s): ' + ', '.join(sorted(unknown)))
        for field_name, coerce, default in _FIELDS:
            env_name = ENV_PREFIX + field_name.upper()
            if field_name in overrides:
                raw = overrides[field_name]
            elif env_name in os.environ:
                raw = os.environ[env_name]
            else:
                raw = default
            setattr(self, field_name, coerce(raw))

    def __repr__(self) -> str:
        parts = ['{}={!r}'.format(field_name, getattr(self, field_name)) for field_name, _, _ in _FIELDS]
        return 'Settings({})'.format(', '.join(parts))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Settings):
            return NotImplemented
        return all((getattr(self, field_name) == getattr(other, field_name) for field_name, _, _ in _FIELDS))
settings = Settings()