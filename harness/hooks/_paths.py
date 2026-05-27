"""Env resolution + safe_subpath wrapper for hook scripts.

The orchestrator seeds these env vars on the worker process:
    JANUSMASK_AGENT      claude|gemini
    JANUSMASK_STATE_DIR  absolute path to state/
    JANUSMASK_MODE       synthesis|planning|reconciliation
    JANUSMASK_ROUND      integer (overrides STATE.json.round per P0.4)
    JANUSMASK_PROJECT_DIR  absolute repo root

Hooks must never trust agent-supplied paths. `safe_subpath` re-exports
`harness.safe_subpath.is_safe_subpath` unchanged — this module only adds
the convenience of rooting against the authoritative state/project dirs.
"""
from __future__ import annotations
import json
import os
import pathlib
from typing import Any
from harness.safe_subpath import is_safe_subpath
_DEFAULT_PROJECT_DIR = pathlib.Path(__file__).resolve().parent.parent.parent

def project_dir() -> pathlib.Path:
    raw = os.environ.get('JANUSMASK_PROJECT_DIR') or os.environ.get('CLAUDE_PROJECT_DIR')
    if raw:
        return pathlib.Path(raw).resolve()
    return _DEFAULT_PROJECT_DIR

def state_dir() -> pathlib.Path:
    raw = os.environ.get('JANUSMASK_STATE_DIR')
    if raw:
        return pathlib.Path(raw).resolve()
    return project_dir() / 'state'

def agent() -> str:
    return os.environ.get('JANUSMASK_AGENT', '')

def mode() -> str:
    return os.environ.get('JANUSMASK_MODE', 'synthesis')

def round_number() -> int:
    """Prefer JANUSMASK_ROUND env (authoritative post-P0.4), else -1 sentinel.

    Callers that also need to consult STATE.json should use
    `_state_gates.current_round` which layers env -> STATE.json fallback.
    """
    raw = os.environ.get('JANUSMASK_ROUND')
    if raw is None or raw == '':
        return -1
    try:
        return int(raw)
    except ValueError:
        return -1

def safe_under_state(candidate: str) -> bool:
    """True iff `candidate` resolves inside the state dir."""
    return is_safe_subpath(str(candidate), str(state_dir()))

def safe_under_project(candidate: str) -> bool:
    """True iff `candidate` resolves inside the project root."""
    return is_safe_subpath(str(candidate), str(project_dir()))

def load_inbox_task(inbox_dir: pathlib.Path) -> dict[str, Any]:
    """Read ``<inbox_dir>/task.json`` and return the parsed dict.

    Returns ``{}`` when the file is missing, unreadable, or contains
    malformed JSON — callers downstream expect a dict and derive their
    own defaults (``task_id="default"`` etc.) from the empty result.

    ``inbox_dir`` is supplied by the caller (typically the agent's
    ``_env.inbox_dir(session_id)``) so this hoist stays agent-agnostic
    and avoids an otherwise-circular import on the per-agent ``_env``.
    """
    task_path = inbox_dir / 'task.json'
    try:
        return json.loads(task_path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def load_self_healing_history(state_dir: pathlib.Path) -> list[dict[str, Any]]:
    """Read state/control/autowork/self_healing_history.jsonl line by line.

    Skipping blank or malformed lines, and returns [] when the file is absent
    or unreadable.
    """
    file_path = state_dir / "state" / "control" / "autowork" / "self_healing_history.jsonl"
    if not file_path.is_file():
        alt_path = state_dir / "control" / "autowork" / "self_healing_history.jsonl"
        if alt_path.is_file():
            file_path = alt_path

    try:
        if not file_path.exists():
            return []
    except OSError:
        return []

    records: list[dict[str, Any]] = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    data = json.loads(stripped)
                    if isinstance(data, dict):
                        records.append(data)
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
    except OSError:
        return []
    return records


def matching_history_records(records: list[dict[str, Any]], files_touched: list[str]) -> list[dict[str, Any]]:
    """Return the records whose files_touched share at least one path string.

    Preserves input order.
    """
    query_set = {str(f) for f in files_touched if f is not None} if files_touched else set()
    if not query_set:
        return []

    matched: list[dict[str, Any]] = []
    for record in records:
        rec_files = record.get("files_touched")
        if rec_files is None:
            coerced = []
        elif isinstance(rec_files, str):
            coerced = [rec_files]
        elif isinstance(rec_files, list):
            coerced = rec_files
        else:
            try:
                coerced = list(rec_files)
            except TypeError:
                coerced = []

        coerced_str_set = {str(item) for item in coerced if item is not None}
        if coerced_str_set.intersection(query_set):
            matched.append(record)

    return matched


def format_self_healing_section(matches: list[dict[str, Any]]) -> str:
    """Format matching self-healing records into an agent-facing section string.

    Returns '' when matches is empty.
    """
    if not matches:
        return ''

    from datetime import datetime

    lines = ['--- RECENT SELF-HEALING HISTORY FOR RELATED COMPONENTS ---']
    for record in matches:
        ts_val = record.get('ts')
        iso_ts = 'unknown-time'
        if ts_val is not None:
            try:
                iso_ts = datetime.fromtimestamp(float(ts_val)).isoformat()
            except (ValueError, TypeError):
                pass

        task_id = record.get('task_id', 'unknown')
        outcome = record.get('outcome', 'unknown')

        files_val = record.get('files_touched')
        if isinstance(files_val, str):
            files_str = files_val
        elif isinstance(files_val, list):
            files_str = ', '.join(str(f) for f in files_val if f is not None)
        elif files_val is None:
            files_str = ''
        else:
            try:
                files_str = ', '.join(str(f) for f in files_val if f is not None)
            except TypeError:
                files_str = str(files_val)

        line = f"Timestamp: {iso_ts} | Task ID: {task_id} | Outcome: {outcome} | Files: {files_str}"
        lines.append(line)

    return '\n'.join(lines) + '\n'