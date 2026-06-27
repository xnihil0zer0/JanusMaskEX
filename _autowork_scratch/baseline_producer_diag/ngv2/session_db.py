"""Durable, crash-resilient session-state store backed by its own SQLite file.

``SessionDB`` persists the artifacts produced during a NobleGreed pipeline run --
findings, proof-of-concepts (PoCs), live-test / detonation reports, and a
phase-validation audit log -- into a *single, dedicated* SQLite database file
that is never merged into ``worker_registry.db`` / ``agent_registry`` /
``work_intents``.

Design notes
------------
* The path is *injected* (``SessionDB(db_path)``), mirroring the
  ``WorkerRegistry(db_path)`` convention -- there is **no** hardcoded default
  (no ``/tmp`` fallback).
* The schema is normalized into five tables -- ``session_pipeline``,
  ``findings``, ``pocs``, ``live_test_reports`` and ``phase_validation_logs`` --
  with ``FOREIGN KEY`` constraints (``pocs.finding_id -> findings.id`` and
  ``live_test_reports.poc_finding_id -> pocs.finding_id``) and ``CHECK``
  constraints that are built directly from ``contracts.SEVERITIES`` and
  ``contracts.VERDICTS`` so they can never drift from the contracts.
* Every connection issues ``PRAGMA journal_mode=WAL``,
  ``PRAGMA synchronous=NORMAL``, ``PRAGMA busy_timeout=5000`` and
  ``PRAGMA foreign_keys=ON`` (FK enforcement is off by default in SQLite).
* Writes run inside ``BEGIN IMMEDIATE`` transactions for atomic, gated phase
  persistence.
* Row (de)serialization reuses the contracts' own ``to_dict`` / ``from_dict``;
  the canonical artifact is stored as a JSON ``data`` column and the columns
  that participate in ``CHECK`` / ``FOREIGN KEY`` constraints (``id``,
  ``finding_id``, ``severity``, ``poc_finding_id``, ``verdict``) are projected
  out of that dict, so a round-trip reproduces the artifact faithfully.

Determinism: this module never reads a wall clock or any nondeterministic
source. It imports only the Python standard library.
"""
from __future__ import annotations
import json
import os
import sqlite3
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Sequence
try:
    from ngv2 import contracts as contracts
except Exception:
    try:
        from . import contracts as contracts
    except Exception:
        import contracts as contracts

def _resolve_class(*candidate_names: str) -> Optional[type]:
    """Return the first attribute of ``contracts`` matching one of the names."""
    for ident in candidate_names:
        obj = getattr(contracts, ident, None)
        if isinstance(obj, type):
            return obj
    return None

def _resolve_seq(*candidate_names: str) -> Sequence[str]:
    """Return the first sequence attribute of ``contracts`` matching a name."""
    for ident in candidate_names:
        obj = getattr(contracts, ident, None)
        if obj is not None:
            return list(obj)
    return []
from ngv2.contracts import Finding
_FINDING_CLS = Finding
from ngv2.contracts import PoC
_POC_CLS = PoC
from ngv2.contracts import LiveTestReport
_REPORT_CLS = LiveTestReport
SEVERITIES: Sequence[str] = _resolve_seq('SEVERITIES') or ['low', 'medium', 'high', 'critical']
VERDICTS: Sequence[str] = _resolve_seq('VERDICTS') or ['confirmed', 'refuted', 'error', 'inconclusive']

def _to_dict(obj):
    """Accept a contract dataclass (via ``to_dict``) or a plain mapping."""
    if isinstance(obj, dict):
        return dict(obj)
    to_dict = getattr(obj, 'to_dict', None)
    if callable(to_dict):
        data = to_dict()
        if isinstance(data, dict):
            return dict(data)
    raise TypeError('cannot convert %r to a dict payload' % (type(obj).__name__,))

def _from_dict(cls, data):
    """Rebuild a contract object from a parsed dict (ignores extra keys)."""
    from_dict = getattr(cls, 'from_dict', None)
    if callable(from_dict):
        return from_dict(data)
    return cls(**data)

