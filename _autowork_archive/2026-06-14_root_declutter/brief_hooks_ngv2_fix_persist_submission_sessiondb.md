---
interfaces: "edits ngv2/human_checkpoint_gate.py to extend _insert_ledger_row with a save_session fallback — when none of the conventional _INSERT_METHODS names exists on the store, derive the deterministic ledger key 'submission:<target>:<timestamp>', add it to a copy of the row as a session_id bookkeeping field, and persist through SessionDB.save_session (the existing session_pipeline write path landed in NGv2 044740a) — so persist_submission(record, now_fn) writes its stamped turn-in ledger row through a REAL un-subclassed SessionDB instead of raising AttributeError, completing the bounty-FSM submitted -> done turn-in edge"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/human_checkpoint_gate.py — teach `_insert_ledger_row` the REAL SessionDB write path (`save_session` into the existing `session_pipeline` table) so `persist_submission(record, now_fn)` persists its stamped turn-in ledger row over a real, un-subclassed `SessionDB` instead of raising `AttributeError: SessionDB exposes no recognised ledger insert method`

# Scope

EDIT the EXISTING module ngv2/human_checkpoint_gate.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). DEFECT (verified live): `persist_submission(record, now_fn)` (landed NGv2 fdc02b3) stamps the record with the injected clock and hands the row to `_insert_ledger_row`, which only probes the conventional insert-method names in `_INSERT_METHODS` — `('insert_ledger_row', 'add_ledger_row', 'append_ledger_row', 'write_ledger_row', 'record_ledger_row', 'insert_submission', 'record_submission', 'add_submission', 'insert_row', 'add_row', 'append_row', 'insert', 'add', 'append', 'record', 'write', 'save', 'log')`. The REAL `ngv2.session_db.SessionDB` exposes NONE of those names: its actual write surface is `insert_finding` / `insert_poc` / `insert_report` / `append_phase_validation_log` / `_write`, plus the `get_session` / `save_session` accessors just landed in NGv2 commit 044740a (brief ngv2_fix_session_api_persistence) — note `save_session(session_id, data)` takes TWO arguments, so merely adding it to the one-arg `_INSERT_METHODS` probe would TypeError. So the loop falls through and `persist_submission` raises `AttributeError: SessionDB exposes no recognised ledger insert method` over ANY real SessionDB, leaving the bounty-FSM `submitted -> done` turn-in ledger write unreachable end-to-end (the committed bind-reconciliation oracle masks this by injecting a `_FakeDB` that fabricates `insert_ledger_row`). THE FIX (consistent with how brief ngv2_fix_session_api_persistence wired SessionDB persistence — reuse `save_session`/`session_pipeline`, do NOT grow SessionDB again): rewrite EXACTLY ONE top-level function, `_insert_ledger_row`, keeping the existing `_INSERT_METHODS` probe loop byte-identical FIRST (it preserves the committed bind-reconciliation oracle's `_FakeDB.insert_ledger_row` path), then — before the final `raise AttributeError(...)`, which stays as the last resort — add a `save_session` fallback: derive the deterministic ledger key `'submission:%s:%s' % (row.get('target'), row.get('timestamp'))`, copy the row (`payload = dict(row)` — never mutate the caller's row), set `payload['session_id'] = ledger_key` (the bookkeeping field `save_session`'s `json_extract(data, '$.session_id')` keying needs; all carried record fields stay intact), and call `saver(ledger_key, payload)`. EXACT corrected target (reproduce VERBATIM):

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

Keep the function pure/deterministic over its inputs (no clock, randomness, network, subprocess; stdlib only — the timestamp already comes from `persist_submission`'s injected `now_fn`). Read the read-only staged target at `{WORK_DIR}/inbox/targets/ngv2/human_checkpoint_gate.py` FIRST for the exact current module layout. Verify GREEN with `python -m pytest tests/ngv2/test_persist_submission_sessiondb_wired.py -q`; working_dir is /home/xnihil0zer0/NobleGreedv2.

DISPATCH DIRECTIVE — PATCH FORMAT (single whole-symbol patch on an EXISTING 1-part top-level function — the canonical safe shape): emit a single top-level `__JANUSMASK_PATCHES__` list with EXACTLY ONE entry:

    __JANUSMASK_PATCHES__ = [
        {'file': 'ngv2/human_checkpoint_gate.py', 'kind': 'symbol', 'name': '_insert_ledger_row',
         'code': r'''def _insert_ledger_row(db: Any, row: Dict[str, Any]) -> None:
    ... the corrected function, byte-for-byte per the Scope target ...
'''},
    ]

The `name` MUST be the 1-part TOP-LEVEL name `'_insert_ledger_row'` — never a dotted qualname, never a manifest, never a whole-file rewrite, never any extra top-level node (the fix needs NO new symbol: `_INSERT_METHODS`, `Any`, `Dict` already exist at module level). POST-EMIT SELF-CHECK (mandatory): your emitted `code` must START with `def _insert_ledger_row(db: Any, row: Dict[str, Any]) -> None:` at column 0, contain the unchanged `for method_name in _INSERT_METHODS:` probe loop, the `save_session` fallback, and END with the original `raise AttributeError('SessionDB exposes no recognised ledger insert method')` line; it must contain exactly ONE top-level `def` and no `class `/`import ` statements.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the committed oracle is keyed to this brief): `task_id`: `ngv2-fix-persist-submission-sessiondb`. meta_task_type=`data_model` (external NGv2 target — the diff-fuzzer cannot resolve external imports, so use a fuzzer-bypassed, smoke-gated meta-type). priority: high. dependencies: []. working_dir: `/home/xnihil0zer0/NobleGreedv2`. files_touched: `["ngv2/human_checkpoint_gate.py"]` ONLY. partial_edit semantics: a single `__JANUSMASK_PATCHES__` list with EXACTLY ONE `'symbol'` entry whose `name` is the 1-part top-level `'_insert_ledger_row'` (whole-function replacement per the DISPATCH DIRECTIVE — never dotted, never a manifest, never a whole-file rewrite, no extra nodes). The DISPATCH DIRECTIVE — PATCH FORMAT paragraph above MUST be copied VERBATIM into the task's `implementation_notes` so the blind worker sees it. verification_command: `python -m pytest tests/ngv2/test_persist_submission_sessiondb_wired.py -q`. The committed RED oracle tests/ngv2/test_persist_submission_sessiondb_wired.py (NGv2 commit 87dd54a) is the authoritative, storage-location-agnostic acceptance contract — make it GREEN; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from the committed oracle `tests/ngv2/test_persist_submission_sessiondb_wired.py` (plan descriptors referencing committed/landed tests — this does NOT authorize authoring new tests), so every `spec.edge_cases` entry is reflected per the validator's edge-case rule (e.g. `test_persist_submission_writes_through_a_real_sessiondb`, `test_stamped_row_survives_fresh_reopen`).

# Non-Goals

This is an EDIT and integration is out of scope: the task's non_goals MUST declare integration testing out of scope — do NOT add integration/e2e tests; this fix is verified solely by the committed unit oracle tests/ngv2/test_persist_submission_sessiondb_wired.py. Do NOT author or modify any test — that oracle is committed and authoritative. Do NOT modify ngv2/session_db.py — `SessionDB` already has the needed `save_session` write path (NGv2 044740a); do NOT implement the alternative fix variant (adding `insert_ledger_row`/a new ledger table to SessionDB, or changing its schema/DDL/pragmas). Do NOT change `persist_submission`, `_make_session_db`, `check_human_approval`, `_token_approval`, `_approval_from_json`, `_approval_from_text`, the module constants (`_APPROVE_TOKENS`, `_REJECT_MARKERS`, `_APPROVE_MARKERS`, `_DECISION_FIELDS`, `_LEDGER_FIELDS`, `_INSERT_METHODS` — in particular do NOT add `'save_session'` to `_INSERT_METHODS`: the probe loop calls `method(row)` with ONE argument and `save_session(session_id, data)` takes two, so that "fix" TypeErrors), the imports, or the module docstring — rewrite `_insert_ledger_row` ONLY. Do NOT reorder the fallback ahead of the `_INSERT_METHODS` probe loop (the committed bind-reconciliation oracle tests/ngv2/test_session_gate_bind_reconciliation_wired.py depends on `insert_ledger_row` winning when present) and do NOT remove the terminal `raise AttributeError(...)` (stores with neither surface must still fail loudly). Do NOT mutate the caller's `row` (copy before adding `session_id`). Do NOT touch ngv2/session_gate.py, ngv2/session_api.py, ngv2/contracts.py, or any other module. No new imports, no network, no wall-clock, no randomness, no third-party dependencies.

# Inputs

The committed authoritative oracle at tests/ngv2/test_persist_submission_sessiondb_wired.py (NGv2 commit 87dd54a; currently RED with `Failed: persist_submission cannot write through a REAL SessionDB (its _INSERT_METHODS probe list matches no real SessionDB method): SessionDB exposes no recognised ledger insert method`). It points the gate's own `session_db` seam at a REAL, un-subclassed `SessionDB(tmp_sqlite)` (via `monkeypatch.setattr(hcg, 'session_db', types.SimpleNamespace(SessionDB=lambda: real_db))`, mirroring how `_make_session_db` resolves `session_db.SessionDB`), calls `persist_submission(record, lambda: 'T-FIXED-0')` with the canonical record schema (`target`/`cwe`/`severity`/`payout_estimate`/`novelty`/`evidence`/`approval`), asserts no AttributeError and no input mutation, then CLOSES the DB and re-opens the sqlite FILE fresh, scanning every table for a JSON cell that round-trips the row — storage-location agnostic, but it requires every carried field PLUS `timestamp == 'T-FIXED-0'` to survive on disk (real persistence, not `:memory:`). The EXACT current defective source being replaced (from ngv2/human_checkpoint_gate.py at HEAD):

    def _insert_ledger_row(db: Any, row: Dict[str, Any]) -> None:
        """Insert ``row`` via the first recognised SessionDB ledger method."""
        for method_name in _INSERT_METHODS:
            method = getattr(db, method_name, None)
            if callable(method):
                method(row)
                return
        raise AttributeError('SessionDB exposes no recognised ledger insert method')

The real write path to reuse, `SessionDB.save_session` from ngv2/session_db.py (read-only; do NOT edit — landed in NGv2 044740a; keys rows by `json_extract(data, '$.session_id')`, hence the `payload['session_id'] = ledger_key` bookkeeping field; UPDATE-then-INSERT through `_write`'s `BEGIN IMMEDIATE` discipline):

    def save_session(self, session_id, data):
        payload = json.dumps(data, sort_keys=True)
        phase = data.get("phase") if isinstance(data, dict) else None
        cur = self._write(
            "UPDATE session_pipeline SET phase = ?, data = ? WHERE json_extract(data, '$.session_id') = ?",
            (phase, payload, session_id),
        )
        if cur.rowcount == 0:
            self._write(
                "INSERT INTO session_pipeline (phase, data) VALUES (?, ?)",
                (phase, payload),
            )

Caller context (read-only): `persist_submission` copies the record, stamps `row['timestamp'] = now_fn()`, builds the db via `_make_session_db()` and calls `_insert_ledger_row(db, row)`; ngv2/session_gate.py binds `record_submission` for the `submitted -> done` edge. The previously-green `_FakeDB.insert_ledger_row` path in tests/ngv2/test_session_gate_bind_reconciliation_wired.py (`test_record_seam_stamps_injected_clock_and_persists`) must keep working — the probe loop stays first and unchanged. stdlib + ngv2 only.

# Deliverables

Edited ngv2/human_checkpoint_gate.py in which `_insert_ledger_row` keeps its `_INSERT_METHODS` probe loop byte-identical, then falls back to the REAL `SessionDB.save_session` write path (deterministic `'submission:<target>:<timestamp>'` ledger key, copied payload carrying every record field plus the `session_id` bookkeeping key, terminal `AttributeError` preserved for stores with neither surface), exactly as pinned in Scope, with NO change to any other symbol, constant, import, or module, so `persist_submission(record, now_fn)` persists its stamped turn-in ledger row through a real, un-subclassed `SessionDB` into the durable `session_pipeline` table and the bounty-FSM `submitted -> done` turn-in write is reachable end-to-end. Verified GREEN by `python -m pytest tests/ngv2/test_persist_submission_sessiondb_wired.py -q`.
