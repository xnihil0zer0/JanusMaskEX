"""Append-only event log writer for JanusMask."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from harness._journal import write_jsonl_row
from harness.state import _default_state_dir
from harness.taxonomy import validate_meta_task_type, validate_synthesis_target_type, UnknownTaxonomyKeyError
try:
    import ulid
    HAS_ULID = True
except ImportError:
    HAS_ULID = False
VALID_EVENT_TYPES = frozenset({'decomposition', 'refactor', 'ambiguous_spec', 'fuzz_round1_fail', 'ast_rejection', 'clean_success'})
VALID_BOOKS = frozenset({'spec_authorship', 'synthesis'})
VALID_AGENTS = frozenset({'claude', 'gemini', 'antigravity'})

class EventValidationError(ValueError):
    """Raised when an event has invalid fields."""
    pass

class EventLogCorruptError(Exception):
    """Raised when the event log contains malformed or partial lines."""
    pass

def _event_log_file(state_dir: Path) -> Path:
    raise NotImplementedError

def _lock_file(state_dir: Path) -> Path:
    raise NotImplementedError

def append_track_event(event_type: str, book: str, agent: str, type: str, task_id: str, delta: dict[str, int], state_dir: Path | None=None, _skip_lock: bool=False) -> dict[str, Any]:
    raise NotImplementedError

def read_events(state_dir: Path | None=None) -> list[dict[str, Any]]:
    raise NotImplementedError