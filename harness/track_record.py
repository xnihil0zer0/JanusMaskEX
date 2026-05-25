"""Track record initialization and core types for JanusMask."""
from __future__ import annotations
import fcntl
import json
import os
from pathlib import Path
from typing import Any
from harness.state import _default_state_dir, _ensure_paths
from harness.taxonomy import load_meta_task_taxonomy, load_synthesis_target_taxonomy

class TrackRecordError(Exception):
    """Base exception for track record operations."""
    pass

class TrackRecordCorruptError(TrackRecordError):
    """Raised when the track record file contains invalid JSON or unexpected schema."""
    pass

class TrackRecordUnavailable(TrackRecordError):
    """Raised when the track record cannot be consulted (missing, corrupt, or unreadable)."""
    pass

def _track_record_file(state_dir: Path) -> Path:
    raise NotImplementedError

def _lock_file(state_dir: Path) -> Path:
    raise NotImplementedError

def _read_track_record_from_disk(path: Path) -> dict[str, Any]:
    raise NotImplementedError

def _write_track_record_to_disk(path: Path, record: dict[str, Any]) -> None:
    raise NotImplementedError

def init_track_record(state_dir: Path | None=None) -> dict[str, Any]:
    """
    Initialize or update the planner_track_record.json idempotently.
    Reads current taxonomy versions, preserves existing counts, and zeroes new keys.
    """
    raise NotImplementedError

class InvalidAgentError(TrackRecordError):
    """Raised when an invalid agent is specified."""
    pass
from harness.track_record_events import append_track_event
from harness.taxonomy import validate_meta_task_type, validate_synthesis_target_type, UnknownTaxonomyKeyError
from harness.track_record_events import EventValidationError
VALID_AGENTS = frozenset({'claude', 'gemini', 'antigravity'})

def _prepare_and_append(event_type: str, book: str, agent: str, type_key: str, task_id: str, delta: dict[str, int], state_dir: Path | None=None) -> tuple[Path, Path]:
    raise NotImplementedError

def decomposition_event(spec_author: str, task_id: str, meta_task_type: str, attempts_delta: int=1, failures_delta: int=1, state_dir: Path | None=None) -> dict[str, Any]:
    raise NotImplementedError

def refactor_event(spec_author: str, task_id: str, meta_task_type: str, state_dir: Path | None=None) -> dict[str, Any]:
    raise NotImplementedError

def ambiguous_spec_event(spec_author: str, task_id: str, meta_task_type: str, state_dir: Path | None=None) -> dict[str, Any]:
    raise NotImplementedError

def fuzz_round1_fail_event(coder: str, task_id: str, synthesis_target_type: str, state_dir: Path | None=None) -> dict[str, Any]:
    raise NotImplementedError

def ast_rejection_event(coder: str, task_id: str, synthesis_target_type: str, state_dir: Path | None=None) -> dict[str, Any]:
    raise NotImplementedError

def clean_success_event(book: str, agent: str, type_key: str, task_id: str, state_dir: Path | None=None) -> dict[str, Any]:
    raise NotImplementedError

def track_record_tiebreaker(meta_task_type: str, diff_item: Any) -> str:
    """Pick the agent with the lower spec_authorship failure rate for meta_task_type.

    Returns "claude" or "gemini". Ties default to "claude". Raises
    TrackRecordUnavailable if planner_track_record.json is missing or corrupt.
    """
    raise NotImplementedError