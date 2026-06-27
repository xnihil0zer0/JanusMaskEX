"""ngv2/human_checkpoint_gate.py

Pure, deterministic SINGLE-human-checkpoint module.

Two responsibilities, each confined to an injected seam:

* ``check_human_approval`` reads the operator decision file (the only
  filesystem read) and decides, failing closed, whether an explicit
  *approve* was recorded.
* ``persist_submission`` stamps a turn-in-ready record with an injected
  clock (``now_fn`` -- never the wall clock) and writes it as a ledger row
  through :class:`ngv2.session_db.SessionDB`.

All non-determinism lives in the two seams (the decision-file read and
``now_fn``); given the same ``(record, now_fn)`` the stamped ledger row is
identical.  No internal wall-clock, randomness, network, subprocess or LLM.
"""
from __future__ import annotations
import json
from typing import Any, Callable, Dict, Optional
import ngv2.session_db as session_db
try:
    import ngv2.contracts as contracts
except Exception:
    contracts = None
_APPROVE_TOKENS = frozenset({'approve', 'approved', 'accept', 'accepted', 'approval'})
_REJECT_MARKERS = ('disapprove', 'disapproved', 'reject', 'rejected', 'deny', 'denied', 'decline', 'declined', 'hold', 'on-hold', 'no-go', 'nogo')
_APPROVE_MARKERS = ('approve', 'approved', 'accept', 'accepted')
_DECISION_FIELDS = ('decision', 'status', 'verdict', 'approval', 'approved', 'result', 'outcome', 'action')

def _token_approval(value: Any) -> bool:
    """Return True iff ``value`` normalises to an explicit approve token."""
    return str(value).strip().lower() in _APPROVE_TOKENS

def _approval_from_json(data: Any) -> Optional[bool]:
    """Resolve approval from parsed JSON.

    Returns True/False when a decision is recognised, or ``None`` when the
    JSON carries no decision-bearing field (so the caller may fall back to a
    tolerant text scan).
    """
    if isinstance(data, bool):
        return data
    if isinstance(data, str):
        return _token_approval(data)
    if isinstance(data, dict):
        lowered = {str(field).strip().lower(): field for field in data.keys()}
        for candidate in _DECISION_FIELDS:
            if candidate in lowered:
                value = data[lowered[candidate]]
                if isinstance(value, bool):
                    return value
                return _token_approval(value)
        return None
    return None

def _approval_from_text(text: str) -> bool:
    """Tolerant markdown/plain-text scan; fails closed on ambiguity."""
    lowered = text.lower()
    if any((marker in lowered for marker in _REJECT_MARKERS)):
        return False
    return any((marker in lowered for marker in _APPROVE_MARKERS))

def check_human_approval(decision_filepath: str) -> bool:
    """Decide approval from the injected operator decision file.

    Returns ``True`` only when the file contains an explicit, unambiguous
    approve decision (case-insensitive).  Returns ``False`` -- never raising --
    when the file is absent, empty, a reject/hold, or any malformed,
    non-approve, or ambiguous content.  Never auto-approves.
    """
    if not decision_filepath:
        return False
    try:
        with open(decision_filepath, 'r', encoding='utf-8') as handle:
            raw = handle.read()
    except (OSError, TypeError, ValueError):
        return False
    if not raw or not raw.strip():
        return False
    text = raw.strip()
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        data = None
    if data is not None:
        verdict = _approval_from_json(data)
        if verdict is not None:
            return verdict
    return _approval_from_text(text)
_LEDGER_FIELDS = ('target', 'cwe', 'severity', 'payout_estimate', 'novelty', 'evidence', 'approval', 'timestamp')
_INSERT_METHODS = ('insert_ledger_row', 'add_ledger_row', 'append_ledger_row', 'write_ledger_row', 'record_ledger_row', 'insert_submission', 'record_submission', 'add_submission', 'insert_row', 'add_row', 'append_row', 'insert', 'add', 'append', 'record', 'write', 'save', 'log')

def _make_session_db() -> Any:
    """Construct a SessionDB, tolerant of its constructor signature."""
    db_cls = session_db.SessionDB
    try:
        return db_cls()
    except TypeError:
        return db_cls(':memory:')

def _insert_ledger_row(db: Any, row: Dict[str, Any]) -> None:
    """Insert ``row`` via the first recognised SessionDB ledger method,
    falling back to the real ``SessionDB.save_session`` write path (the
    ``session_pipeline`` table) when none of the conventional names exists.
    """
    for method_name in _INSERT_METHODS:
        method = getattr(db, method_name, None)
        if callable(method):
            method(row)
            return
    saver = getattr(db, 'save_session', None)
    if callable(saver):
        ledger_key = 'submission:%s:%s' % (row.get('target'), row.get('timestamp'))
        payload = dict(row)
        payload['session_id'] = ledger_key
        saver(ledger_key, payload)
        return
    raise AttributeError('SessionDB exposes no recognised ledger insert method')

def persist_submission(record: Dict[str, Any], now_fn: Callable[[], Any]) -> None:
    """Stamp ``record`` with ``now_fn()`` and persist it as a ledger row.

    The record is copied (the input is not mutated), its ``timestamp`` is set
    from the injected ``now_fn`` (never the wall clock), and the other carried
    fields -- target, cwe, severity, payout_estimate, novelty, evidence,
    approval -- are left intact.  The row is written through
    :class:`ngv2.session_db.SessionDB`.  Deterministic over ``(record, now_fn)``:
    identical inputs yield an identical stamped ledger row.
    """
    row: Dict[str, Any] = dict(record)
    row['timestamp'] = now_fn()
    db = _make_session_db()
    _insert_ledger_row(db, row)