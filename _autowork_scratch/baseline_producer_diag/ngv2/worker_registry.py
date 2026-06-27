"""Deterministic, SQLite-backed registry of workers, resource locks, commands,
and work-intents for NobleGreed v2.

This is a clean-room reimplementation that keeps ONLY the durable state machine.
There is NO process probing, NO signals, NO ``psutil``. Time is the single
injected seam: construct with ``WorkerRegistry(db_path, now_fn=...)`` where
``now_fn() -> float`` returns epoch seconds. With a scripted clock, staleness,
lock expiry, and command expiry are fully deterministic.

Standard library only.
"""
from __future__ import annotations
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
WORKER_STATUSES = ('running', 'completed', 'failed', 'crashed', 'suspended', 'resumed', 'expired')
STALE_THRESHOLD_S = 1800
GPU_STALE_THRESHOLD_S = 300
SUSPEND_TOKEN_THRESHOLD = 50000
RESUME_TOKEN_CEILING = 500000
_DEFAULT_SIMILARITY_THRESHOLD = 0.3
_WORKER_COLUMNS = ('id', 'worker_type', 'pid', 'worktree_path', 'status', 'start_time', 'last_seen', 'exit_code', 'prompt_hash', 'model', 'session_id', 'token_usage', 'prompt_text')

def _word_set(text: Optional[str]) -> set:
    """Lowercased, whitespace-split word set used for similarity scoring."""
    if not text:
        return set()
    return {tok for tok in text.lower().split() if tok}

def _similarity(a: Optional[str], b: Optional[str]) -> float:
    """Jaccard similarity between two free-text strings in [0.0, 1.0]."""
    sa = _word_set(a)
    sb = _word_set(b)
    if not sa and (not sb):
        return 1.0
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0

