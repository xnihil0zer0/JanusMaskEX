"""Deterministic work-intent coordination layer.

This module sits on top of an already-built ``ngv2.worker_registry.WorkerRegistry``
(a durable SQLite state machine whose only non-deterministic seam is an injected
``now_fn``).  It adds the typed *contract* the legacy registry lacked:

* a fixed, ordered :data:`INTENT_TYPES` vocabulary,
* validation of ``intent_type`` / ``target`` inputs, and
* a small :class:`WorkIntentTracker` wrapper (plus module-level helpers) that
  records work intents and detects collisions between *running* workers.

It is pure coordination -- no process probing, no signals, no network, no LLM
calls and no randomness.  All determinism flows from the injected registry
(which itself takes an injected clock); this layer never reads a wall clock.

A *collision* exists when another worker that is still **running** has already
registered the same ``(intent_type, target)`` pair.  Because the legacy
``WorkerRegistry`` has no hook into intent bookkeeping, "freeing" an intent when
its holder completes is achieved at *read* time: collisions are only reported
for intents whose owning worker is still live in the registry.
"""
from __future__ import annotations
import os
import sqlite3
from typing import Any, Dict, Optional, Set, Tuple
INTENT_TYPES: Tuple[str, ...] = ('audit', 'clone', 'poc', 'live_test', 'hunt', 'submit')
_INTENTS_TABLE = 'work_intents'
_COMPLETED_STATES = frozenset({'completed', 'complete', 'done', 'finished', 'exited', 'exit', 'failed', 'fail', 'dead', 'killed', 'stopped', 'crashed', 'timeout', 'timedout', 'cancelled', 'canceled', 'error', 'errored', 'orphaned', 'reaped', 'zombie', 'closed', 'aborted', 'terminated'})

def _validate_intent_type(intent_type: Any) -> None:
    """Raise :class:`ValueError` unless *intent_type* is a known intent."""
    if intent_type not in INTENT_TYPES:
        raise ValueError('unknown intent_type %r; expected one of %r' % (intent_type, list(INTENT_TYPES)))

def _validate_target(target: Any) -> None:
    """Raise :class:`ValueError` unless *target* is a non-empty string."""
    if not isinstance(target, str) or not target.strip():
        raise ValueError('target must be a non-empty string, got %r' % (target,))

def _resolve_db_path(registry: Any) -> Optional[str]:
    """Best-effort discovery of the registry's on-disk SQLite path."""
    state = getattr(registry, '__dict__', {}) or {}
    for value in state.values():
        try:
            path = os.fspath(value)
        except TypeError:
            continue
        if isinstance(path, bytes):
            try:
                path = path.decode()
            except Exception:
                continue
        if isinstance(path, str) and path and os.path.exists(path):
            return path
    return None

def _resolve_connection(registry: Any) -> sqlite3.Connection:
    """Return a usable SQLite connection to the registry's database.

    Prefers reusing a live :class:`sqlite3.Connection` already held by the
    registry (so intent rows and worker rows share one database), and otherwise
    opens a fresh connection to the discovered database file.
    """
    state = getattr(registry, '__dict__', {}) or {}
    for value in state.values():
        if isinstance(value, sqlite3.Connection):
            return value
    for value in state.values():
        if isinstance(value, type):
            continue
        if hasattr(value, 'execute') and hasattr(value, 'commit'):
            try:
                value.execute('SELECT 1')
                return value
            except Exception:
                continue
    path = _resolve_db_path(registry)
    if path is not None:
        return sqlite3.connect(path)
    raise RuntimeError("could not locate the registry's SQLite connection")

def _pick_workers_table(conn: sqlite3.Connection, tables: Any) -> Optional[str]:
    """Choose the table that holds worker rows, by name then by shape."""
    lower = {str(t).lower(): t for t in tables}
    for candidate in ('workers', 'worker'):
        if candidate in lower:
            return lower[candidate]
    for table in tables:
        if table == _INTENTS_TABLE:
            continue
        try:
            cols = [str(row[1]).lower() for row in conn.execute('PRAGMA table_info("%s")' % table).fetchall()]
        except Exception:
            continue
        has_id = 'id' in cols or 'worker_id' in cols
        has_state = any((c in cols for c in ('status', 'state', 'exit_code', 'exitcode', 'completed_at', 'finished_at')))
        if has_id and has_state:
            return table
    return None

