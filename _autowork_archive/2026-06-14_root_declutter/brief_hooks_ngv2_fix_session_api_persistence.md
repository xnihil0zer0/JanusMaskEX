---
interfaces: "edits ngv2/session_db.py to add two persistence accessors — get_session(session_id) and save_session(session_id, data) — on class SessionDB, backed by the existing session_pipeline table (keyed by json_extract(data, '$.session_id')), so SessionApi._load/_save find a real store and the bounty-lifecycle FSM (advance/get_current_phase/get_parked_package/get_readiness_reason) persists over a bare SessionDB instead of returning 404"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/session_db.py — add `get_session` / `save_session` accessors to `SessionDB` (persisting FSM working-state in the existing `session_pipeline` table) so `SessionApi.advance()` / `get_current_phase()` work over a bare, un-subclassed `SessionDB` instead of 404ing

# Scope

EDIT the EXISTING module ngv2/session_db.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). DEFECT (verified live): `ngv2.session_api.SessionApi` has TWO DISJOINT storage paths. Its legacy surface (`create_session`/`get_state`/`transition`) persists through the SQL `session_pipeline` table via raw SQL on `db._conn`, keyed by `json_extract(data, '$.session_id')`. But its extended bounty-lifecycle FSM surface (`advance`/`get_current_phase`/`get_parked_package`/`get_readiness_reason`) reads/writes the session through `SessionApi._load`/`SessionApi._save`, which only PROBE the injected store for conventional accessor methods — `_load` tries `('get_session', 'load_session', 'read_session', 'fetch_session', 'load', 'get', 'read', 'fetch')` and `_save` tries `('save_session', 'update_session', 'write_session', 'store_session', 'save', 'update', 'put', 'write', 'set', 'store')`. The real `SessionDB` exposes NONE of these names, so `_load` returns None, `advance()`/`get_current_phase()` return the 404 envelope `{'error': 'session_not_found', 'status': 404, ...}` over a real DB, and `_save` silently no-ops — the FSM is in-memory-only and never persistence-wired. THE FIX: add exactly TWO public methods to `class SessionDB` in ngv2/session_db.py: (1) `get_session(self, session_id)` — `SELECT data FROM session_pipeline WHERE json_extract(data, '$.session_id') = ?`, return the `json.loads`-parsed dict (or None on miss/parse failure/non-dict); (2) `save_session(self, session_id, data)` — serialize `data` with `json.dumps(data, sort_keys=True)`, extract `phase = data.get('phase')` when `data` is a dict (else None), then UPDATE the matching row (`UPDATE session_pipeline SET phase = ?, data = ? WHERE json_extract(data, '$.session_id') = ?`) and, if `cur.rowcount == 0`, INSERT a new row (`INSERT INTO session_pipeline (phase, data) VALUES (?, ?)`); route both writes through the existing `self._write(...)` helper so they run inside the module's `BEGIN IMMEDIATE` transaction discipline (reads may use `self._conn.execute` directly, matching `get_finding`). Do NOT raise on a missing session in `get_session` — return None (that is what `SessionApi._load` expects). Keep the methods pure/deterministic (no clock, randomness, network, subprocess; stdlib only) and do NOT change any existing method, the schema/DDL, the pragmas, or any other module — in particular do NOT touch ngv2/session_api.py (its `_load`/`_save` probe lists already find `get_session`/`save_session` first; zero changes needed there). Read the read-only staged target at `{WORK_DIR}/inbox/targets/ngv2/session_db.py` FIRST for the exact class layout and the `_write` helper. Verify GREEN with `python -m pytest tests/ngv2/test_session_api_persistence_wired.py -q`; working_dir is /home/xnihil0zer0/NobleGreedv2.

LOUD DISPATCH DIRECTIVE — PATCH FORMAT (WHOLE-CLASS SYMBOL PATCH; class-METHOD patches are FORBIDDEN — the previous attempt of this exact task died `synthesis_or_ast_failed` on a dotted-anchor method patch with class-level indentation, `SyntaxError: unindent does not match any outer indentation level`): emit a single top-level `__JANUSMASK_PATCHES__` list with EXACTLY ONE entry:

    __JANUSMASK_PATCHES__ = [
        {'file': 'ngv2/session_db.py', 'kind': 'symbol', 'name': 'SessionDB',
         'code': r'''class SessionDB:
    ... the ENTIRE class, byte-for-byte, plus the two new methods at the end ...
'''},
    ]

