"""Deterministic, SQLite-backed registry of sub-agents and inter-agent messages.

This is the clean-room distillation of the legacy NobleGreed agent-tracking
surface. All durable state lives in an in-process ``sqlite3`` database; the only
non-determinism seam is an injected time source ``now_fn() -> float`` (epoch
seconds). There is no real clock, no network, no subprocess, no PID probing and
no randomness in the tested surface: message TTL expiry and agent staleness are
pure DB state-transitions driven entirely by ``now_fn`` and stored timestamps.

Stdlib only.
"""
from __future__ import annotations
import sqlite3
from typing import Any, Callable, Dict, List, Optional, Union
try:
    from os import PathLike
    _PathLike = Union[str, 'PathLike[str]']
except Exception:
    _PathLike = Any
AGENT_STALE_THRESHOLD_S = 1800
AGENT_STATUSES = ('running', 'completed', 'failed')
_TERMINAL_STATUSES = ('completed', 'failed')

class AgentRegistry:
    """A deterministic, SQLite-backed registry of sub-agents and messages.

    Parameters
    ----------
    db_path:
        Filesystem path (``str`` or path-like) of the backing SQLite database.
        A fresh path yields a fresh schema; an existing path reuses prior state.
    now_fn:
        Zero-argument callable returning the current epoch seconds as a float.
        This is the single injected time seam; the registry never reads a real
        clock.
    """

    def __init__(self, db_path: _PathLike, now_fn: Callable[[], float]=lambda: 0.0) -> None:
        self._now_fn = now_fn
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute('\n            CREATE TABLE IF NOT EXISTS agent_registry (\n                agent_id      TEXT PRIMARY KEY,\n                worker_id     INTEGER,\n                session_id    TEXT,\n                agent_type    TEXT,\n                role          TEXT,\n                status        TEXT,\n                registered_at REAL,\n                last_seen     REAL,\n                finished_at   REAL\n            )\n            ')
        cur.execute('\n            CREATE TABLE IF NOT EXISTS agent_messages (\n                id         INTEGER PRIMARY KEY AUTOINCREMENT,\n                to_agent   TEXT,\n                from_agent TEXT,\n                message    TEXT,\n                created_at REAL,\n                expires_at REAL,\n                read_at    REAL\n            )\n            ')
        self._conn.commit()

    def _now(self) -> float:
        return float(self._now_fn())

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        return {col: row[col] for col in row.keys()}

    def register_agent(self, agent_id: str, worker_id: int, session_id: str, agent_type: str='', role: Optional[str]=None) -> bool:
        """Insert a new ``running`` agent.

        Returns ``True`` on insert; re-registering an existing ``agent_id`` is a
        no-op that returns ``False`` (never raises).
        """
        now = self._now()
        try:
            self._conn.execute("\n                INSERT INTO agent_registry (\n                    agent_id, worker_id, session_id, agent_type, role,\n                    status, registered_at, last_seen, finished_at\n                ) VALUES (?, ?, ?, ?, ?, 'running', ?, ?, NULL)\n                ", (agent_id, worker_id, session_id, agent_type, role, now, now))
        except sqlite3.IntegrityError:
            return False
        self._conn.commit()
        return True

    def agent_heartbeat(self, agent_id: str) -> bool:
        """Refresh ``last_seen`` for a ``running`` agent.

        Returns ``True`` if a running agent was updated; ``False`` for an
        unknown agent or one that is no longer running.
        """
        now = self._now()
        cur = self._conn.execute("UPDATE agent_registry SET last_seen = ? WHERE agent_id = ? AND status = 'running'", (now, agent_id))
        self._conn.commit()
        return cur.rowcount > 0

    def complete_agent(self, agent_id: str, status: str='completed') -> bool:
        """Transition an agent to a terminal status.

        ``status`` is coerced to ``'completed'`` unless it is exactly one of the
        terminal statuses (``'completed'`` / ``'failed'``). Returns ``True`` if
        an agent was updated, ``False`` if no such agent exists.
        """
        final_status = status if status in _TERMINAL_STATUSES else 'completed'
        now = self._now()
        cur = self._conn.execute('UPDATE agent_registry SET status = ?, finished_at = ? WHERE agent_id = ?', (final_status, now, agent_id))
        self._conn.commit()
        return cur.rowcount > 0

    def set_agent_role(self, agent_id: str, role: Optional[str]) -> bool:
        """Set an agent's ``role``. Returns ``False`` if the agent is missing."""
        cur = self._conn.execute('UPDATE agent_registry SET role = ? WHERE agent_id = ?', (role, agent_id))
        self._conn.commit()
        return cur.rowcount > 0

    def list_agents(self, worker_id: int=0, status: Optional[str]=None, role: Optional[str]=None) -> List[Dict[str, Any]]:
        """Enumerate agents, optionally filtered.

        ``worker_id == 0`` (or ``None``) means "no worker filter"; ``status`` and
        ``role`` filter when truthy/non-``None``.
        """
        clauses: List[str] = []
        params: List[Any] = []
        if worker_id:
            clauses.append('worker_id = ?')
            params.append(worker_id)
        if status is not None:
            clauses.append('status = ?')
            params.append(status)
        if role is not None:
            clauses.append('role = ?')
            params.append(role)
        sql = 'SELECT * FROM agent_registry'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY registered_at, agent_id'
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def cleanup_stale_agents(self) -> int:
        """Mark ``running`` agents whose ``last_seen`` is stale as ``failed``.

        An agent is stale when ``now - last_seen > AGENT_STALE_THRESHOLD_S``.
        Returns the number of agents transitioned. Idempotent: agents already in
        a terminal status are untouched.
        """
        now = self._now()
        cutoff = now - AGENT_STALE_THRESHOLD_S
        cur = self._conn.execute("UPDATE agent_registry SET status = 'failed', finished_at = ? WHERE status = 'running' AND last_seen < ?", (now, cutoff))
        self._conn.commit()
        return cur.rowcount

    def send_agent_message(self, to_agent: str, message: str, from_agent: Optional[str]=None, expires_in_seconds: float=0) -> int:
        """Queue a message for ``to_agent``.

        ``expires_in_seconds <= 0`` means the message never expires. Returns the
        new message's integer id (always ``> 0``).
        """
        now = self._now()
        expires_at: Optional[float]
        if expires_in_seconds and expires_in_seconds > 0:
            expires_at = now + expires_in_seconds
        else:
            expires_at = None
        cur = self._conn.execute('\n            INSERT INTO agent_messages (\n                to_agent, from_agent, message, created_at, expires_at, read_at\n            ) VALUES (?, ?, ?, ?, ?, NULL)\n            ', (to_agent, from_agent, message, now, expires_at))
        self._conn.commit()
        return int(cur.lastrowid)

    def get_agent_messages(self, to_agent: str, mark_read: bool=False) -> List[Dict[str, Any]]:
        """Return unread, unexpired messages for ``to_agent``.

        Expiry is clock-driven: a message is excluded once ``now >= expires_at``
        (``expires_at IS NULL`` never expires). When ``mark_read`` is true, the
        returned messages are marked read (their snapshot still reflects the
        pre-read ``read_at`` of ``None``); a subsequent call will not return
        them again.
        """
        now = self._now()
        rows = self._conn.execute('\n            SELECT * FROM agent_messages\n            WHERE to_agent = ?\n              AND read_at IS NULL\n              AND (expires_at IS NULL OR expires_at > ?)\n            ORDER BY id\n            ', (to_agent, now)).fetchall()
        result = [self._row_to_dict(r) for r in rows]
        if mark_read and result:
            ids = [m['id'] for m in result]
            placeholders = ','.join(('?' for _ in ids))
            self._conn.execute('UPDATE agent_messages SET read_at = ? WHERE id IN (%s)' % placeholders, [now] + ids)
            self._conn.commit()
        return result

    def close(self) -> None:
        """Close the backing SQLite connection."""
        self._conn.close()