def _row_is_completed(rec: Dict[str, Any], lcols: Dict[str, str]) -> bool:
    """Return ``True`` if a worker row shows any sign of having finished."""
    for field in ('status', 'state'):
        if field in lcols:
            value = rec.get(lcols[field])
            if value is not None and str(value).strip().lower() in _COMPLETED_STATES:
                return True
    for field in ('completed_at', 'finished_at', 'ended_at', 'exited_at', 'done_at', 'closed_at', 'completion_time', 'end_time'):
        if field in lcols and rec.get(lcols[field]) is not None:
            return True
    for field in ('exit_code', 'exitcode', 'return_code', 'returncode'):
        if field in lcols and rec.get(lcols[field]) is not None:
            return True
    return False

def _running_worker_ids(conn: sqlite3.Connection) -> Set[Any]:
    """Return the set of worker ids that are currently running."""
    try:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()]
    except Exception:
        return set()
    table = _pick_workers_table(conn, tables)
    if table is None:
        return set()
    cur = conn.execute('SELECT * FROM "%s"' % table)
    colnames = [d[0] for d in cur.description]
    lcols = {c.lower(): c for c in colnames}
    id_field = lcols.get('id') or lcols.get('worker_id')
    if id_field is None and colnames:
        id_field = colnames[0]
    if id_field is None:
        return set()
    running: Set[Any] = set()
    for row in cur.fetchall():
        rec = {colnames[i]: row[i] for i in range(len(colnames))}
        if not _row_is_completed(rec, lcols):
            running.add(rec.get(id_field))
    return running

class WorkIntentTracker:
    """Typed coordination layer over a ``WorkerRegistry`` instance.

    The tracker stores intent rows in a dedicated table inside the registry's
    own SQLite database and reports a collision only when another *running*
    worker already holds the same ``(intent_type, target)`` pair.
    """

    def __init__(self, registry: Any) -> None:
        self._registry = registry
        self._conn = _resolve_connection(registry)
        self._ensure_table()

    def _ensure_table(self) -> None:
        self._conn.execute('CREATE TABLE IF NOT EXISTS %s ( id INTEGER PRIMARY KEY AUTOINCREMENT, worker_id INTEGER NOT NULL, intent_type TEXT NOT NULL, target TEXT NOT NULL)' % _INTENTS_TABLE)
        self._conn.commit()

    def register_intent(self, worker_id: int, intent_type: str, target: str) -> int:
        """Record that *worker_id* intends *intent_type* work on *target*.

        Validation happens before any database write, so a bad request never
        leaves a row behind.  Returns the new intent's positive row id.
        """
        _validate_intent_type(intent_type)
        _validate_target(target)
        cur = self._conn.execute('INSERT INTO %s (worker_id, intent_type, target) VALUES (?, ?, ?)' % _INTENTS_TABLE, (worker_id, intent_type, target))
        self._conn.commit()
        return int(cur.lastrowid)

    def check_intent_collision(self, intent_type: str, target: str, exclude_worker_id: Optional[int]=None) -> Optional[Dict[str, Any]]:
        """Return the colliding intent, or ``None`` if the pair is free.

        A collision exists when a *running* worker -- other than
        *exclude_worker_id* -- already registered this ``(intent_type, target)``
        pair.  Intents owned by workers that have since completed are ignored,
        which is how a holder completing frees the pair again.
        """
        _validate_intent_type(intent_type)
        running = _running_worker_ids(self._conn)
        cur = self._conn.execute('SELECT id, worker_id, intent_type, target FROM %s WHERE intent_type = ? AND target = ? ORDER BY id' % _INTENTS_TABLE, (intent_type, target))
        for row in cur.fetchall():
            intent_id, worker_id, row_type, row_target = (row[0], row[1], row[2], row[3])
            if exclude_worker_id is not None and worker_id == exclude_worker_id:
                continue
            if worker_id in running:
                return {'id': intent_id, 'worker_id': worker_id, 'intent_type': row_type, 'target': row_target}
        return None

def register_intent(registry: Any, worker_id: int, intent_type: str, target: str) -> int:
    """Module-level convenience wrapper for :meth:`WorkIntentTracker.register_intent`."""
    return WorkIntentTracker(registry).register_intent(worker_id, intent_type, target)

def check_intent_collision(registry: Any, intent_type: str, target: str, exclude_worker_id: Optional[int]=None) -> Optional[Dict[str, Any]]:
    """Module-level convenience wrapper for :meth:`WorkIntentTracker.check_intent_collision`."""
    return WorkIntentTracker(registry).check_intent_collision(intent_type, target, exclude_worker_id=exclude_worker_id)