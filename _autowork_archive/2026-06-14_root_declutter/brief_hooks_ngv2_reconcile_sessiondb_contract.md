---
interfaces: "edits ngv2/session_db.py and ngv2/session_api.py to restore the five old SessionDB sub-contracts the bounty-FSM rewrite dropped — (i) insert_finding/insert_poc/insert_report accept contract DATACLASSES again via the already-present-but-dead _to_dict() (today they json.dumps the raw argument and TypeError on any non-dict), (ii) SessionApi.submit_artifacts stamps session_id into the artifact payload before _persist_artifact, (iii) the get_* fetchers key on the artifact's contract id again (finding_id / pocs.finding_id / reports.poc_finding_id, with id|finding_id|fid projection via the dead _pick()) and return rebuilt contract OBJECTS via the dead _from_dict(), (iv) the public db_path attribute the module docstring advertises is restored alongside _db_path, and (v) SessionApi._load_table('live_test_reports') is fixed to the actual table name 'reports' — plus the severity CHECK, finding-id UNIQUE and PoC->Finding FK constraints the committed B2 oracle pins are restored into the schema (re-wiring the dead _quoted_set/SEVERITIES/VERDICTS)"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/session_db.py + ngv2/session_api.py — reconcile the rewritten SessionDB with the five committed sub-contracts it dropped: dataclass-tolerant inserts (`_to_dict`), contract-id-keyed object-returning getters (`_pick`/`_from_dict`), severity-CHECK + finding-UNIQUE + orphan-PoC-FK schema constraints (`_quoted_set`/`SEVERITIES`/`VERDICTS`), the public `db_path` attribute, session_id stamping in `SessionApi.submit_artifacts`, and the `'reports'` table name in `SessionApi._load_table`

# Scope

