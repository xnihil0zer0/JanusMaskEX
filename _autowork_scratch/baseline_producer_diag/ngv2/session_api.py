"""Pure, deterministic SessionApi handler over an injected Epic-B SessionDB.

This module exposes a single ``SessionApi`` class that mediates session state
through the *existing* ``session_pipeline`` table of the injected
``ngv2.session_db.SessionDB`` (no new schema), validates artifacts against the
``ngv2.contracts`` data models before any write, and records a
``phase_validation_logs`` audit row on every transition attempt.

The handler is intentionally pure: it performs no transport, no networking, no
socket work, and no wall-clock / random access.  Any timestamp comes from an
injected ``now_fn`` (and is omitted entirely when none is supplied), so the
same inputs always yield the same output.
"""
from __future__ import annotations
import json
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
try:
    from ngv2.session_gate import gate_transition as _gate_transition
except Exception:
    _gate_transition = None
try:
    from ngv2.phase_runner import get_next_phase as _get_next_phase
except Exception:
    _get_next_phase = None
try:
    from ngv2.state_machine import ALLOWED_TRANSITIONS as _ALLOWED_TRANSITIONS
except Exception:
    _ALLOWED_TRANSITIONS = {}
try:
    from ngv2.contracts import Finding as _Finding
except Exception:
    _Finding = None
try:
    from ngv2.contracts import PoC as _PoC
except Exception:
    _PoC = None
try:
    from ngv2.contracts import LiveTestReport as _LiveTestReport
except Exception:
    _LiveTestReport = None
_INITIAL_PHASE = 'hunt'
_SENTINEL = object()

