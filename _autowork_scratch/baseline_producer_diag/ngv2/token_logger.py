"""ngv2.token_logger — deterministic stdlib-only sqlite3 cost/usage ledger.

A tiny accounting shell with no clock, network, or randomness in its tested
surface. Pricing is a fixed table (cost-per-million tokens), the database
path is the only injection seam, and the timestamp is supplied by the caller
so every recorded row is fully deterministic.
"""
from __future__ import annotations
import sqlite3
from typing import Any, Dict, Optional
__all__ = ['PRICING', 'SCHEMA', 'log_message', 'aggregate_session']
PRICING: Dict[str, Dict[str, float]] = {'opus': {'input': 15.0, 'output': 75.0, 'cache_read': 1.5}, 'sonnet': {'input': 3.0, 'output': 15.0, 'cache_read': 0.3}}
_DEFAULT_MODEL = 'sonnet'
_MODEL_RULES = (('opus', 'opus'), ('sonnet', 'sonnet'))
SCHEMA = '\nCREATE TABLE IF NOT EXISTS sessions (\n    session_id   TEXT PRIMARY KEY,\n    first_seen   TEXT,\n    last_seen    TEXT\n);\n\nCREATE TABLE IF NOT EXISTS messages (\n    id            INTEGER PRIMARY KEY AUTOINCREMENT,\n    session_id    TEXT    NOT NULL,\n    timestamp     TEXT    NOT NULL,\n    role          TEXT,\n    model         TEXT,\n    input_tokens  INTEGER NOT NULL DEFAULT 0,\n    output_tokens INTEGER NOT NULL DEFAULT 0,\n    cached_tokens INTEGER NOT NULL DEFAULT 0,\n    cost_usd      REAL    NOT NULL DEFAULT 0\n);\n\nCREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);\n'
_COST_PRECISION = 8

def _normalize_model(model: Optional[str]) -> str:
    """Map a raw model identifier to a key present in ``PRICING``.

    Case-insensitive substring match; falls back to the default model for
    empty, ``None``, or unrecognized identifiers.
    """
    if not model:
        return _DEFAULT_MODEL
    lowered = model.lower()
    for needle, normalized in _MODEL_RULES:
        if needle in lowered:
            return normalized
    return _DEFAULT_MODEL

def _connect(db_path: str) -> sqlite3.Connection:
    """Open ``db_path`` and ensure the schema exists idempotently."""
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn

def _compute_cost(normalized_model: str, input_tokens: int, output_tokens: int, cached_tokens: int) -> float:
    """Compute the USD cost of a single message via the pricing table."""
    rates = PRICING[normalized_model]
    raw = (input_tokens * rates['input'] + output_tokens * rates['output'] + cached_tokens * rates['cache_read']) / 1000000
    return round(raw, _COST_PRECISION)

def log_message(session_id: str, timestamp: str, role: str, model: str, input_tokens: int, output_tokens: int, cached_tokens: int, db_path: str) -> float:
    """Persist one usage event and return its computed cost in USD.

    The model is normalized before storage and pricing lookup. The supplied
    ``timestamp`` is recorded verbatim (the injected clock seam). The write
    is committed so a reopened ledger observes it.
    """
    normalized = _normalize_model(model)
    cost = _compute_cost(normalized, input_tokens, output_tokens, cached_tokens)
    conn = _connect(db_path)
    try:
        conn.execute('INSERT OR IGNORE INTO sessions (session_id, first_seen, last_seen) VALUES (?, ?, ?)', (session_id, timestamp, timestamp))
        conn.execute('UPDATE sessions SET last_seen = ? WHERE session_id = ?', (timestamp, session_id))
        conn.execute('INSERT INTO messages (session_id, timestamp, role, model, input_tokens, output_tokens, cached_tokens, cost_usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (session_id, timestamp, role, normalized, input_tokens, output_tokens, cached_tokens, cost))
        conn.commit()
    finally:
        conn.close()
    return cost

def aggregate_session(session_id: str, db_path: str) -> Dict[str, Any]:
    """Return summed token/cost totals for a single session.

    Unknown or empty sessions yield a fully zeroed shape rather than raising.
    """
    conn = _connect(db_path)
    try:
        row = conn.execute('SELECT COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0), COALESCE(SUM(cached_tokens), 0), COALESCE(SUM(cost_usd), 0), COUNT(*) FROM messages WHERE session_id = ?', (session_id,)).fetchone()
    finally:
        conn.close()
    total_input = int(row[0])
    total_output = int(row[1])
    total_cached = int(row[2])
    total_cost = round(float(row[3]), _COST_PRECISION)
    message_count = int(row[4])
    return {'total_input_tokens': total_input, 'total_output_tokens': total_output, 'total_cached_tokens': total_cached, 'total_tokens': total_input + total_output + total_cached, 'total_cost': total_cost, 'message_count': message_count}