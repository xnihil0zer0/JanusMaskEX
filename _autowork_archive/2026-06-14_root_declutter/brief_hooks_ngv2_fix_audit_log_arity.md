---
interfaces: "edits ngv2/session_api.py SessionApi._append_audit to call the rewritten SessionDB audit writer with its actual positional contract — append_phase_validation_log(session_id, to_phase, record) instead of the stale legacy-kwarg call append_phase_validation_log(record, phase=to_phase) that raises TypeError: append_phase_validation_log() missing 1 required positional argument: 'entry' on EVERY audited transition attempt — and edits ngv2/session_db.py SessionDB.get_phase_validation_logs to make session_id optional (None -> all audit rows in id order) so the committed oracle's no-arg read-back works"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/session_api.py + ngv2/session_db.py — fix the audit-log arity mismatch: `SessionApi._append_audit` (session_api.py:234) still calls `self.db.append_phase_validation_log(record, phase=to_phase)` but the rewritten `SessionDB.append_phase_validation_log` (session_db.py:257) signature is `(session_id, phase, entry)`, so EVERY transition attempt dies with `TypeError` before the audit row is written; also make `get_phase_validation_logs`'s `session_id` optional so the oracle's zero-arg read-back returns all rows

# Scope

EDIT the EXISTING modules ngv2/session_api.py and ngv2/session_db.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). DISPATCH ORDER: dispatch this brief FIRST of the three session-stack fixes (before `ngv2_reconcile_sessiondb_contract` and `ngv2_fix_gate_transition_backcompat`) — it is standalone-green on its oracle and the sibling briefs' whole-class patches must include this brief's corrected lines.

DEFECT (verified against NGv2 HEAD `44bfb3c`, 2026-06-11): the SessionDB rewrite changed the audit writer's signature but the production caller was never updated. Current source, ngv2/session_api.py lines 227-234:

    def _append_audit(self, session_id: Any, from_phase: Any, to_phase: Any, ok: bool, error: Optional[str]) -> None:
        record: Dict[str, Any] = {'session_id': session_id, 'from': from_phase, 'to': to_phase, 'ok': ok, 'error': error}
        if self.now_fn is not None:
            try:
                record['ts'] = self.now_fn()
            except Exception:
                pass
        self.db.append_phase_validation_log(record, phase=to_phase)

Current source, ngv2/session_db.py lines 257-262:

    def append_phase_validation_log(self, session_id, phase, entry):
        payload = json.dumps(entry, sort_keys=True)
        return self._write(
            "INSERT INTO phase_validation_logs (session_id, phase, data) VALUES (?, ?, ?)",
            (session_id, phase, payload),
        )

