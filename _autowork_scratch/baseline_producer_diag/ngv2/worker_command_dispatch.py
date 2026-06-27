"""Deterministic overseer->worker command-delivery contract.

Clean-room distillation of the legacy ``worker_commands`` SQLite capability
(issue / poll / mark-processed / broadcast). This is an INJECTED-SEAM module:
every function takes an explicit ``db_path`` so the durable state is fully
controllable, and every timestamp is an explicit parameter with a deterministic
default so the same inputs always produce the same output (no wall-clock, no
network, no randomness).
"""
from __future__ import annotations
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple
COMMAND_FIELDS: Tuple[str, ...] = ('id', 'worker_id', 'command', 'issued_at', 'expires_at', 'processed_at', 'issued_by')
VALID_COMMANDS: frozenset = frozenset({'pause', 'resume', 'abort', 'checkpoint', 'rate_limit_backoff'})
DEFAULT_EXPIRES_IN_SECONDS: int = 300
DEFAULT_BACKOFF_DELAY_SECONDS: int = 120
_CREATE_TABLE_SQL = '\nCREATE TABLE IF NOT EXISTS worker_commands (\n    id           INTEGER PRIMARY KEY AUTOINCREMENT,\n    worker_id    INTEGER NOT NULL,\n    command      TEXT    NOT NULL,\n    issued_at    INTEGER NOT NULL,\n    expires_at   INTEGER,\n    processed_at INTEGER,\n    issued_by    TEXT    NOT NULL\n)\n'

def _connect(db_path: str) -> sqlite3.Connection:
    """Open a connection to the durable command store at ``db_path``."""
    return sqlite3.connect(db_path)

def init_db(db_path: str) -> None:
    """Create the ``worker_commands`` table if it does not already exist."""
    conn = _connect(db_path)
    try:
        conn.execute(_CREATE_TABLE_SQL)
        conn.commit()
    finally:
        conn.close()

def _command_base(command: str) -> str:
    """Return the base token of a command, stripping any ``:suffix``."""
    return command.split(':', 1)[0]

def issue_command(worker_id: int, command: str, *, issued_by: str='overseer', expires_in_seconds: int=DEFAULT_EXPIRES_IN_SECONDS, issued_at: int=0, db_path: str) -> int:
    """Persist a single command for ``worker_id`` and return its row id.

    ``command`` may carry a ``:suffix`` (e.g. ``rate_limit_backoff:60``); the
    base token must be a member of :data:`VALID_COMMANDS`, otherwise a
    ``ValueError`` is raised and nothing is persisted.

    ``issued_at`` is an explicit deterministic clock value. ``expires_at`` is
    stamped as ``issued_at + expires_in_seconds`` when ``expires_in_seconds``
    is positive; when it is zero or negative the command never expires
    (``expires_at`` is ``NULL``).
    """
    if _command_base(command) not in VALID_COMMANDS:
        raise ValueError(f'unknown command: {command!r}')
    if expires_in_seconds > 0:
        expires_at: Optional[int] = issued_at + expires_in_seconds
    else:
        expires_at = None
    conn = _connect(db_path)
    try:
        cursor = conn.execute('INSERT INTO worker_commands (worker_id, command, issued_at, expires_at, processed_at, issued_by) VALUES (?, ?, ?, ?, ?, ?)', (worker_id, command, issued_at, expires_at, None, issued_by))
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()

def get_pending_commands(worker_id: int, *, db_path: str) -> List[Dict[str, Any]]:
    """Return the unprocessed commands for ``worker_id``, oldest first.

    Each row is a dict keyed by exactly :data:`COMMAND_FIELDS`. Only commands
    that have not yet been marked processed are returned; results are ordered
    by ascending row id (insertion order).
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute('SELECT id, worker_id, command, issued_at, expires_at, processed_at, issued_by FROM worker_commands WHERE worker_id = ? AND processed_at IS NULL ORDER BY id ASC', (worker_id,)).fetchall()
    finally:
        conn.close()
    return [dict(zip(COMMAND_FIELDS, row)) for row in rows]

def mark_command_processed(command_id: int, *, processed_at: int=0, db_path: str) -> None:
    """Mark the command with ``command_id`` as processed.

    Idempotent: marking an already-processed (or non-existent) command does
    not raise. ``processed_at`` is an explicit deterministic clock value;
    any non-NULL value removes the command from the pending set.
    """
    conn = _connect(db_path)
    try:
        conn.execute('UPDATE worker_commands SET processed_at = ? WHERE id = ? AND processed_at IS NULL', (processed_at, command_id))
        conn.commit()
    finally:
        conn.close()

def broadcast_rate_limit(worker_ids: Sequence[int], *, delay_seconds: int=DEFAULT_BACKOFF_DELAY_SECONDS, exclude_worker_id: Optional[int]=None, issued_by: str='overseer', issued_at: int=0, db_path: str) -> int:
    """Issue a ``rate_limit_backoff:<delay_seconds>`` command to each worker.

    The worker matching ``exclude_worker_id`` (if any) is skipped. Returns the
    number of commands actually issued.
    """
    command = f'rate_limit_backoff:{delay_seconds}'
    issued = 0
    for worker_id in worker_ids:
        if exclude_worker_id is not None and worker_id == exclude_worker_id:
            continue
        issue_command(worker_id, command, issued_by=issued_by, issued_at=issued_at, db_path=db_path)
        issued += 1
    return issued