---
interfaces: "edits ngv2/session_api.py SessionApi.__init__ to initialize self.now_fn (injectable, default None) before _append_audit reads it, fixing the AttributeError raised on every transition() audit write"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/session_api.py — initialize `SessionApi.now_fn` in `__init__` so `_append_audit` no longer raises `AttributeError` on every transition attempt

# Scope

EDIT the EXISTING module ngv2/session_api.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). The audit-timestamp branch in `_append_audit` (~line 228) reads `if self.now_fn is not None:`, but `SessionApi.__init__` (~line 60, `def __init__(self, db: Any=None) -> None:`) NEVER initializes a `now_fn` attribute — the audit-timestamp support was added to `_append_audit` without updating the constructor. `_append_audit` is reached on EVERY `transition` attempt (the audit row is written for allowed, disallowed, and gate-fail transitions alike, BEFORE any return), so constructing the handler exactly the way production does — `api = SessionApi(db)` (see `_e2e_run/drive.py` line 94, no `now_fn` kwarg) — and calling `api.transition(sid, to_phase)` raises `AttributeError: 'SessionApi' object has no attribute 'now_fn'` inside `_append_audit` (confirmed live via `_e2e_run/drive.py` line 114). The SINGLE behavioral change is to make `self.now_fn` a well-defined attribute set at construction: add an injectable `now_fn` parameter to `__init__` defaulting to `None` and assign `self.now_fn = now_fn`, so the existing `_append_audit` branch (`if self.now_fn is not None:` → stamp `record['ts'] = self.now_fn()`) is well-defined and, for the default (no-kwarg) construction, simply omits the optional `'ts'` key. Read ngv2/session_api.py FIRST (the `__init__` at ~line 60 and `_append_audit` at ~lines 226-233) to scope the exact minimal edit. Do NOT change any logic, signature, or return value of `transition`, `_append_audit`, `create_session`, `submit_artifacts`, or any other method beyond adding the `now_fn` parameter/assignment to `__init__`. Keep it pure/deterministic (no clock, randomness, network, subprocess; the timestamp source stays injected, never a wall-clock default). Verify GREEN with `python -m pytest tests/ngv2/test_session_api_audit_now_fn_wired.py -q`; working_dir is /home/xnihil0zer0/NobleGreedv2.

# Non-Goals

This is an EDIT and integration is out of scope: do NOT add integration/e2e tests — this is purely an `__init__`-initialization fix verified by the committed unit oracle tests/ngv2/test_session_api_audit_now_fn_wired.py; the task's `non_goals` MUST declare integration testing out of scope. Do NOT author or modify any test — that oracle is committed and authoritative. Do NOT change the behavior, logic, signatures, or return values of `transition`, `_append_audit`, `create_session`, `get_state`, `submit_artifacts`, `_evaluate_gate`, `_classify`, `_advance`, `advance`, or any other method beyond adding the injectable `now_fn` parameter to `__init__` and assigning `self.now_fn`. Do NOT default `now_fn` to a real clock (e.g. `time.time`, `datetime.now`) — it MUST default to `None` so the default construction stays deterministic and omits the `'ts'` key; preserve the exact `_append_audit` branch semantics (`if self.now_fn is not None:` → `record['ts'] = self.now_fn()` guarded by try/except). Do NOT touch ngv2/session_gate.py (a separate import-ordering fix is in flight — do not import it, do not depend on it), ngv2/session_db.py, ngv2/contracts.py, ngv2/state_machine.py, or any other module — edit ngv2/session_api.py ONLY. Do NOT add any new module-level symbol; no network, no wall-clock, no randomness, no third-party imports.

# Inputs

The committed authoritative oracle at tests/ngv2/test_session_api_audit_now_fn_wired.py (constructs `SessionApi(db)` over a real `ngv2.session_db.SessionDB` exactly as production `_e2e_run/drive.py` line 94 does — positional `db` only, NO `now_fn` kwarg workaround — then: asserts `hasattr(api, 'now_fn')` and `api.now_fn is None` after default construction; calls `api.transition('s1', 'triage')` and asserts it returns a dict WITHOUT raising, that an audit row was persisted via `db.get_phase_validation_logs()` with `from=='hunt'`/`to=='triage'`, and that the optional `'ts'` key is absent under the default construction; and asserts an unknown-session transition still returns a 404 envelope before `_append_audit` is reached). It deliberately does NOT import `ngv2.session_gate` (un-importable, fix in flight); the now_fn defect surfaces in `_append_audit` regardless of gate availability because the audit row is always written before the gate verdict is consulted.

The EXACT current `__init__` to edit (ngv2/session_api.py ~line 60):

```python
    def __init__(self, db: Any=None) -> None:
        self.db = db
```

The EXACT current `_append_audit` whose branch the fix must keep well-defined (ngv2/session_api.py ~lines 226-233 — DO NOT change it):

```python
    def _append_audit(self, session_id: Any, from_phase: Any, to_phase: Any, ok: bool, error: Optional[str]) -> None:
        record: Dict[str, Any] = {'session_id': session_id, 'from': from_phase, 'to': to_phase, 'ok': ok, 'error': error}
        if self.now_fn is not None:
            try:
                record['ts'] = self.now_fn()
            except Exception:
                pass
        self.db.append_phase_validation_log(record, phase=to_phase)
```

The module docstring already specifies the intended contract: "Any timestamp comes from an injected `now_fn` (and is omitted entirely when none is supplied)". stdlib + ngv2 only.

# Deliverables

Edited ngv2/session_api.py in which `SessionApi.__init__` initializes `self.now_fn` from an injectable parameter defaulting to `None` (e.g. `def __init__(self, db: Any=None, now_fn: Optional[Callable[[], Any]]=None) -> None:` with `self.now_fn = now_fn`), so that `SessionApi(db)` (the production construction) leaves `now_fn` as `None` and `api.transition(sid, to_phase)` no longer raises `AttributeError: 'SessionApi' object has no attribute 'now_fn'` — the audit row is written deterministically on every transition attempt, with the optional `'ts'` key omitted under the default construction — and with NO change to any other method's logic, signature, or return value, and no import of or dependency on ngv2/session_gate. Verified GREEN by `python -m pytest tests/ngv2/test_session_api_audit_now_fn_wired.py -q`.