The `name` MUST be the 1-part TOP-LEVEL name `'SessionDB'` — NEVER a dotted method qualname (NOT `'SessionDB.get_finding'`, NOT `'SessionDB.get_session'`): a dotted symbol patch can only REPLACE a method that already exists (a not-yet-existing method name raises KeyError, a code block whose leaf name differs from the anchor raises ValueError, and extra nodes are forbidden on dotted anchors — ValueError), and emitting method fragments carrying class-level indentation is exactly what produced the prior SyntaxError. Instead the `code` raw string MUST be the COMPLETE `class SessionDB:` block (starting at column 0) reproduced BYTE-FOR-BYTE from the read-only staged target at `{WORK_DIR}/inbox/targets/ngv2/session_db.py` (the class spans lines 109-269 at HEAD, ~161 lines), with the ONLY change being the two NEW methods `get_session(self, session_id)` and `save_session(self, session_id, data)` appended at the END of the class body (immediately after `__exit__`), indented one level (4 spaces) exactly like every sibling method. KNOWN GOTCHA — SYMBOL TRUNCATION: agents have deterministically truncated large symbol reproductions before. POST-EMIT SELF-CHECK (mandatory): your emitted `code` must START with `class SessionDB:` at column 0 and END with the final line of your new `save_session` method, and must still contain, byte-identical, the class docstring AND all 19 existing methods — `__init__`, `_configure_connection`, `_init_schema` (with its FULL five-table DDL `statements` block and FK/CHECK constraints), `_begin`, `_commit`, `_rollback`, `_write`, `insert_finding`, `get_finding`, `insert_poc`, `get_poc`, `insert_report`, `get_report`, `append_phase_validation_log`, `get_phase_validation_logs`, `_next_sequential_id`, `close`, `__enter__`, `__exit__`. If any of those is missing or paraphrased, you truncated — re-read the staged target and re-emit. Do NOT emit a `__JANUSMASK_MANIFEST__`, do NOT emit a whole-file rewrite, do NOT add any new top-level symbol or R-anchor extra nodes (the two new methods live INSIDE the reproduced class body), and do NOT touch any other top-level symbol (`_resolve_class`, `_resolve_seq`, `_to_dict`, `_from_dict`, `_pick`, `_quoted_set`, the module constants, the imports).

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the committed oracle and the auto-promote allowlist are keyed to this brief): `task_id`: `ngv2-sessiondb-add-session-accessors`. meta_task_type=`data_model` (external NGv2 target — the diff-fuzzer cannot resolve external imports, so keep a fuzzer-bypassed, smoke-gated meta-type). priority: high. dependencies: []. working_dir: `/home/xnihil0zer0/NobleGreedv2`. files_touched: `["ngv2/session_db.py"]` ONLY. partial_edit semantics: a single `__JANUSMASK_PATCHES__` list with EXACTLY ONE `'symbol'` entry whose `name` is the 1-part top-level `'SessionDB'` (the whole-class reproduction per the LOUD DISPATCH DIRECTIVE — never a dotted `SessionDB.<method>` patch, never a manifest, never a whole-file rewrite). The LOUD DISPATCH DIRECTIVE — PATCH FORMAT paragraph above MUST be copied VERBATIM into the task's `implementation_notes` so the blind worker sees it. verification_command: `python -m pytest tests/ngv2/test_session_api_persistence_wired.py -q`. The committed RED oracle tests/ngv2/test_session_api_persistence_wired.py (NGv2 commit 9016219) is the authoritative, variant-agnostic acceptance contract — make it GREEN; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from the committed oracle `tests/ngv2/test_session_api_persistence_wired.py` (plan descriptors referencing committed/landed tests — this does NOT authorize authoring new tests), so every `spec.edge_cases` entry is reflected per the validator's edge-case rule.

# Non-Goals

This is an EDIT and integration is out of scope: the task's non_goals MUST declare integration testing out of scope — do NOT add integration/e2e tests; this fix is verified solely by the committed unit oracle tests/ngv2/test_session_api_persistence_wired.py. Do NOT author or modify any test — that oracle is committed and authoritative. Do NOT modify ngv2/session_api.py — its `_load`/`_save` accessor-probe mechanism stays exactly as is (the fix is purely additive on `SessionDB`); do NOT implement the alternative fix variant (a `_load`/`_save` table fallback inside SessionApi). Do NOT change any existing `SessionDB` method (`insert_finding`, `get_finding`, `insert_poc`, `get_poc`, `insert_report`, `get_report`, `append_phase_validation_log`, `get_phase_validation_logs`, `_write`, `_begin`, `_commit`, `_rollback`, `_next_sequential_id`, `close`, `__enter__`, `__exit__`) or their aliases, the five-table schema/DDL, the FK/CHECK constraints, the WAL/foreign_keys pragmas, or the `__init__` signature. Do NOT add a hardcoded default db_path. PATCH-SHAPE non-goals (the prior attempt exhausted its retry budget on these): do NOT emit a dotted-qualname symbol patch (`'SessionDB.get_session'`, `'SessionDB.get_finding'`, or any `SessionDB.<method>` anchor) — adding a method via a dotted patch is impossible and was the prior failure; do NOT emit standalone method fragments carrying class-level indentation; do NOT emit a `__JANUSMASK_MANIFEST__` or a whole-file rewrite; do NOT add R-anchor extra top-level nodes (there is no top-level symbol after `class SessionDB` to anchor a binding-assignment on — the two accessors must be real methods inside the single reproduced `'SessionDB'` whole-class symbol patch). Do NOT touch ngv2/session_gate.py (currently un-importable, separate fix in flight — the oracle and the `advance()` path under test never call it), ngv2/state_machine.py, ngv2/contracts.py, or any other module — edit ngv2/session_db.py ONLY. No new module-level symbols beyond what the two methods need (json/sqlite3 are already imported); no network, no wall-clock, no randomness, no third-party imports.

