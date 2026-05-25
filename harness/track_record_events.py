"""Append-only event log writer for JanusMask."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness._journal import write_jsonl_row
from harness.state import _default_state_dir
from harness.taxonomy import (
    validate_meta_task_type,
    validate_synthesis_target_type,
    UnknownTaxonomyKeyError,
)

try:
    import ulid
    HAS_ULID = True
except ImportError:
    HAS_ULID = False

VALID_EVENT_TYPES = frozenset({
    "decomposition",
    "refactor",
    "ambiguous_spec",
    "fuzz_round1_fail",
    "ast_rejection",
    "clean_success",
})

VALID_BOOKS = frozenset({"spec_authorship", "synthesis"})
VALID_AGENTS = frozenset({"claude", "gemini", "antigravity"})


class EventValidationError(ValueError):
    """Raised when an event has invalid fields."""
    pass


class EventLogCorruptError(Exception):
    """Raised when the event log contains malformed or partial lines."""
    pass


def _event_log_file(state_dir: Path) -> Path:
    return state_dir / "track_record_events.jsonl"


def _lock_file(state_dir: Path) -> Path:
    return state_dir / "track_record.lock"


def append_track_event(
    event_type: str,
    book: str,
    agent: str,
    type: str,
    task_id: str,
    delta: dict[str, int],
    state_dir: Path | None = None,
    _skip_lock: bool = False,
) -> dict[str, Any]:
    if event_type not in VALID_EVENT_TYPES:
        raise EventValidationError(f"Invalid event_type: {event_type}")
    if book not in VALID_BOOKS:
        raise EventValidationError(f"Invalid book: {book}")
    if agent not in VALID_AGENTS:
        raise EventValidationError(f"Invalid agent: {agent}")

    try:
        if book == "spec_authorship":
            validate_meta_task_type(type)
        else:
            validate_synthesis_target_type(type)
    except UnknownTaxonomyKeyError as e:
        raise EventValidationError(f"Invalid type for book '{book}': {type}") from e

    if "failures" not in delta or "attempts" not in delta:
        raise EventValidationError("delta must contain 'failures' and 'attempts' keys")

    state_dir = state_dir or _default_state_dir()
    log_path = _event_log_file(state_dir)
    lock_path = _lock_file(state_dir)

    if HAS_ULID:
        event_id = str(ulid.new())
    else:
        event_id = uuid.uuid4().hex

    event = {
        "event_id": event_id,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event_type": event_type,
        "book": book,
        "agent": agent,
        "type": type,
        "task_id": task_id,
        "delta": delta,
        "reversed": False,
        "reversal_reason": None,
    }

    write_jsonl_row(
        log_path,
        event,
        lock_path=None if _skip_lock else lock_path,
    )
    return event


def read_events(state_dir: Path | None = None) -> list[dict[str, Any]]:
    state_dir = state_dir or _default_state_dir()
    log_path = _event_log_file(state_dir)

    if not log_path.exists():
        return []

    events = []
    with open(log_path, "r") as f:
        for i, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise EventLogCorruptError(f"Corrupt event log at line {i}: {e}") from e

    return events