The call binds `record` to `session_id` and `to_phase` to `phase` and leaves `entry` unbound → `TypeError: append_phase_validation_log() missing 1 required positional argument: 'entry'` raised out of `SessionApi.transition` on EVERY attempt (allowed, disallowed, and gate-fail alike), before any audit row can be written. Additionally the committed oracle reads the audit back with NO argument — `api.db.get_phase_validation_logs()` (tests/ngv2/test_session_api_audit_now_fn_wired.py line 76; also tests/ngv2/test_session_api_wired.py lines 192/203/218/229/240) — but the rewritten accessor (session_db.py lines 264-275) REQUIRES `session_id`:

    def get_phase_validation_logs(self, session_id):
        rows = self._conn.execute(
            "SELECT data FROM phase_validation_logs WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        ...

THE FIX (data_model — two one-spot corrections, no behavior redesign):

(1) ngv2/session_api.py — `_append_audit`'s last line becomes the canonical positional call (the `record` already carries `session_id`); EXACT corrected line (the ONLY change in this file):

    self.db.append_phase_validation_log(session_id, to_phase, record)

(2) ngv2/session_db.py — `get_phase_validation_logs` gains `session_id=None`; `None` returns ALL audit rows ordered by id; a provided session_id keeps today's filtered query byte-for-byte. EXACT corrected method (the ONLY change in this file):

    def get_phase_validation_logs(self, session_id=None):
        if session_id is None:
            rows = self._conn.execute(
                "SELECT data FROM phase_validation_logs ORDER BY id ASC"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT data FROM phase_validation_logs WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        logs = []
        for row in rows:
            try:
                logs.append(json.loads(row["data"]))
            except (ValueError, TypeError):
                continue
        return logs

Read the read-only staged targets at `{WORK_DIR}/inbox/targets/ngv2/session_api.py` and `{WORK_DIR}/inbox/targets/ngv2/session_db.py` FIRST and reproduce everything else byte-for-byte. NO new imports are needed in either file. Verify GREEN with `python -m pytest tests/ngv2/test_session_api_audit_now_fn_wired.py -q`; working_dir is /home/xnihil0zer0/NobleGreedv2. (NOTE: after this fix the headline oracle test passes even though the gate is still broken — `_evaluate_gate` catches the gate's `unhashable type: 'dict'` TypeError and audits the attempt as a failed transition; the gate itself is the sibling brief `ngv2_fix_gate_transition_backcompat`.)

DISPATCH DIRECTIVE — PATCH FORMAT (whole-symbol patches on EXISTING 1-part top-level classes — the canonical safe shape; class METHODS are NEVER patched as dotted symbols): emit a single top-level `__JANUSMASK_PATCHES__` list with EXACTLY TWO entries:

    __JANUSMASK_PATCHES__ = [
        {'file': 'ngv2/session_api.py', 'kind': 'symbol', 'name': 'SessionApi',
         'code': r'''<the ENTIRE class SessionApi reproduced BYTE-FOR-BYTE from the staged target, with ONLY the final line of _append_audit changed to: self.db.append_phase_validation_log(session_id, to_phase, record)>'''},
        {'file': 'ngv2/session_db.py', 'kind': 'symbol', 'name': 'SessionDB',
         'code': r'''<the ENTIRE class SessionDB reproduced BYTE-FOR-BYTE from the staged target, with ONLY get_phase_validation_logs replaced by the corrected method pinned in Scope>'''},
    ]

Each `name` MUST be the 1-part TOP-LEVEL class name (`'SessionApi'`, `'SessionDB'`) — never a dotted qualname (never `SessionApi._append_audit`), never a manifest, never a whole-file rewrite, never any extra top-level node, NO new imports. The emitted `code` for each entry must reproduce the WHOLE class from the staged target BYTE-FOR-BYTE with ONLY the pinned change — every other method, docstring, and the trailing in-class string literal of `SessionApi` ('Read/advance surface over the session pipeline...', line 666) must survive intact. POST-EMIT SELF-CHECK (mandatory, guards against silent truncation of large symbols): the emitted `SessionApi` code must START with `class SessionApi:` at column 0, contain EXACTLY 40 `def ` occurrences (the class has 40 methods — count them), contain the corrected line `self.db.append_phase_validation_log(session_id, to_phase, record)` and NOT contain `phase=to_phase`, and end with the `_truthy_approval` method followed by the trailing class-docstring string literal; the emitted `SessionDB` code must START with `class SessionDB:` at column 0, contain EXACTLY 21 `def ` occurrences, contain `def get_phase_validation_logs(self, session_id=None):`, and keep `def append_phase_validation_log(self, session_id, phase, entry):` UNCHANGED.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM: `task_id`: `ngv2-fix-audit-log-arity`. meta_task_type=`data_model` (external NGv2 target — the diff-fuzzer cannot resolve external imports, so use a fuzzer-bypassed, smoke-gated meta-type). priority: high. dependencies: []. working_dir: `/home/xnihil0zer0/NobleGreedv2`. files_touched: `["ngv2/session_api.py", "ngv2/session_db.py"]` ONLY. partial_edit semantics: a single `__JANUSMASK_PATCHES__` list with EXACTLY TWO `'symbol'` entries whose `name`s are the 1-part top-level `'SessionApi'` and `'SessionDB'` (whole-class replacements per the DISPATCH DIRECTIVE — never dotted, never a manifest, never a whole-file rewrite, no extra nodes). The DISPATCH DIRECTIVE — PATCH FORMAT paragraph above MUST be copied VERBATIM into the task's `implementation_notes` so the blind worker sees it. verification_command: `python -m pytest tests/ngv2/test_session_api_audit_now_fn_wired.py -q`. The committed RED oracle tests/ngv2/test_session_api_audit_now_fn_wired.py (1 failing of 3 today) is the authoritative acceptance contract — make it FULLY GREEN; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from the committed oracle tests/ngv2/test_session_api_audit_now_fn_wired.py (plan descriptors referencing committed/landed tests — this does NOT authorize authoring new tests), so every `spec.edge_cases` entry is reflected per the validator's edge-case rule (e.g. `test_transition_runs_append_audit_without_attributeerror` and `test_unknown_session_transition_does_not_touch_now_fn`; also good: `test_default_construction_has_now_fn_attribute`).

# Non-Goals

This is an EDIT and integration is out of scope: the task's non_goals MUST declare integration testing out of scope — do NOT add integration/e2e tests; this fix is verified solely by the committed unit oracle tests/ngv2/test_session_api_audit_now_fn_wired.py. Do NOT author or modify any test — that oracle is committed and authoritative. Change ONLY the two pinned spots: `_append_audit`'s final call line in SessionApi, and `get_phase_validation_logs`'s signature/no-filter branch in SessionDB. Do NOT change `append_phase_validation_log` itself (its `(session_id, phase, entry)` signature is the canonical contract this brief conforms the caller TO — do not add shape-sniffing/back-compat kwargs to it). Do NOT change the audit `record` dict's keys ({'session_id','from','to','ok','error'} plus optional 'ts'), the `now_fn` branch, `transition`'s flow, `_evaluate_gate` (its still-broken legacy gate call is the sibling brief `ngv2_fix_gate_transition_backcompat`), `_load_table`'s `'live_test_reports'` name or `submit_artifacts`/`_persist_artifact` (those are the sibling brief `ngv2_reconcile_sessiondb_contract`), the phase_validation_logs DDL, or any other method of either class. Do NOT add new imports, network, wall-clock, randomness, or third-party dependencies. Do NOT touch ngv2/session_gate.py, ngv2/state_machine.py, ngv2/contracts.py, or any other module. Currently-green tests over these classes (tests/ngv2/test_session_api_surface_wired.py, test_session_api_persistence_wired.py, test_persist_submission_sessiondb_wired.py, test_session_mcp_wired.py's create/build_tools tests) MUST STAY GREEN — hence byte-for-byte reproduction outside the two pinned spots.

# Inputs

The committed authoritative RED oracle tests/ngv2/test_session_api_audit_now_fn_wired.py (NGv2 HEAD `44bfb3c`; fail count confirmed live 2026-06-11: 1 failing, 2 passing). The failing case `test_transition_runs_append_audit_without_attributeerror` constructs `SessionApi(SessionDB(tmp))` exactly as production `_e2e_run/drive.py` does, calls `api.create_session('s1', ...)` then `api.transition('s1', 'triage')` — which today raises `TypeError` at ngv2/session_api.py:234 — and then reads the audit back with `api.db.get_phase_validation_logs()` (NO argument), asserting the last row has `from == 'hunt'`, `to == 'triage'`, and no `'ts'` key (default `now_fn=None` omits the timestamp). The passing cases `test_default_construction_has_now_fn_attribute` and `test_unknown_session_transition_does_not_touch_now_fn` (404 returns BEFORE `_append_audit`) must stay green.

The EXACT current defective sources are quoted in Scope: ngv2/session_api.py lines 227-234 (`_append_audit`, defective final line `self.db.append_phase_validation_log(record, phase=to_phase)`) and ngv2/session_db.py lines 257-275 (`append_phase_validation_log(session_id, phase, entry)` — correct, untouched — and `get_phase_validation_logs(session_id)` — required-arg, to be made optional). The `record` built by `_append_audit` already carries `session_id` as a key, so passing the loose `session_id` positionally plus the whole `record` as `entry` loses nothing. The `phase_validation_logs` table (session_db.py lines 154-161: `id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, phase TEXT, data TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(data))`) is READ-ONLY context — do not edit the DDL in this brief. stdlib + ngv2 only.

# Deliverables

Edited ngv2/session_api.py whose `SessionApi._append_audit` ends with the canonical positional call `self.db.append_phase_validation_log(session_id, to_phase, record)` and edited ngv2/session_db.py whose `SessionDB.get_phase_validation_logs(session_id=None)` returns ALL audit rows (id order) when called with no argument while preserving the filtered query when a session_id is given — everything else in both classes byte-for-byte unchanged — so every transition attempt (allowed, disallowed, gate-fail) durably writes its audit row instead of raising TypeError, and the committed read-back contract works. Verified GREEN by `python -m pytest tests/ngv2/test_session_api_audit_now_fn_wired.py -q`.