# Inputs

The committed authoritative oracle at tests/ngv2/test_session_api_persistence_wired.py (NGv2 commit 9016219; currently RED with `AssertionError: STORAGE GAP: advance() returned the 404 envelope over a bare SessionDB`). It seeds FSM working-state as a raw `session_pipeline` row (`{"session_id": ..., "phase": "source", "artifacts": {...}}` JSON in the `data` column), then over a REAL un-subclassed `SessionDB` asserts: `get_current_phase` reads the seeded phase `'source'`; `advance()` walks the autonomous phases and parks at `awaiting_submission` (reason `awaiting_operator_approval`) with all `_REQUIRED_ARTIFACTS` present; `advance(..., approval_decision={'approved': True})` releases through `submitted` to `done`; and the parked phase + `parked_package` SURVIVE closing the DB and reopening a fresh `SessionDB`+`SessionApi` over the same sqlite file (real persistence, not in-memory). The exact consumer contract in ngv2/session_api.py (read-only; do NOT edit) — `_load` probes accessors and needs `get_session` to return the session dict or None:

    def _load(self, session_id: Any) -> Any:
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
        ...
        return None

and `_save` needs `save_session(session_id, data)` to persist the working-state dict:

    def _save(self, session_id: Any, data: Dict[str, Any]) -> None:
        db = self.db
        if db is None:
            return
        for name in ('save_session', 'update_session', 'write_session', 'store_session', 'save', 'update', 'put', 'write', 'set', 'store'):
            mutator = getattr(db, name, None)
            if callable(mutator):
                try:
                    mutator(session_id, data)
                    return
                ...

The keying convention to match (from SessionApi's legacy `_load_session`/`_advance`, same table):

    cur = self.db._conn.execute("SELECT data FROM session_pipeline WHERE json_extract(data, '$.session_id') = ?", (session_id,))
    ...
    self.db._conn.execute("UPDATE session_pipeline SET phase = ?, data = ? WHERE json_extract(data, '$.session_id') = ?", (to_phase, json.dumps(data, sort_keys=True), session_id))

The target module's existing storage surface in ngv2/session_db.py — the `session_pipeline` DDL is `CREATE TABLE IF NOT EXISTS session_pipeline (id INTEGER PRIMARY KEY, phase TEXT, data TEXT NOT NULL DEFAULT '{}')` (NO foreign keys on this table), and the write helper to reuse is:

    def _write(self, sql: str, params: Sequence[Any]) -> sqlite3.Cursor:
        """Execute a single write inside a BEGIN IMMEDIATE transaction."""
        self._begin()
        try:
            cur = self._conn.execute(sql, params)
            self._commit()
            return cur
        except Exception:
            self._rollback()
            raise

with read-path precedent `get_finding`: `row = self._conn.execute('SELECT data FROM findings WHERE id = ?', (finding_id,)).fetchone()` then `json.loads(row['data'])` (`self._conn.row_factory = sqlite3.Row`; the connection uses `isolation_level=None`). ngv2/state_machine.py LIFECYCLE_PHASES = ('source', 'hunt', 'triage', 'verify', 'poc', 'detonate', 'novelty', 'report', 'awaiting_submission', 'submitted', 'done') = session_api.PHASE_ORDER (read-only reference). stdlib + ngv2 only.

# Deliverables

Edited ngv2/session_db.py in which `class SessionDB` additionally exposes `get_session(self, session_id)` (returns the parsed session working-state dict from `session_pipeline` keyed by `json_extract(data, '$.session_id')`, or None on miss) and `save_session(self, session_id, data)` (persists the dict back as sorted-keys JSON via `self._write`, UPDATE-then-INSERT on rowcount 0, syncing the `phase` column from `data.get('phase')`), with NO change to any existing method, alias, schema statement, pragma, or other module, so the live `SessionApi` FSM surface (`advance`/`get_current_phase`/`get_parked_package`/`get_readiness_reason`) is persistence-wired end-to-end over a bare `SessionDB`. Verified GREEN by `python -m pytest tests/ngv2/test_session_api_persistence_wired.py -q`.