class WorkerRegistry:
    """SQLite-backed registry of workers, locks, commands, and intents."""

    def __init__(self, db_path: Path, *, now_fn: Optional[Callable[[], float]]=None) -> None:
        self.db_path = Path(db_path)
        self._now: Callable[[], float] = now_fn if now_fn is not None else time.time
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        cur = self._conn.cursor()
        cur.executescript("\n            CREATE TABLE IF NOT EXISTS workers (\n                id INTEGER PRIMARY KEY AUTOINCREMENT,\n                worker_type TEXT,\n                pid INTEGER,\n                worktree_path TEXT,\n                status TEXT NOT NULL DEFAULT 'running',\n                start_time REAL,\n                last_seen REAL,\n                exit_code INTEGER,\n                prompt_hash TEXT,\n                model TEXT,\n                session_id TEXT,\n                token_usage INTEGER DEFAULT 0,\n                prompt_text TEXT\n            );\n\n            CREATE TABLE IF NOT EXISTS tasks (\n                id INTEGER PRIMARY KEY AUTOINCREMENT,\n                worker_id INTEGER,\n                description TEXT,\n                status TEXT,\n                created_at REAL,\n                updated_at REAL\n            );\n\n            CREATE TABLE IF NOT EXISTS resource_locks (\n                resource TEXT PRIMARY KEY,\n                worker_id INTEGER,\n                acquired_at REAL,\n                expires_at REAL\n            );\n\n            CREATE TABLE IF NOT EXISTS worker_commands (\n                id INTEGER PRIMARY KEY AUTOINCREMENT,\n                worker_id INTEGER,\n                command TEXT,\n                issued_at REAL,\n                expires_at REAL,\n                processed_at REAL\n            );\n\n            CREATE TABLE IF NOT EXISTS gpu_queue (\n                id INTEGER PRIMARY KEY AUTOINCREMENT,\n                worker_id INTEGER,\n                resource TEXT,\n                enqueued_at REAL,\n                status TEXT\n            );\n\n            CREATE TABLE IF NOT EXISTS worker_intents (\n                id INTEGER PRIMARY KEY AUTOINCREMENT,\n                worker_id INTEGER,\n                category TEXT,\n                target TEXT,\n                created_at REAL\n            );\n\n            CREATE TABLE IF NOT EXISTS agent_registry (\n                id INTEGER PRIMARY KEY AUTOINCREMENT,\n                name TEXT,\n                role TEXT,\n                registered_at REAL\n            );\n\n            CREATE TABLE IF NOT EXISTS agent_messages (\n                id INTEGER PRIMARY KEY AUTOINCREMENT,\n                sender_id INTEGER,\n                recipient_id INTEGER,\n                body TEXT,\n                created_at REAL\n            );\n            ")
        self._conn.commit()

    def _worker_row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {column: row[column] for column in _WORKER_COLUMNS}

    def register_worker(self, worker_type: str, pid: Optional[int], worktree_path: Optional[str], prompt_hash: Optional[str], model: Optional[str], session_id: Optional[str]) -> int:
        now = self._now()
        cur = self._conn.cursor()
        cur.execute("\n            INSERT INTO workers (\n                worker_type, pid, worktree_path, status,\n                start_time, last_seen, exit_code, prompt_hash,\n                model, session_id, token_usage, prompt_text\n            ) VALUES (?, ?, ?, 'running', ?, ?, NULL, ?, ?, ?, 0, NULL)\n            ", (worker_type, pid, worktree_path, now, now, prompt_hash, model, session_id))
        self._conn.commit()
        return int(cur.lastrowid)

    def heartbeat(self, worker_id: int) -> bool:
        now = self._now()
        cur = self._conn.cursor()
        cur.execute('UPDATE workers SET last_seen = ? WHERE id = ?', (now, worker_id))
        self._conn.commit()
        return cur.rowcount > 0

    def complete_worker(self, worker_id: int, exit_code: int=0) -> bool:
        status = 'completed' if exit_code == 0 else 'failed'
        cur = self._conn.cursor()
        cur.execute('UPDATE workers SET status = ?, exit_code = ? WHERE id = ?', (status, exit_code, worker_id))
        updated = cur.rowcount > 0
        if updated:
            self._release_worker_locks(worker_id)
        self._conn.commit()
        return updated

    def list_workers(self, status_filter: Optional[str]=None) -> List[Dict[str, Any]]:
        cur = self._conn.cursor()
        if status_filter is None:
            cur.execute('SELECT * FROM workers ORDER BY id')
        else:
            cur.execute('SELECT * FROM workers WHERE status = ? ORDER BY id', (status_filter,))
        return [self._worker_row_to_dict(row) for row in cur.fetchall()]

    def get_worker_count(self, status: str, exclude_type: Optional[str]=None) -> int:
        cur = self._conn.cursor()
        if exclude_type is None:
            cur.execute('SELECT COUNT(*) FROM workers WHERE status = ?', (status,))
        else:
            cur.execute('SELECT COUNT(*) FROM workers WHERE status = ? AND worker_type != ?', (status, exclude_type))
        return int(cur.fetchone()[0])

    def _release_worker_locks(self, worker_id: int) -> None:
        cur = self._conn.cursor()
        cur.execute('DELETE FROM resource_locks WHERE worker_id = ?', (worker_id,))

    def acquire_lock(self, resource: str, worker_id: int, timeout_s: float) -> bool:
        now = self._now()
        cur = self._conn.cursor()
        cur.execute('DELETE FROM resource_locks WHERE expires_at <= ?', (now,))
        existing = cur.execute('SELECT worker_id FROM resource_locks WHERE resource = ?', (resource,)).fetchone()
        if existing is not None:
            self._conn.commit()
            return False
        cur.execute('\n            INSERT INTO resource_locks (resource, worker_id, acquired_at, expires_at)\n            VALUES (?, ?, ?, ?)\n            ', (resource, worker_id, now, now + timeout_s))
        self._conn.commit()
        return True

    def release_lock(self, resource: str, worker_id: int) -> bool:
        cur = self._conn.cursor()
        row = cur.execute('SELECT worker_id FROM resource_locks WHERE resource = ?', (resource,)).fetchone()
        if row is None or row['worker_id'] != worker_id:
            return False
        cur.execute('DELETE FROM resource_locks WHERE resource = ?', (resource,))
        self._conn.commit()
        return True

    def _holds_gpu_lock(self, worker_id: int) -> bool:
        cur = self._conn.cursor()
        row = cur.execute("SELECT 1 FROM resource_locks WHERE worker_id = ? AND resource LIKE 'gpu%' LIMIT 1", (worker_id,)).fetchone()
        return row is not None

    def cleanup_stale(self) -> int:
        now = self._now()
        cur = self._conn.cursor()
        rows = cur.execute("SELECT id, last_seen FROM workers WHERE status = 'running'").fetchall()
        crashed = 0
        for row in rows:
            last_seen = row['last_seen']
            if last_seen is None:
                last_seen = 0.0
            threshold = GPU_STALE_THRESHOLD_S if self._holds_gpu_lock(row['id']) else STALE_THRESHOLD_S
            if now - last_seen > threshold:
                cur.execute("UPDATE workers SET status = 'crashed' WHERE id = ?", (row['id'],))
                self._release_worker_locks(row['id'])
                crashed += 1
        self._conn.commit()
        return crashed

    def suspend_worker(self, worker_id: int, session_id: Optional[str], token_usage: int, prompt_text: Optional[str]) -> bool:
        cur = self._conn.cursor()
        cur.execute("\n            UPDATE workers\n               SET status = 'suspended',\n                   session_id = ?,\n                   token_usage = ?,\n                   prompt_text = ?\n             WHERE id = ? AND status = 'running'\n            ", (session_id, token_usage, prompt_text, worker_id))
        updated = cur.rowcount > 0
        if updated:
            self._release_worker_locks(worker_id)
        self._conn.commit()
        return updated

    def find_resumable_worker(self, worker_type: str, task_description: Optional[str], max_tokens: Optional[int], similarity_threshold: Optional[float]) -> Optional[Dict[str, Any]]:
        ceiling = RESUME_TOKEN_CEILING
        if max_tokens is not None:
            ceiling = min(ceiling, max_tokens)
        threshold = _DEFAULT_SIMILARITY_THRESHOLD if similarity_threshold is None else similarity_threshold
        cur = self._conn.cursor()
        candidates = cur.execute("\n            SELECT * FROM workers\n             WHERE status = 'suspended'\n               AND worker_type = ?\n               AND COALESCE(token_usage, 0) < ?\n             ORDER BY id\n            ", (worker_type, ceiling)).fetchall()
        best: Optional[sqlite3.Row] = None
        best_sim = -1.0
        for row in candidates:
            sim = _similarity(row['prompt_text'], task_description)
            if sim >= threshold and sim > best_sim:
                best = row
                best_sim = sim
        if best is None:
            return None
        return self._worker_row_to_dict(best)

    def resume_worker(self, worker_id: int, new_pid: Optional[int]) -> bool:
        now = self._now()
        cur = self._conn.cursor()
        cur.execute("\n            UPDATE workers\n               SET status = 'running',\n                   pid = ?,\n                   last_seen = ?\n             WHERE id = ? AND status = 'suspended'\n            ", (new_pid, now, worker_id))
        self._conn.commit()
        return cur.rowcount > 0

    def expire_worker(self, worker_id: int) -> bool:
        cur = self._conn.cursor()
        cur.execute("UPDATE workers SET status = 'expired' WHERE id = ? AND status = 'suspended'", (worker_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def issue_command(self, worker_id: int, command: str, expires_in_seconds: float) -> int:
        now = self._now()
        cur = self._conn.cursor()
        cur.execute('\n            INSERT INTO worker_commands (worker_id, command, issued_at, expires_at, processed_at)\n            VALUES (?, ?, ?, ?, NULL)\n            ', (worker_id, command, now, now + expires_in_seconds))
        self._conn.commit()
        return int(cur.lastrowid)

    def get_pending_commands(self, worker_id: int) -> List[Dict[str, Any]]:
        now = self._now()
        cur = self._conn.cursor()
        rows = cur.execute('\n            SELECT id, worker_id, command, issued_at, expires_at, processed_at\n              FROM worker_commands\n             WHERE worker_id = ?\n               AND processed_at IS NULL\n               AND expires_at > ?\n             ORDER BY id\n            ', (worker_id, now)).fetchall()
        return [dict(row) for row in rows]

    def mark_command_processed(self, command_id: int) -> bool:
        now = self._now()
        cur = self._conn.cursor()
        cur.execute('UPDATE worker_commands SET processed_at = ? WHERE id = ?', (now, command_id))
        self._conn.commit()
        return cur.rowcount > 0

    def register_intent(self, worker_id: int, category: str, target: str) -> int:
        now = self._now()
        cur = self._conn.cursor()
        cur.execute('\n            INSERT INTO worker_intents (worker_id, category, target, created_at)\n            VALUES (?, ?, ?, ?)\n            ', (worker_id, category, target, now))
        self._conn.commit()
        return int(cur.lastrowid)

    def check_intent_collision(self, category: str, target: str, exclude_worker_id: Optional[int]=None) -> Optional[Dict[str, Any]]:
        cur = self._conn.cursor()
        sql = "\n            SELECT wi.id AS intent_id, wi.worker_id AS worker_id,\n                   wi.category AS category, wi.target AS target\n              FROM worker_intents wi\n              JOIN workers w ON w.id = wi.worker_id\n             WHERE wi.category = ?\n               AND wi.target = ?\n               AND w.status = 'running'\n        "
        params: List[Any] = [category, target]
        if exclude_worker_id is not None:
            sql += ' AND wi.worker_id != ?'
            params.append(exclude_worker_id)
        sql += ' ORDER BY wi.id LIMIT 1'
        row = cur.execute(sql, params).fetchone()
        if row is None:
            return None
        return dict(row)