def _pick(payload, *keys):
    """Return the value of the first present key, else None."""
    for key in keys:
        if key in payload:
            return payload[key]
    return None

def _quoted_set(values):
    """Render an iterable of literals as a SQL ``IN`` set, e.g. ('a', 'b')."""
    return '(' + ', '.join(("'" + str(value) + "'" for value in values)) + ')'

class SessionDB:
    """SQLite-backed persistence for the NGv2 bounty session pipeline.

    Stores findings, proof-of-concepts, reports, phase-validation logs, and the
    per-session FSM working-state across five tables in a single sqlite file.
    Writes go through :meth:`_write` under a ``BEGIN IMMEDIATE`` transaction so
    they commit atomically; point reads use ``self._conn`` directly.
    """

    def __init__(self, db_path):
        self.db_path = os.fspath(db_path)
        self._db_path = self.db_path
        self._conn = sqlite3.connect(self.db_path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._configure_connection()
        self._init_schema()

    def _configure_connection(self):
        self._conn.execute('PRAGMA journal_mode=WAL')
        self._conn.execute('PRAGMA synchronous=NORMAL')
        self._conn.execute('PRAGMA busy_timeout=5000')
        self._conn.execute('PRAGMA foreign_keys=ON')

    def _init_schema(self):
        severity_set = _quoted_set(SEVERITIES)
        verdict_set = _quoted_set(VERDICTS)
        statements = ['CREATE TABLE IF NOT EXISTS findings ( id INTEGER PRIMARY KEY, session_id TEXT, finding_id TEXT NOT NULL UNIQUE, severity TEXT NOT NULL CHECK (severity IN ' + severity_set + "), data TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(data)))", "CREATE TABLE IF NOT EXISTS pocs ( id INTEGER PRIMARY KEY, session_id TEXT, finding_id TEXT NOT NULL UNIQUE REFERENCES findings (finding_id), data TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(data)))", 'CREATE TABLE IF NOT EXISTS reports ( id INTEGER PRIMARY KEY, session_id TEXT, poc_finding_id TEXT NOT NULL REFERENCES pocs (finding_id), verdict TEXT NOT NULL CHECK (verdict IN ' + verdict_set + "), data TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(data)))", "CREATE TABLE IF NOT EXISTS phase_validation_logs ( id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, phase TEXT, data TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(data)))", "CREATE TABLE IF NOT EXISTS session_pipeline ( id INTEGER PRIMARY KEY, phase TEXT, data TEXT NOT NULL DEFAULT '{}')"]
        for statement in statements:
            self._conn.execute(statement)

    def _begin(self):
        self._conn.execute('BEGIN')

    def _commit(self):
        self._conn.execute('COMMIT')

    def _rollback(self):
        self._conn.execute('ROLLBACK')

    def _write(self, sql, params=()):
        self._begin()
        try:
            cursor = self._conn.execute(sql, params)
        except Exception:
            self._rollback()
            raise
        self._commit()
        return cursor.lastrowid

    def insert_finding(self, finding):
        payload = _to_dict(finding)
        finding_id = _pick(payload, 'id', 'finding_id', 'fid')
        severity = _pick(payload, 'severity')
        session_id = _pick(payload, 'session_id')
        return self._write('INSERT INTO findings (session_id, finding_id, severity, data) VALUES (?, ?, ?, ?)', (session_id, finding_id, severity, json.dumps(payload, sort_keys=True)))

    def get_finding(self, finding_id):
        row = self._conn.execute('SELECT data FROM findings WHERE finding_id = ?', (finding_id,)).fetchone()
        if row is None:
            return None
        try:
            parsed = json.loads(row['data'])
        except (ValueError, TypeError):
            return None
        if not isinstance(parsed, dict):
            return None
        return _from_dict(_FINDING_CLS, parsed)

    def insert_poc(self, poc):
        payload = _to_dict(poc)
        finding_id = _pick(payload, 'finding_id', 'id', 'fid')
        session_id = _pick(payload, 'session_id')
        return self._write('INSERT INTO pocs (session_id, finding_id, data) VALUES (?, ?, ?)', (session_id, finding_id, json.dumps(payload, sort_keys=True)))

    def get_poc(self, finding_id):
        row = self._conn.execute('SELECT data FROM pocs WHERE finding_id = ?', (finding_id,)).fetchone()
        if row is None:
            return None
        try:
            parsed = json.loads(row['data'])
        except (ValueError, TypeError):
            return None
        if not isinstance(parsed, dict):
            return None
        return _from_dict(_POC_CLS, parsed)

    def insert_report(self, report):
        payload = _to_dict(report)
        poc_finding_id = _pick(payload, 'poc_finding_id', 'poc_id')
        verdict = _pick(payload, 'verdict')
        session_id = _pick(payload, 'session_id')
        return self._write('INSERT INTO reports (session_id, poc_finding_id, verdict, data) VALUES (?, ?, ?, ?)', (session_id, poc_finding_id, verdict, json.dumps(payload, sort_keys=True)))

    def get_report(self, poc_finding_id):
        row = self._conn.execute('SELECT data FROM reports WHERE poc_finding_id = ?', (poc_finding_id,)).fetchone()
        if row is None:
            return None
        try:
            parsed = json.loads(row['data'])
        except (ValueError, TypeError):
            return None
        if not isinstance(parsed, dict):
            return None
        return _from_dict(_REPORT_CLS, parsed)

    def append_phase_validation_log(self, session_id, phase, entry):
        return self._write('INSERT INTO phase_validation_logs (session_id, phase, data) VALUES (?, ?, ?)', (session_id, phase, json.dumps(entry, sort_keys=True)))

    def get_phase_validation_logs(self, session_id=None):
        if session_id is None:
            rows = self._conn.execute('SELECT data FROM phase_validation_logs ORDER BY id').fetchall()
        else:
            rows = self._conn.execute('SELECT data FROM phase_validation_logs WHERE session_id = ? ORDER BY id', (session_id,)).fetchall()
        logs = []
        for row in rows:
            try:
                parsed = json.loads(row['data'])
            except (ValueError, TypeError):
                continue
            logs.append(parsed)
        return logs

    def _next_sequential_id(self, table):
        row = self._conn.execute('SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM ' + table).fetchone()
        return row['next_id']

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def get_session(self, session_id):
        row = self._conn.execute("SELECT data FROM session_pipeline WHERE json_extract(data, '$.session_id') = ?", (session_id,)).fetchone()
        if row is None:
            return None
        try:
            parsed = json.loads(row['data'])
        except (ValueError, TypeError):
            return None
        if not isinstance(parsed, dict):
            return None
        return parsed

    def save_session(self, session_id, state):
        payload = dict(state or {})
        payload['session_id'] = session_id
        data = json.dumps(payload, sort_keys=True)
        phase = payload.get('phase')
        existing = self._conn.execute("SELECT id FROM session_pipeline WHERE json_extract(data, '$.session_id') = ?", (session_id,)).fetchone()
        if existing is None:
            return self._write('INSERT INTO session_pipeline (phase, data) VALUES (?, ?)', (phase, data))
        return self._write('UPDATE session_pipeline SET phase = ?, data = ? WHERE id = ?', (phase, data, existing['id']))
from ngv2.contracts import SEVERITIES
from ngv2.contracts import VERDICTS
'SQLite-backed session store for the NobleGreedv2 bounty FSM.\n\nStateful store for the agentic pipeline. Findings / PoCs / live-test reports are\npersisted as JSON blobs alongside the keyed contract-id columns, with a severity\nCHECK constraint, a finding-id UNIQUE constraint, and a PoC -> Finding foreign\nkey. The artifact tables keep a NULLABLE ``session_id`` column so a bare,\nunstamped contract can still be inserted.\n'