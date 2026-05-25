"""Track record initialization and core types for JanusMask."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import Any

from harness.state import _default_state_dir, _ensure_paths
from harness.taxonomy import (
    load_meta_task_taxonomy,
    load_synthesis_target_taxonomy,
)


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
    return state_dir / "planner_track_record.json"


def _lock_file(state_dir: Path) -> Path:
    return state_dir / "track_record.lock"


def _read_track_record_from_disk(path: Path) -> dict[str, Any]:
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Track record root is not a JSON object")
        return data
    except (json.JSONDecodeError, ValueError) as exc:
        raise TrackRecordCorruptError(
            f"Corrupt track record file at {path}: {exc}"
        ) from exc


def _write_track_record_to_disk(path: Path, record: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(".json.tmp")
    with open(tmp_path, "w") as f:
        json.dump(record, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    tmp_path.replace(path)


def init_track_record(state_dir: Path | None = None) -> dict[str, Any]:
    """
    Initialize or update the planner_track_record.json idempotently.
    Reads current taxonomy versions, preserves existing counts, and zeroes new keys.
    """
    state_dir = state_dir or _default_state_dir()
    _ensure_paths(state_dir)
    lock_path = _lock_file(state_dir)
    record_path = _track_record_file(state_dir)

    with open(lock_path, "a") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            # 1. Load taxonomy and get versions/keys
            meta_tax = load_meta_task_taxonomy(state_dir)
            synth_tax = load_synthesis_target_taxonomy(state_dir)

            meta_version = meta_tax["version"]
            synth_version = synth_tax["version"]
            meta_keys = frozenset(meta_tax["keys"].keys())
            synth_keys = frozenset(synth_tax["keys"].keys())

            # 2. Read existing record or create new
            if record_path.exists():
                record = _read_track_record_from_disk(record_path)
            else:
                record = {
                    "version": 1,
                    "spec_authorship": {},
                    "synthesis": {},
                }
            
            # 3. Update taxonomy versions
            record["meta_task_taxonomy_version"] = meta_version
            record["synthesis_target_taxonomy_version"] = synth_version

            if "spec_authorship" not in record:
                record["spec_authorship"] = {}
            if "synthesis" not in record:
                record["synthesis"] = {}

            agents = ["claude", "gemini", "antigravity"]

            # 4. Fill missing agents and keys
            for agent in agents:
                # spec_authorship uses meta_task keys
                if agent not in record["spec_authorship"]:
                    record["spec_authorship"][agent] = {}
                for mk in meta_keys:
                    if mk not in record["spec_authorship"][agent]:
                        record["spec_authorship"][agent][mk] = {"failures": 0, "attempts": 0}
                
                # synthesis uses synthesis_target keys
                if agent not in record["synthesis"]:
                    record["synthesis"][agent] = {}
                for sk in synth_keys:
                    if sk not in record["synthesis"][agent]:
                        record["synthesis"][agent][sk] = {"failures": 0, "attempts": 0}

            _write_track_record_to_disk(record_path, record)

        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)

    return record


class InvalidAgentError(TrackRecordError):
    """Raised when an invalid agent is specified."""
    pass

from harness.track_record_events import append_track_event
from harness.taxonomy import validate_meta_task_type, validate_synthesis_target_type, UnknownTaxonomyKeyError
from harness.track_record_events import EventValidationError

VALID_AGENTS = frozenset({"claude", "gemini", "antigravity"})

def _prepare_and_append(
    event_type: str,
    book: str,
    agent: str,
    type_key: str,
    task_id: str,
    delta: dict[str, int],
    state_dir: Path | None = None,
) -> tuple[Path, Path]:
    if agent not in VALID_AGENTS:
        raise InvalidAgentError(f"Invalid agent: {agent}")
    
    if book == "spec_authorship":
        validate_meta_task_type(type_key)
    else:
        validate_synthesis_target_type(type_key)

    state_dir = state_dir or _default_state_dir()
    _ensure_paths(state_dir)
    record_path = _track_record_file(state_dir)
    lock_path = _lock_file(state_dir)
    
    if not record_path.exists():
        init_track_record(state_dir)

    return lock_path, record_path

def decomposition_event(spec_author: str, task_id: str, meta_task_type: str, attempts_delta: int = 1, failures_delta: int = 1, state_dir: Path | None = None) -> dict[str, Any]:
    delta = {"failures": failures_delta, "attempts": attempts_delta}
    lock_path, record_path = _prepare_and_append("decomposition", "spec_authorship", spec_author, meta_task_type, task_id, delta, state_dir)
    
    with open(lock_path, "a") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            event = append_track_event("decomposition", "spec_authorship", spec_author, meta_task_type, task_id, delta, state_dir, _skip_lock=True)
            record = _read_track_record_from_disk(record_path)
            cell = record.setdefault("spec_authorship", {}).setdefault(spec_author, {}).setdefault(meta_task_type, {"failures": 0, "attempts": 0})
            
            cell["failures"] += failures_delta
            cell["attempts"] += attempts_delta  # DEFERRED_WIRING: attempts_not_consumed
            
            _write_track_record_to_disk(record_path, record)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    return event

def refactor_event(spec_author: str, task_id: str, meta_task_type: str, state_dir: Path | None = None) -> dict[str, Any]:
    delta = {"failures": 1, "attempts": 1}
    lock_path, record_path = _prepare_and_append("refactor", "spec_authorship", spec_author, meta_task_type, task_id, delta, state_dir)
    
    with open(lock_path, "a") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            event = append_track_event("refactor", "spec_authorship", spec_author, meta_task_type, task_id, delta, state_dir, _skip_lock=True)
            record = _read_track_record_from_disk(record_path)
            cell = record.setdefault("spec_authorship", {}).setdefault(spec_author, {}).setdefault(meta_task_type, {"failures": 0, "attempts": 0})
            
            cell["failures"] += 1
            cell["attempts"] += 1  # DEFERRED_WIRING: attempts_not_consumed
            
            _write_track_record_to_disk(record_path, record)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    return event

def ambiguous_spec_event(spec_author: str, task_id: str, meta_task_type: str, state_dir: Path | None = None) -> dict[str, Any]:
    delta = {"failures": 1, "attempts": 1}
    lock_path, record_path = _prepare_and_append("ambiguous_spec", "spec_authorship", spec_author, meta_task_type, task_id, delta, state_dir)
    
    with open(lock_path, "a") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            event = append_track_event("ambiguous_spec", "spec_authorship", spec_author, meta_task_type, task_id, delta, state_dir, _skip_lock=True)
            record = _read_track_record_from_disk(record_path)
            cell = record.setdefault("spec_authorship", {}).setdefault(spec_author, {}).setdefault(meta_task_type, {"failures": 0, "attempts": 0})
            
            cell["failures"] += 1  # DEFERRED_WIRING: ambiguous_folded_into_failures
            cell["attempts"] += 1  # DEFERRED_WIRING: attempts_not_consumed
            
            _write_track_record_to_disk(record_path, record)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    return event

def fuzz_round1_fail_event(coder: str, task_id: str, synthesis_target_type: str, state_dir: Path | None = None) -> dict[str, Any]:
    delta = {"failures": 1, "attempts": 1}
    lock_path, record_path = _prepare_and_append("fuzz_round1_fail", "synthesis", coder, synthesis_target_type, task_id, delta, state_dir)
    
    with open(lock_path, "a") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            event = append_track_event("fuzz_round1_fail", "synthesis", coder, synthesis_target_type, task_id, delta, state_dir, _skip_lock=True)
            record = _read_track_record_from_disk(record_path)
            cell = record.setdefault("synthesis", {}).setdefault(coder, {}).setdefault(synthesis_target_type, {"failures": 0, "attempts": 0})
            
            cell["failures"] += 1
            cell["attempts"] += 1  # DEFERRED_WIRING: attempts_not_consumed
            
            _write_track_record_to_disk(record_path, record)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    return event

def ast_rejection_event(coder: str, task_id: str, synthesis_target_type: str, state_dir: Path | None = None) -> dict[str, Any]:
    delta = {"failures": 1, "attempts": 1}
    lock_path, record_path = _prepare_and_append("ast_rejection", "synthesis", coder, synthesis_target_type, task_id, delta, state_dir)
    
    with open(lock_path, "a") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            event = append_track_event("ast_rejection", "synthesis", coder, synthesis_target_type, task_id, delta, state_dir, _skip_lock=True)
            record = _read_track_record_from_disk(record_path)
            cell = record.setdefault("synthesis", {}).setdefault(coder, {}).setdefault(synthesis_target_type, {"failures": 0, "attempts": 0})
            
            cell["failures"] += 1
            cell["attempts"] += 1  # DEFERRED_WIRING: attempts_not_consumed
            
            _write_track_record_to_disk(record_path, record)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    return event

def clean_success_event(book: str, agent: str, type_key: str, task_id: str, state_dir: Path | None = None) -> dict[str, Any]:
    delta = {"failures": 0, "attempts": 1}
    lock_path, record_path = _prepare_and_append("clean_success", book, agent, type_key, task_id, delta, state_dir)

    with open(lock_path, "a") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            event = append_track_event("clean_success", book, agent, type_key, task_id, delta, state_dir, _skip_lock=True)
            record = _read_track_record_from_disk(record_path)
            cell = record.setdefault(book, {}).setdefault(agent, {}).setdefault(type_key, {"failures": 0, "attempts": 0})

            # clean_success never increments failures
            cell["attempts"] += 1  # DEFERRED_WIRING: attempts_not_consumed

            _write_track_record_to_disk(record_path, record)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    return event


def track_record_tiebreaker(meta_task_type: str, diff_item: Any) -> str:
    """Pick the agent with the lower spec_authorship failure rate for meta_task_type.

    Returns "claude" or "gemini". Ties default to "claude". Raises
    TrackRecordUnavailable if planner_track_record.json is missing or corrupt.
    """
    state_dir = _default_state_dir()
    record_path = _track_record_file(state_dir)
    if not record_path.exists():
        raise TrackRecordUnavailable(f"Track record file not found at {record_path}")
    try:
        record = _read_track_record_from_disk(record_path)
    except TrackRecordCorruptError as exc:
        raise TrackRecordUnavailable(f"Track record corrupt: {exc}") from exc

    spec_auth = record.get("spec_authorship", {})

    def _rate(agent: str) -> float:
        cell = spec_auth.get(agent, {}).get(meta_task_type, {})
        attempts = cell.get("attempts", 0)
        failures = cell.get("failures", 0)
        return failures / attempts if attempts > 0 else 0.0

    return "gemini" if _rate("gemini") < _rate("claude") else "claude"