EDIT the EXISTING modules ngv2/session_db.py and ngv2/session_api.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). DISPATCH ORDER: dispatch this brief SECOND of the three session-stack fixes — AFTER `ngv2_fix_audit_log_arity` has integrated (the whole-class patches below must include that brief's corrected `_append_audit` call and optional-arg `get_phase_validation_logs`) and BEFORE `ngv2_fix_gate_transition_backcompat`.

DEFECTS (all verified against NGv2 HEAD `44bfb3c`, 2026-06-11 — the SessionDB rewrite kept the module-level helpers `_to_dict` (line 68), `_from_dict` (line 79), `_pick` (line 91), `_quoted_set` (line 98), `SEVERITIES` (line 65) and `VERDICTS` (line 66) but left ALL of them DEAD):

(i) ngv2/session_db.py:192-198 — `insert_finding` (and `insert_poc` line 213, `insert_report` line 235) is dict-only:

    def insert_finding(self, finding):
        payload = json.dumps(finding, sort_keys=True)
        session_id = finding.get("session_id") if isinstance(finding, dict) else None
        return self._write(
            "INSERT INTO findings (session_id, data) VALUES (?, ?)",
            (session_id, payload),
        )

`json.dumps(Finding(...))` → `TypeError: Object of type Finding is not JSON serializable` (kills tests/ngv2/test_session_db_wired.py round-trips and the `_seed_parent` of test_session_api_classify_phase_wired.py).

(ii) the schema mandates `session_id TEXT NOT NULL` on findings/pocs/reports (lines 132-152) but `SessionApi.submit_artifacts` (session_api.py:78-101) never stamps session_id into the artifact before `_persist_artifact` (line 328: candidates `[obj, raw]`, neither carries session_id) → `sqlite3.IntegrityError: NOT NULL constraint failed: findings.session_id` → every valid artifact is "rejected" (kills the 2 submit tests of test_session_api_wired.py and the submit-delegate of test_session_mcp_wired.py).

(iii) `get_finding` (session_db.py:200-211) keys ONLY on `json_extract(data, '$.finding_id')` — but `Finding.to_dict()` carries `id`, NOT `finding_id`, so every lookup misses; `get_poc` (line 222) keys on `'$.poc_id'` (PoC has no such field — its key is `finding_id`) and `get_report` (line 244) on `'$.report_id'` (LiveTestReport's key is `poc_finding_id`); all three return raw DICTS, but the committed B2 oracle asserts `got.to_dict() == inserted.to_dict()` — they must return rebuilt contract OBJECTS.

(iv) the public `db_path` attribute was removed — `__init__` (line 118-123) sets only `self._db_path` — while the module docstring still advertises the injected-path `SessionDB(db_path)` convention; tests/ngv2/test_session_mcp_main_wired.py::test_resolved_path_constructs_sessiondb asserts `db.db_path == p` → AttributeError.

(v) session_api.py:188 — `SessionApi._evaluate_gate` loads `rows['reports']` from `self._load_table('live_test_reports')` but the rewritten schema's table is named `reports` (line 147) → the detonate->report gate always sees zero reports.

Additionally the committed B2 oracle (tests/ngv2/test_session_db_wired.py, LOAD-BEARING per its docstring) pins constraints the rewrite dropped entirely and which MUST be restored for it to go green: a bad `severity` (not in `contracts.SEVERITIES`) is rejected with `sqlite3.IntegrityError` (CHECK), an orphan `PoC.finding_id` is rejected with `sqlite3.IntegrityError` (FK; `PRAGMA foreign_keys=ON` is already issued), and a duplicate finding id raises `sqlite3.IntegrityError` (UNIQUE — what makes test_session_api_dup_wired.py's rejected-entry contract work, since `submit_artifacts` already catches `sqlite3.IntegrityError`). Because direct dataclass inserts carry NO session_id, the artifact tables' `session_id` columns must become NULLABLE (`TEXT`, dropping `NOT NULL`) — API-path rows still get session_id via the new stamping in (ii).

THE FIX, part 1 — ngv2/session_db.py: replace the `SessionDB` class with the version below (ONLY `__init__`, `_init_schema`, `insert_finding`, `get_finding`, `insert_poc`, `get_poc`, `insert_report`, `get_report` change; `_configure_connection`, `_begin`, `_commit`, `_rollback`, `_write`, `append_phase_validation_log`, `get_phase_validation_logs` (the post-`ngv2_fix_audit_log_arity` optional-arg version), `_next_sequential_id`, `close`, `__enter__`, `__exit__`, `get_session`, `save_session` stay byte-for-byte). EXACT corrected methods (reproduce VERBATIM; `os`, `json`, `sqlite3`, `_to_dict`, `_from_dict`, `_pick`, `_quoted_set`, `SEVERITIES`, `VERDICTS`, `_FINDING_CLS`, `_POC_CLS`, `_REPORT_CLS` all already exist at module level — NO new imports):

    def __init__(self, db_path):
        self.db_path = os.fspath(db_path)
        self._db_path = self.db_path
        self._conn = sqlite3.connect(self.db_path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._configure_connection()
        self._init_schema()

    def _init_schema(self):
        severity_set = _quoted_set(SEVERITIES)
        verdict_set = _quoted_set(VERDICTS)
        statements = [
            "CREATE TABLE IF NOT EXISTS findings (\n"
            "    id INTEGER PRIMARY KEY,\n"
            "    session_id TEXT,\n"
            "    finding_id TEXT NOT NULL UNIQUE,\n"
            "    severity TEXT NOT NULL CHECK (severity IN " + severity_set + "),\n"
            "    data TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(data))\n"
            ")",
            "CREATE TABLE IF NOT EXISTS pocs (\n"
            "    id INTEGER PRIMARY KEY,\n"
            "    session_id TEXT,\n"
            "    finding_id TEXT NOT NULL UNIQUE REFERENCES findings (finding_id),\n"
            "    data TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(data))\n"
            ")",
            "CREATE TABLE IF NOT EXISTS reports (\n"
            "    id INTEGER PRIMARY KEY,\n"
            "    session_id TEXT,\n"
            "    poc_finding_id TEXT NOT NULL REFERENCES pocs (finding_id),\n"
            "    verdict TEXT NOT NULL CHECK (verdict IN " + verdict_set + "),\n"
            "    data TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(data))\n"
            ")",
            "CREATE TABLE IF NOT EXISTS phase_validation_logs (\n"
            "    id INTEGER PRIMARY KEY,\n"
            "    session_id TEXT NOT NULL,\n"
            "    phase TEXT,\n"
            "    data TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(data))\n"
            ")",
            "CREATE TABLE IF NOT EXISTS session_pipeline (\n"
            "    id INTEGER PRIMARY KEY,\n"
            "    phase TEXT,\n"
            "    data TEXT NOT NULL DEFAULT '{}'\n"
            ")",
        ]
        for statement in statements:
            self._conn.execute(statement)

    def insert_finding(self, finding):
        payload = _to_dict(finding)
        finding_id = _pick(payload, "id", "finding_id", "fid")
        severity = _pick(payload, "severity")
        session_id = _pick(payload, "session_id")
        return self._write(
            "INSERT INTO findings (session_id, finding_id, severity, data) VALUES (?, ?, ?, ?)",
            (session_id, finding_id, severity, json.dumps(payload, sort_keys=True)),
        )

    def get_finding(self, finding_id):
        row = self._conn.execute(
            "SELECT data FROM findings WHERE finding_id = ?",
            (finding_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            parsed = json.loads(row["data"])
        except (ValueError, TypeError):
            return None
        if not isinstance(parsed, dict):
            return None
        return _from_dict(_FINDING_CLS, parsed)

    def insert_poc(self, poc):
        payload = _to_dict(poc)
        finding_id = _pick(payload, "finding_id", "id", "fid")
        session_id = _pick(payload, "session_id")
        return self._write(
            "INSERT INTO pocs (session_id, finding_id, data) VALUES (?, ?, ?)",
            (session_id, finding_id, json.dumps(payload, sort_keys=True)),
        )

    def get_poc(self, finding_id):
        row = self._conn.execute(
            "SELECT data FROM pocs WHERE finding_id = ?",
            (finding_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            parsed = json.loads(row["data"])
        except (ValueError, TypeError):
            return None
        if not isinstance(parsed, dict):
            return None
        return _from_dict(_POC_CLS, parsed)

    def insert_report(self, report):
        payload = _to_dict(report)
        poc_finding_id = _pick(payload, "poc_finding_id", "poc_id")
        verdict = _pick(payload, "verdict")
        session_id = _pick(payload, "session_id")
        return self._write(
            "INSERT INTO reports (session_id, poc_finding_id, verdict, data) VALUES (?, ?, ?, ?)",
            (session_id, poc_finding_id, verdict, json.dumps(payload, sort_keys=True)),
        )

    def get_report(self, poc_finding_id):
        row = self._conn.execute(
            "SELECT data FROM reports WHERE poc_finding_id = ?",
            (poc_finding_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            parsed = json.loads(row["data"])
        except (ValueError, TypeError):
            return None
        if not isinstance(parsed, dict):
            return None
        return _from_dict(_REPORT_CLS, parsed)

THE FIX, part 2 — ngv2/session_api.py, three pinned spots inside `SessionApi` (everything else byte-for-byte, INCLUDING the `ngv2_fix_audit_log_arity` corrected line `self.db.append_phase_validation_log(session_id, to_phase, record)`):

(a) in `submit_artifacts`, the persist call passes session_id down — change `self._persist_artifact(kind, raw, obj)` (line 95) to:

    self._persist_artifact(kind, raw, obj, session_id)

(b) `_persist_artifact` stamps session_id into a COPY of the validated dict and prefers the stamped dict over the dataclass so the stamp actually persists; EXACT corrected method:

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

(c) in `_evaluate_gate` (line 188), the rows dict's reports leg uses the real table name — change `'reports': self._load_table('live_test_reports')` to:

    'reports': self._load_table('reports')

Read the read-only staged targets at `{WORK_DIR}/inbox/targets/ngv2/session_db.py` and `{WORK_DIR}/inbox/targets/ngv2/session_api.py` FIRST and reproduce everything outside the pinned spots byte-for-byte. Verify GREEN with `python -m pytest tests/ngv2/test_session_db_wired.py tests/ngv2/test_session_api_dup_wired.py tests/ngv2/test_session_api_classify_phase_wired.py tests/ngv2/test_session_mcp_main_wired.py "tests/ngv2/test_session_api_wired.py::test_submit_artifacts_accepts_valid_finding" "tests/ngv2/test_session_api_wired.py::test_submit_artifacts_partial_accept_mixed_batch" "tests/ngv2/test_session_mcp_wired.py::test_submit_artifacts_tool_delegates" -q`; working_dir is /home/xnihil0zer0/NobleGreedv2. (The transition-leg tests of test_session_api_wired.py / test_session_mcp_wired.py additionally need the sibling brief `ngv2_fix_gate_transition_backcompat`, dispatched after this one, whose verification runs those files whole.)

DISPATCH DIRECTIVE — PATCH FORMAT (whole-symbol patches on EXISTING 1-part top-level classes — the canonical safe shape; class METHODS are NEVER patched as dotted symbols): emit a single top-level `__JANUSMASK_PATCHES__` list with EXACTLY TWO entries:

    __JANUSMASK_PATCHES__ = [
        {'file': 'ngv2/session_db.py', 'kind': 'symbol', 'name': 'SessionDB',
         'code': r'''<the ENTIRE class SessionDB: the staged target's class reproduced byte-for-byte EXCEPT __init__, _init_schema, insert_finding, get_finding, insert_poc, get_poc, insert_report, get_report replaced VERBATIM by the corrected methods pinned in Scope>'''},
        {'file': 'ngv2/session_api.py', 'kind': 'symbol', 'name': 'SessionApi',
         'code': r'''<the ENTIRE class SessionApi reproduced byte-for-byte from the staged target with ONLY the three pinned spots changed: the submit_artifacts persist call gains the trailing session_id argument, _persist_artifact is replaced VERBATIM by the corrected method in Scope, and _evaluate_gate's _load_table('live_test_reports') becomes _load_table('reports')>'''},
    ]

Each `name` MUST be the 1-part TOP-LEVEL class name (`'SessionDB'`, `'SessionApi'`) — never a dotted qualname, never a manifest, never a whole-file rewrite, never any extra top-level node, NO new imports (every needed name — `os`, `_to_dict`, `_from_dict`, `_pick`, `_quoted_set`, `SEVERITIES`, `VERDICTS`, `_FINDING_CLS`, `_POC_CLS`, `_REPORT_CLS`, `Optional`, `Dict`, `Any` — already exists at module level in its file). POST-EMIT SELF-CHECK (mandatory, guards against silent truncation of large symbols): the emitted `SessionDB` code must START with `class SessionDB:` at column 0, contain EXACTLY 21 `def ` occurrences, contain `self.db_path = os.fspath(db_path)`, `finding_id TEXT NOT NULL UNIQUE`, `REFERENCES findings (finding_id)`, `_quoted_set(SEVERITIES)`, `_to_dict(finding)` and `_from_dict(_FINDING_CLS, parsed)`, keep `def append_phase_validation_log(self, session_id, phase, entry):` and `def get_phase_validation_logs(self, session_id=None):` unchanged, and end with the `save_session` method; the emitted `SessionApi` code must START with `class SessionApi:` at column 0, contain EXACTLY 40 `def ` occurrences, contain `self._persist_artifact(kind, raw, obj, session_id)` and `def _persist_artifact(self, kind: str, raw: Dict[str, Any], obj: Any, session_id: Any=None)` and `self._load_table('reports')`, NOT contain `live_test_reports`, retain `self.db.append_phase_validation_log(session_id, to_phase, record)`, and end with the `_truthy_approval` method followed by the trailing class-docstring string literal.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM: `task_id`: `ngv2-reconcile-sessiondb-contract`. meta_task_type=`data_model` (external NGv2 target — the diff-fuzzer cannot resolve external imports, so use a fuzzer-bypassed, smoke-gated meta-type; this is schema + (de)serialization plumbing, archetypal data_model). priority: high. dependencies: []. working_dir: `/home/xnihil0zer0/NobleGreedv2`. files_touched: `["ngv2/session_db.py", "ngv2/session_api.py"]` ONLY. partial_edit semantics: a single `__JANUSMASK_PATCHES__` list with EXACTLY TWO `'symbol'` entries whose `name`s are the 1-part top-level `'SessionDB'` and `'SessionApi'` (whole-class replacements per the DISPATCH DIRECTIVE — never dotted, never a manifest, never a whole-file rewrite, no extra nodes). The DISPATCH DIRECTIVE — PATCH FORMAT paragraph above MUST be copied VERBATIM into the task's `implementation_notes` together with the corrected method sources so the blind worker sees them. verification_command: `python -m pytest tests/ngv2/test_session_db_wired.py tests/ngv2/test_session_api_dup_wired.py tests/ngv2/test_session_api_classify_phase_wired.py tests/ngv2/test_session_mcp_main_wired.py "tests/ngv2/test_session_api_wired.py::test_submit_artifacts_accepts_valid_finding" "tests/ngv2/test_session_api_wired.py::test_submit_artifacts_partial_accept_mixed_batch" "tests/ngv2/test_session_mcp_wired.py::test_submit_artifacts_tool_delegates" -q`. The committed RED oracles are the authoritative acceptance contract — make them GREEN; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from this brief's committed RED oracle files (plan descriptors referencing committed/landed tests — this does NOT authorize authoring new tests), so every `spec.edge_cases` entry is reflected per the validator's edge-case rule (e.g. `test_bad_severity_rejected_by_check` and `test_duplicate_resubmit_returns_rejected_entry_and_does_not_raise`; also good: `test_finding_round_trip`, `test_orphan_poc_rejected_by_fk`, `test_submit_bare_report_in_detonate_phase_is_accepted`, `test_resolved_path_constructs_sessiondb`).

# Non-Goals

This is an EDIT and integration is out of scope: the task's non_goals MUST declare integration testing out of scope — do NOT add integration/e2e tests; this fix is verified solely by the committed unit oracles in the verification command. Do NOT author or modify any test — those oracles are committed and authoritative. Change ONLY the pinned methods/spots. Do NOT add schema MIGRATION logic for pre-existing sqlite files (CREATE TABLE IF NOT EXISTS over fresh tmp paths is what the oracles exercise; live-state migration is explicitly out of scope). Do NOT rename the `reports` table back to `live_test_reports` — the table KEEPS its new name and the API caller is conformed to it. Do NOT change `append_phase_validation_log` / `get_phase_validation_logs` (already reconciled by the sibling brief `ngv2_fix_audit_log_arity` — preserve its versions byte-for-byte), `get_session` / `save_session`, `_write`/`_begin`/`_commit`/`_rollback`, `_configure_connection` (keep exactly the two PRAGMAs), `_next_sequential_id`, the context-manager methods, or — in SessionApi — `transition`, `_evaluate_gate` beyond the one table-name string, `_append_audit`, `_classify` (its phase->kind map is already fixed at HEAD), `_validate_artifact`, `create_session`, `get_state`, `advance`, or any other method. Do NOT "fix" `SessionApi._evaluate_gate`'s legacy-shaped `_gate_transition(rows, current, to_phase)` call — that is the sibling brief `ngv2_fix_gate_transition_backcompat`, explicitly out of scope here. Do NOT add new imports, module-level symbols, network, wall-clock, randomness, or third-party dependencies. Do NOT touch ngv2/session_gate.py, ngv2/contracts.py, ngv2/session_mcp.py, ngv2/state_machine.py, or any other module. MUST STAY GREEN: tests/ngv2/test_session_api_persistence_wired.py, test_session_api_surface_wired.py, test_persist_submission_sessiondb_wired.py (persist_submission writes through `save_session`/`session_pipeline` — untouched), test_session_api_audit_now_fn_wired.py, and the currently-passing cases of every file in the verification command (e.g. `test_fetch_miss_returns_none`, `test_journal_mode_is_wal`, `test_valueerror_from_persist_becomes_rejected_entry`, `test_regression_contract_invalid_artifact_still_rejected`, the five `resolve_db_path` tests).

# Inputs

The committed authoritative RED oracles (NGv2 HEAD `44bfb3c`; fail counts confirmed live 2026-06-11):

- tests/ngv2/test_session_db_wired.py — 5 failing of 7 (`test_finding_round_trip`, `test_poc_round_trip`, `test_report_round_trip` — dataclass inserts TypeError today; `test_bad_severity_rejected_by_check`, `test_orphan_poc_rejected_by_fk` — need the restored CHECK/FK). LOAD-BEARING contract: inserts take contract dataclasses; `get_finding(finding_id)` / `get_poc(finding_id)` / `get_report(poc_finding_id)` return objects whose `to_dict()` equals the inserted object's `to_dict()`; bad severity and orphan PoC raise `sqlite3.IntegrityError`; fetch-miss returns None.
- tests/ngv2/test_session_api_dup_wired.py — 4 failing of 6 (`test_duplicate_resubmit_returns_rejected_entry_and_does_not_raise`, `test_duplicate_within_same_batch_rejects_second_at_its_index`, `test_duplicate_does_not_block_subsequent_valid_artifact`, `test_original_row_survives_duplicate_attempt`) — needs valid submits to actually persist (stamping + nullable session_id) AND duplicates to raise `sqlite3.IntegrityError` (UNIQUE finding_id) which `submit_artifacts` already converts to rejected entries.
- tests/ngv2/test_session_api_classify_phase_wired.py — 2 failing of 8 (`test_submit_bare_report_in_detonate_phase_is_accepted`, `test_submit_bare_report_in_report_phase_is_accepted`) — their `_seed_parent` inserts Finding/PoC DATACLASSES directly, then submits a bare LiveTestReport dict.
- tests/ngv2/test_session_api_wired.py — the 2 submit tests (`test_submit_artifacts_accepts_valid_finding`, `test_submit_artifacts_partial_accept_mixed_batch`).
- tests/ngv2/test_session_mcp_wired.py — `test_submit_artifacts_tool_delegates` (the second mcp delegate failure, `test_transition_tool_delegates`, additionally needs the gate-backcompat sibling brief).
- tests/ngv2/test_session_mcp_main_wired.py — 1 failing of 8 (`test_resolved_path_constructs_sessiondb`, asserts `db.db_path == p`).

The EXACT current defective sources are quoted in Scope ((i)-(v)). Contract shapes (READ-ONLY, ngv2/contracts.py): `Finding.to_dict()` keys = {id, target, category, severity, title, description, evidence}; `PoC.to_dict()` keys = {finding_id, language, code, entrypoint}; `LiveTestReport.to_dict()` keys = {poc_finding_id, verdict, exit_code, stdout, stderr, duration_ms}; `SEVERITIES = ('low','medium','high','critical')`; `VERDICTS = ('confirmed','refuted','error','inconclusive')`; `from_dict` reads only its named keys, so a stamped extra `session_id` key in the persisted JSON never breaks rebuild or `to_dict()` round-trip equality. The dead module-level helpers to re-wire are at session_db.py lines 62-107 (`_FINDING_CLS`/`_POC_CLS`/`_REPORT_CLS`, `SEVERITIES`/`VERDICTS`, `_to_dict`, `_from_dict`, `_pick`, `_quoted_set`). The historical B2 contract reference: `git -C /home/xnihil0zer0/NobleGreedv2 show 6ac449c:ngv2/session_db.py` (old `self.db_path = os.fspath(db_path)`, `payload = _to_dict(...)` inserts, severity-CHECK/FK DDL built from `_quoted_set`). stdlib + ngv2 only.

# Deliverables

Edited ngv2/session_db.py whose `SessionDB` restores the five dropped sub-contracts exactly as pinned in Scope (dataclass-tolerant `_to_dict` inserts with `_pick` projections; `finding_id`-UNIQUE + severity-CHECK + PoC-FK + verdict-CHECK schema with NULLABLE artifact session_id; contract-object-returning, contract-id-keyed getters via `_from_dict`; public `db_path` alongside `_db_path`) and edited ngv2/session_api.py whose `SessionApi` stamps `session_id` into the persisted artifact payload (`submit_artifacts` → `_persist_artifact(kind, raw, obj, session_id)` preferring the stamped dict) and loads gate rows from the real `'reports'` table — everything else in both classes byte-for-byte unchanged. Verified GREEN by the verification command in Required plan shape (16 currently-failing oracle cases flip green; all currently-passing siblings stay green).