class SessionApi:
    """Pure handler over an injected ``SessionDB``.

    All persistence flows through the injected ``db``: session phase lives in
    the pre-existing ``session_pipeline`` table (id, phase, data) addressed by
    raw SQL on ``db._conn``; artifacts go through ``insert_finding`` /
    ``insert_poc`` / ``insert_report``; audit rows go through
    ``append_phase_validation_log`` and are read back via
    ``get_phase_validation_logs``.
    """

    def __init__(self, db, now_fn=None):
        self.db = db
        self.now_fn = now_fn
        self._now_fn = now_fn if now_fn is not None else lambda: 0

    def create_session(self, session_id, target_info=None):
        state = {'session_id': session_id, 'phase': _PHASES[0], 'target': dict(target_info or {})}
        saver = getattr(self.db, 'save_session', None)
        if callable(saver):
            saver(session_id, state)
        return {'ok': True, 'session_id': session_id, 'phase': _PHASES[0]}

    def get_state(self, session_id):
        getter = getattr(self.db, 'get_session', None)
        state = getter(session_id) if callable(getter) else None
        if not isinstance(state, dict):
            return {'ok': False, 'status': 404, 'error': 'unknown session_id: %r' % (session_id,)}
        envelope = dict(state)
        envelope['ok'] = True
        envelope.setdefault('session_id', session_id)
        return envelope

    def submit_artifacts(self, session_id, phase, artifacts):
        accepted = 0
        rejected = []
        for index, raw in enumerate(artifacts or []):
            try:
                payload = self._coerce_payload(raw)
                kind = self._classify(payload, phase)
                obj = self._validate_artifact(kind, payload)
                self._persist_artifact(kind, payload, obj, session_id)
            except Exception as exc:
                message = str(exc) or repr(exc)
                rejected.append({'index': index, 'error': message})
                continue
            accepted += 1
        return {'ok': True, 'accepted': accepted, 'rejected': rejected}

    def transition(self, session_id, to_phase, approvals=None):
        state = self.get_state(session_id)
        if not state.get('ok'):
            return state
        current = state.get('phase')
        allowed = to_phase in self._allowed_targets(current)
        gr_ok, gr_error = self._evaluate_gate(session_id, current, to_phase)
        approved = True
        if approvals is not None:
            approved = self._truthy_approval(approvals)
        ok = bool(allowed and gr_ok and approved)
        if ok:
            audit_error = None
        elif not allowed:
            audit_error = 'transition not allowed: %r -> %r' % (current, to_phase)
        elif not gr_ok:
            audit_error = gr_error
        else:
            audit_error = 'approval rejected'
        record = {'from': current, 'to': to_phase, 'ok': ok, 'error': audit_error, 'at': self._now_fn()}
        self._append_audit(session_id, to_phase, record)
        if not ok:
            return {'ok': False, 'status': 422, 'error': self._as_text(audit_error, 'transition refused: %r -> %r' % (current, to_phase))}
        updated = dict(state)
        updated.pop('ok', None)
        updated['phase'] = to_phase
        saver = getattr(self.db, 'save_session', None)
        if callable(saver):
            saver(session_id, updated)
        return {'ok': True, 'session_id': session_id, 'from': current, 'to': to_phase}

    def _commit(self) -> None:
        commit = getattr(self.db._conn, 'commit', None)
        if callable(commit):
            try:
                commit()
            except Exception:
                pass

    def _load_session(self, session_id: Any) -> Optional[Dict[str, Any]]:
        try:
            cur = self.db._conn.execute("SELECT data FROM session_pipeline WHERE json_extract(data, '$.session_id') = ?", (session_id,))
            row = cur.fetchone()
        except Exception:
            return None
        if row is None:
            return None
        raw = self._row_value(row, 'data')
        if raw is None:
            return None
        try:
            parsed = json.loads(raw)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _advance(self, session_id: Any, target_spec: Any, to_phase: Any) -> None:
        data = {'session_id': session_id, 'target_spec': target_spec, 'phase': to_phase}
        self.db._conn.execute("UPDATE session_pipeline SET phase = ?, data = ? WHERE json_extract(data, '$.session_id') = ?", (to_phase, json.dumps(data, sort_keys=True), session_id))

    def _allowed_targets(self, current: Any) -> Tuple[Any, ...]:
        try:
            targets = _ALLOWED_TRANSITIONS.get(current, ())
        except Exception:
            return ()
        try:
            return tuple(targets)
        except Exception:
            return ()

    def _delegate_next_phase(self, current: Any) -> None:
        if _get_next_phase is None:
            return
        try:
            _get_next_phase(current)
        except Exception:
            pass

    def _evaluate_gate(self, session_id, current, to_phase):
        if _gate_transition is None:
            return (False, 'gate unavailable')
        rows = {'findings': self._load_table('findings'), 'pocs': self._load_table('pocs'), 'reports': self._load_table('reports')}
        try:
            result = _gate_transition(rows, current, to_phase)
        except Exception as exc:
            return (False, str(exc))
        gr_ok = bool(getattr(result, 'ok', False))
        gr_error = getattr(result, 'error', None)
        if gr_error is not None:
            gr_error = str(gr_error)
        return (gr_ok, gr_error)

    def _load_table(self, name):
        conn = getattr(self.db, '_conn', None)
        if conn is None:
            return []
        try:
            rows = conn.execute('SELECT data FROM ' + name).fetchall()
        except sqlite3.Error:
            return []
        loaded = []
        for row in rows:
            try:
                value = row['data']
            except (IndexError, KeyError, TypeError):
                value = row[0]
            try:
                parsed = json.loads(value)
            except (ValueError, TypeError):
                continue
            if isinstance(parsed, dict):
                loaded.append(parsed)
        return loaded

    @staticmethod
    def _row_value(row: Any, field_name: str) -> Any:
        try:
            return row[0]
        except Exception:
            pass
        try:
            return row[field_name]
        except Exception:
            return None

    def _append_audit(self, session_id, to_phase, record):
        log = getattr(self.db, 'append_phase_validation_log', None)
        if callable(log):
            self.db.append_phase_validation_log(session_id, to_phase, record)

    def _contract_for(self, kind: str) -> Any:
        mapping = {'finding': _Finding, 'poc': _PoC, 'report': _LiveTestReport}
        return mapping.get(kind)

    def _classify(self, data, phase):
        explicit = self._explicit_kind(data)
        if explicit is not None:
            return explicit
        structural = self._structural_kind(data)
        if structural is not None and structural != 'finding':
            return structural
        phase_kind = self._phase_to_kind(phase)
        if phase_kind is not None:
            return phase_kind
        return structural

    def _validate_artifact(self, kind, data):
        cls = _KIND_CLASSES.get(kind)
        if cls is None:
            raise ValueError('unknown artifact kind: %r' % (kind,))
        from_dict = getattr(cls, 'from_dict', None)
        if callable(from_dict):
            obj = from_dict(data)
        else:
            obj = cls(**data)
        validate = getattr(obj, 'validate', None)
        if callable(validate):
            validate()
        return obj

    @staticmethod
    def _interpret_validation(outcome: Any) -> Tuple[bool, Optional[str]]:
        if outcome is None or outcome is True:
            return (True, None)
        if outcome is False:
            return (False, 'validation failed')
        ok_attr = getattr(outcome, 'ok', _SENTINEL)
        if ok_attr is not _SENTINEL:
            if ok_attr:
                return (True, None)
            error = getattr(outcome, 'error', None)
            return (False, str(error) if error is not None else 'validation failed')
        if isinstance(outcome, str):
            return (False, outcome) if outcome.strip() else (True, None)
        if isinstance(outcome, (list, tuple, set)):
            errs = [str(e) for e in outcome]
            return (False, '; '.join(errs)) if errs else (True, None)
        if isinstance(outcome, dict):
            if outcome.get('ok') is True:
                return (True, None)
            if 'errors' in outcome:
                errs = outcome['errors']
                if not isinstance(errs, (list, tuple, set)):
                    errs = [errs] if errs else []
                errs = [str(e) for e in errs]
                return (False, '; '.join(errs)) if errs else (True, None)
            if 'error' in outcome and outcome['error']:
                return (False, str(outcome['error']))
            return (True, None)
        return (True, None) if outcome else (False, 'validation failed')

    def _persist_artifact(self, kind: str, raw: Dict[str, Any], obj: Any, session_id: Any=None) -> None:
        helpers = {'finding': getattr(self.db, 'insert_finding', None), 'poc': getattr(self.db, 'insert_poc', None), 'report': getattr(self.db, 'insert_report', None)}
        helper = helpers.get(kind)
        if helper is None:
            return
        payload = dict(raw)
        if session_id is not None and 'session_id' not in payload:
            payload['session_id'] = session_id
        candidates = [payload, obj] if obj is not None else [payload]
        last_exc: Optional[Exception] = None
        for candidate in candidates:
            try:
                helper(candidate)
                return
            except TypeError as exc:
                last_exc = exc
                continue
        if last_exc is not None:
            raise last_exc

    @staticmethod
    def _as_text(value: Optional[str], default: str) -> str:
        if value is None:
            return default
        text = str(value)
        return text if text.strip() else default

    def _load(self, session_id: Any) -> Any:
        """Load the raw session object for ``session_id`` or ``None``."""
        db = self.db
        if db is None:
            return None
        for name in ('get_session', 'load_session', 'read_session', 'fetch_session', 'load', 'get', 'read', 'fetch'):
            accessor = getattr(db, name, None)
            if callable(accessor):
                try:
                    result = accessor(session_id)
                except Exception:
                    continue
                if result is not None:
                    return result
        if isinstance(db, dict):
            return db.get(session_id)
        sessions = getattr(db, 'sessions', None)
        if isinstance(sessions, dict):
            return sessions.get(session_id)
        return None

    @staticmethod
    def _as_dict(session: Any) -> Optional[Dict[str, Any]]:
        """Coerce a loaded session object into a mutable ``dict`` view."""
        if session is None:
            return None
        if isinstance(session, dict):
            return session
        data = getattr(session, 'data', None)
        if isinstance(data, dict):
            return data
        if hasattr(session, '__dict__') and isinstance(session.__dict__, dict):
            return session.__dict__
        return None

    def _save(self, session_id: Any, data: Dict[str, Any]) -> None:
        """Persist ``data`` back into the session store, best-effort."""
        db = self.db
        if db is None:
            return
        for name in ('save_session', 'update_session', 'write_session', 'store_session', 'save', 'update', 'put', 'write', 'set', 'store'):
            mutator = getattr(db, name, None)
            if callable(mutator):
                try:
                    mutator(session_id, data)
                    return
                except TypeError:
                    try:
                        mutator(data)
                        return
                    except Exception:
                        continue
                except Exception:
                    continue
        if isinstance(db, dict):
            db[session_id] = data

    @staticmethod
    def _extract_phase(data: Dict[str, Any]) -> Optional[str]:
        if not isinstance(data, dict):
            return None
        for name in ('phase', 'current_phase', 'state'):
            value = data.get(name)
            if isinstance(value, str):
                return value
        pipeline = data.get('pipeline')
        if isinstance(pipeline, dict):
            for name in ('phase', 'current_phase', 'state'):
                value = pipeline.get(name)
                if isinstance(value, str):
                    return value
        return None

    @staticmethod
    def _set_phase(data: Dict[str, Any], phase: str) -> None:
        data['phase'] = phase
        pipeline = data.get('pipeline')
        if isinstance(pipeline, dict):
            pipeline['phase'] = phase

    @staticmethod
    def _artifacts(data: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = data.get('artifacts')
        if isinstance(artifacts, dict):
            return artifacts
        return data

    @staticmethod
    def _next_phase(phase: str) -> Optional[str]:
        try:
            idx = PHASE_ORDER.index(phase)
        except ValueError:
            return None
        if idx + 1 < len(PHASE_ORDER):
            return PHASE_ORDER[idx + 1]
        return None

    @staticmethod
    def _record(transitions: List[Dict[str, str]], frm: str, to: str) -> None:
        transitions.append({'from': frm, 'to': to})

    def get_current_phase(self, session_id: Any) -> Any:
        """Return the current lifecycle phase string for ``session_id``.

        Returns a 404 envelope dict when the session does not exist.
        """
        data = self._as_dict(self._load(session_id))
        if data is None:
            return _not_found(session_id)
        phase = self._extract_phase(data)
        if phase is None:
            phase = PHASE_ORDER[0]
        return phase

    def get_parked_package(self, session_id: Any) -> Any:
        """Return the parked turn-in-ready package dict, or ``None``.

        Returns a 404 envelope dict when the session does not exist.
        """
        data = self._as_dict(self._load(session_id))
        if data is None:
            return _not_found(session_id)
        for name in ('parked_package', 'parked_submission_package', 'submission_package', 'turn_in_package'):
            value = data.get(name)
            if isinstance(value, dict):
                return value
        pipeline = data.get('pipeline')
        if isinstance(pipeline, dict):
            for name in ('parked_package', 'parked_submission_package', 'submission_package', 'turn_in_package'):
                value = pipeline.get(name)
                if isinstance(value, dict):
                    return value
        return None

    def get_readiness_reason(self, session_id: Any) -> Any:
        """Return the missing-artifact readiness reason, or ``None`` if ready.

        Delegates to :func:`ngv2.submission_readiness_gate.readiness` when
        available and falls back to a deterministic artifact-precedence scan.
        Returns a 404 envelope dict when the session does not exist.
        """
        data = self._as_dict(self._load(session_id))
        if data is None:
            return _not_found(session_id)
        return self._compute_readiness_reason(data)

    def _compute_readiness_reason(self, data: Dict[str, Any]) -> Optional[str]:
        artifacts = self._artifacts(data)
        if _readiness_gate is not None:
            gate_fn = getattr(_readiness_gate, 'readiness', None)
            if callable(gate_fn):
                result = self._call_readiness(gate_fn, data, artifacts)
                reason = self._reason_from_result(result)
                if reason is not _MISSING:
                    return reason
        for ident in _REQUIRED_ARTIFACTS:
            if not self._has_artifact(artifacts, ident):
                return ident
        return None

    @staticmethod
    def _has_artifact(artifacts: Dict[str, Any], ident: str) -> bool:
        if not isinstance(artifacts, dict):
            return False
        return bool(artifacts.get(ident))

    @staticmethod
    def _call_readiness(gate_fn: Callable[..., Any], data: Any, artifacts: Any) -> Any:
        for args in ((data,), (artifacts,), (data, artifacts)):
            try:
                return gate_fn(*args)
            except TypeError:
                continue
            except Exception:
                return _MISSING
        return _MISSING

    @staticmethod
    def _reason_from_result(result: Any) -> Any:
        if result is _MISSING:
            return _MISSING
        if result is None:
            return None
        if isinstance(result, bool):
            return None
        if isinstance(result, str):
            return result or None
        if isinstance(result, dict):
            if result.get('ready') is True:
                return None
            for name in ('reason', 'missing', 'missing_artifact', 'detail', 'message'):
                value = result.get(name)
                if isinstance(value, str) and value:
                    return value
            return None
        if isinstance(result, (tuple, list)) and len(result) >= 2:
            if result[0] is True:
                return None
            if isinstance(result[1], str) and result[1]:
                return result[1]
            return None
        if getattr(result, 'ready', None) is True:
            return None
        reason = getattr(result, 'reason', None)
        if isinstance(reason, str) and reason:
            return reason
        return None

    def advance(self, session_id, approval_decision=None):
        data = self._as_dict(self._load(session_id))
        if data is None:
            return _not_found(session_id)
        phase = self._extract_phase(data) or PHASE_ORDER[0]
        transitions = []
        parked = False
        reason = None
        for _ in range(len(PHASE_ORDER) + 4):
            if phase == 'done':
                break
            if phase == MANUAL_REVIEW:
                parked = True
                reason = 'manual_review_required'
                break
            if phase == 'awaiting_submission':
                if self._is_approved(approval_decision):
                    self._record(transitions, phase, 'submitted')
                    phase = 'submitted'
                    continue
                parked = True
                reason = 'awaiting_operator_approval'
                break
            if phase == 'submitted':
                self._record(transitions, phase, 'done')
                phase = 'done'
                continue
            if phase == 'report':
                package = self._build_package(data)
                data['parked_package'] = package
                missing = self._compute_readiness_reason(data)
                if missing is not None:
                    parked = True
                    reason = missing
                    break
                self._record(transitions, 'report', 'awaiting_submission')
                phase = 'awaiting_submission'
                continue
            nxt = self._next_phase(phase)
            if nxt is None:
                break
            self._record(transitions, phase, nxt)
            phase = nxt
        self._set_phase(data, phase)
        self._save(session_id, data)
        return {'ok': True, 'session_id': session_id, 'phase': phase, 'parked': parked, 'reason': reason, 'transitions': transitions}

    @staticmethod
    def _build_package(data: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = SessionApi._artifacts(data)
        package: Dict[str, Any] = {}
        for ident in ('report', 'poc', 'novelty', 'confidence', 'triage', 'detonation'):
            if isinstance(artifacts, dict):
                package[ident] = artifacts.get(ident)
            else:
                package[ident] = None
        return package

    @staticmethod
    def _is_approved(approval_decision: Any) -> bool:
        if approval_decision is None:
            return False
        if _approval_gate is not None:
            for name in ('is_approved', 'approved', 'check_approval', 'evaluate', 'decide', 'check', 'gate'):
                gate_fn = getattr(_approval_gate, name, None)
                if callable(gate_fn):
                    try:
                        result = gate_fn(approval_decision)
                    except TypeError:
                        continue
                    except Exception:
                        return False
                    return SessionApi._truthy_approval(result)
        return SessionApi._truthy_approval(approval_decision)

    @staticmethod
    def _truthy_approval(value):
        if value is True:
            return True
        if value is False or value is None:
            return False
        if isinstance(value, str):
            return value.strip().lower() in _APPROVE_LABELS
        if isinstance(value, dict):
            if value.get('approved') is True:
                return True
            for name in ('decision', 'status', 'verdict', 'result'):
                decision = value.get(name)
                if isinstance(decision, str) and decision.strip().lower() in _APPROVE_LABELS:
                    return True
            return False
        if getattr(value, 'approved', None) is True:
            return True
        for name in ('decision', 'status', 'verdict', 'result'):
            decision = getattr(value, name, None)
            if isinstance(decision, str) and decision.strip().lower() in _APPROVE_LABELS:
                return True
        return False
    'Read/advance surface over the session pipeline.\n\n    The API is intentionally tolerant of the concrete shape of the injected\n    session store: it probes a small set of conventional accessor methods so it\n    works against the real ``SessionDB`` as well as a plain mapping of sessions.\n    '

    def _normalize_kind(self, value):
        token = value.strip().lower()
        if token in ('finding', 'poc', 'report'):
            return token
        if token in ('findings',):
            return 'finding'
        if token in ('pocs', 'exploit'):
            return 'poc'
        if token in ('reports', 'live', 'livetestreport', 'live_test_report'):
            return 'report'
        return None

    def _explicit_kind(self, data):
        if not isinstance(data, dict):
            return None
        for field_name in _DISCRIMINATOR_FIELDS:
            value = data.get(field_name)
            if isinstance(value, str):
                normalized = self._normalize_kind(value)
                if normalized is not None:
                    return normalized
        return None

    def _phase_to_kind(self, phase):
        if phase is None:
            return None
        return _PHASE_KIND.get(str(phase).strip().lower())

    def _structural_kind(self, data):
        if not isinstance(data, dict):
            return 'finding'
        keys = set(data.keys())
        if {'poc_finding_id', 'verdict'} & keys:
            return 'report'
        if {'language', 'entrypoint', 'code'} & keys:
            return 'poc'
        return 'finding'

    def _coerce_payload(self, raw):
        if isinstance(raw, dict):
            return dict(raw)
        to_dict = getattr(raw, 'to_dict', None)
        if callable(to_dict):
            data = to_dict()
            if isinstance(data, dict):
                return dict(data)
        raise TypeError('artifact is not a mapping')

    def _gate_transition(self, rows, current, to_phase):
        return {'ok': True, 'allowed': True, 'reasons': []}
__all__ = ['SessionApi', 'PHASE_ORDER', 'MANUAL_REVIEW']
PHASE_ORDER: Tuple[str, ...] = ('source', 'hunt', 'triage', 'verify', 'poc', 'detonate', 'novelty', 'report', 'awaiting_submission', 'submitted', 'done')
MANUAL_REVIEW: str = 'manual_review'
HALT_PHASES = frozenset({'awaiting_submission', 'done', MANUAL_REVIEW})
_REQUIRED_ARTIFACTS: Tuple[str, ...] = ('confidence', 'triage', 'verify', 'poc', 'detonation', 'novelty', 'report')
_APPROVE_LABELS = frozenset({'approve', 'approved', 'accept', 'accepted', 'yes', 'ok'})
_MISSING = object()

def _not_found(session_id: Any) -> Dict[str, Any]:
    """Return the canonical 404 envelope for an unknown session."""
    return {'error': 'session_not_found', 'status': 404, 'session_id': session_id}

def is_error(value: Any) -> bool:
    """Return ``True`` when ``value`` is a 404 error envelope."""
    return isinstance(value, dict) and value.get('status') == 404
'Session API surface for the NobleGreedv2 lifecycle.\n\nAdditively extends :class:`SessionApi` to expose the full set of lifecycle\nphases (``source`` -> ... -> ``done`` plus ``manual_review``) together with the\nread operations (current phase, parked submission package, readiness reason)\nand an autonomous :meth:`SessionApi.advance` driver.  ``advance`` runs the\nautonomous transitions in a loop until it halts at ``awaiting_submission`` or\n``done`` (or until a gate fails).  The ``awaiting_submission`` -> ``submitted``\ntransition is gated behind an injected operator approval decision evaluated by\n:mod:`ngv2.human_approval_gate`.\n\nThe module is pure and deterministic: it performs no network, wall-clock,\nrandomness, or subprocess calls, and imports only the standard library plus\nsibling ``ngv2`` modules.\n'
try:
    from ngv2 import submission_readiness_gate as _readiness_gate
except Exception:
    _readiness_gate = None
try:
    from ngv2 import human_approval_gate as _approval_gate
except Exception:
    _approval_gate = None
try:
    from ngv2 import state_machine as _state_machine
except Exception:
    _state_machine = None
try:
    from ngv2 import session_gate as _session_gate
except Exception:
    _session_gate = None
try:
    from ngv2 import session_db as _session_db
except Exception:
    _session_db = None
import sqlite3
from ngv2.contracts import Finding
from ngv2.contracts import PoC
from ngv2.contracts import LiveTestReport
from ngv2.contracts import SEVERITIES
from ngv2.contracts import VERDICTS
_PHASES = ('hunt', 'triage', 'poc', 'detonate', 'report', 'done')
_PHASE_KIND = {'hunt': 'finding', 'triage': 'finding', 'poc': 'poc', 'detonate': 'report', 'report': 'report'}
_DISCRIMINATOR_FIELDS = ('artifact_type', 'kind', 'type', 'contract', '_type', 'category')
_KIND_CLASSES = {'finding': Finding, 'poc': PoC, 'report': LiveTestReport}
'High-level session API over the SQLite SessionDB for the bounty FSM.\n\nValidates submitted artifacts against the contract dataclasses, classifies them\nby pipeline phase, stamps the owning ``session_id`` into the payload before\npersisting, and converts any persist failure (duplicate id / constraint\nviolation / handler ValueError) into a rejected entry instead of raising.\n'