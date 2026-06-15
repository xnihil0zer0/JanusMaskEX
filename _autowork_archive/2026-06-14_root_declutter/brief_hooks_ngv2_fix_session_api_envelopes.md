---
interfaces: "edits ngv2/session_api.py so SessionApi stops silently allowing every gated transition and speaks the reconciled legacy envelopes again — DELETES the permissive instance-method stub `_gate_transition` (which SHADOWS the module-level import of the real session_gate.gate_transition) and rewires `_evaluate_gate` to the real module-level gate, and restores the three envelope behaviors: `create_session` -> {'ok': True, 'session_id', 'phase': 'hunt'}, `get_state` unknown-session -> the 404 envelope, `transition` -> ALLOWED_TRANSITIONS allow-map check + 422 envelope + 'to' key + 404 on unknown session — while KEEPING commit 1c525e9's duck-typed save_session/get_session storage work intact"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/session_api.py — delete the permissive `_gate_transition` stub (every gated transition is silently allowed today), rewire `_evaluate_gate` to the real module-level `session_gate.gate_transition`, and restore the reconciled legacy envelopes (`ok`/404/422/`to` + the ALLOWED_TRANSITIONS check) in `create_session` / `get_state` / `transition` — un-breaking the 7 RED api/mcp oracle cases that commit `1c525e9` regressed

# Scope

EDIT the EXISTING module ngv2/session_api.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). DISPATCH ORDER: this brief builds on the LANDED dual-shape `gate_transition` sibling (`ngv2_fix_gate_transition_backcompat`, integrated as NGv2 `ebb4a18`) — `session_gate.gate_transition` now self-dispatches and accepts the legacy `(rows, from_phase, to_phase)` calling convention, so the transition legs of this brief's verification command are reachable. This brief is dispatchable now; do NOT touch ngv2/session_gate.py.

DEFECT (verified against NGv2 HEAD `ebb4a18`, 2026-06-11; introduced by `1c525e9`, the sessiondb-contract reconciliation): `1c525e9` regressed SessionApi in two coupled ways.

(i) It introduced a PERMISSIVE instance-method stub at ngv2/session_api.py:586 (the LAST method in the class):

    def _gate_transition(self, rows, current, to_phase):
        return {'ok': True, 'allowed': True, 'reasons': []}

This stub SHADOWS the module-level import of the real gate (`from ngv2.session_gate import gate_transition as _gate_transition` at the top of the file) for its caller `_evaluate_gate`, which today reads:

    def _evaluate_gate(self, session_id, current, to_phase):
        rows = {'findings': self._load_table('findings'), 'pocs': self._load_table('pocs'), 'reports': self._load_table('reports')}
        return self._gate_transition(rows, current, to_phase)

so EVERY gated transition is silently allowed — the real artifact gates never run.

(ii) It dropped the reconciled legacy envelopes from the three public methods. The EXACT current defective source (HEAD `ebb4a18`):

    def create_session(self, session_id, target_info=None):
        state = {'session_id': session_id, 'phase': _PHASES[0], 'target': dict(target_info or {})}
        saver = getattr(self.db, 'save_session', None)
        if callable(saver):
            saver(session_id, state)
        return state

    def get_state(self, session_id):
        getter = getattr(self.db, 'get_session', None)
        if callable(getter):
            return getter(session_id)
        return None

    def transition(self, session_id, to_phase, approvals=None):
        state = self.get_state(session_id) or {'session_id': session_id, 'phase': _PHASES[0]}
        current = state.get('phase')
        gate = self._evaluate_gate(session_id, current, to_phase)
        approved = True
        if approvals is not None:
            approved = self._truthy_approval(approvals)
        record = {'from': current, 'to': to_phase, 'gate': gate, 'at': self._now_fn()}
        self._append_audit(session_id, to_phase, record)
        ok = bool(gate.get('ok')) and approved
        if ok:
            state['phase'] = to_phase
            saver = getattr(self.db, 'save_session', None)
            if callable(saver):
                saver(session_id, state)
        return {'ok': ok, 'phase': state.get('phase'), 'gate': gate}

`create_session` returns the raw state dict (no `'ok'` key); `get_state` returns `None` for an unknown session instead of the 404 envelope (the `_not_found` helper at session_api.py:596 still exists but is now unused by these paths); `transition` never consults `ALLOWED_TRANSITIONS` (hunt->report sails through), never 404s, never 422s, and returns `'phase'` instead of `'from'`/`'to'`. The reconciled contract is documented in the `transition` docstring at NGv2 `7ab704e` (`git -C /home/xnihil0zer0/NobleGreedv2 show 7ab704e:ngv2/session_api.py`) and pinned by the 7 failing committed oracles listed in Inputs.

KEEP `1c525e9`'s duck-typed `save_session`/`get_session` storage work INTACT: `1c525e9` also gave `ngv2.session_db.SessionDB` real `get_session`/`save_session` accessors (session_db.py:240/252, backed by the `session_pipeline` table), and the three methods correctly route storage through `getattr(self.db, 'save_session'/'get_session', ...)`. That routing stays. Only the ENVELOPES and the GATE are restored — do NOT resurrect `7ab704e`'s raw `self.db._conn` SQL in these three methods, do NOT change `_load_table` (the reports table in this schema is named `reports`, NOT `7ab704e`'s `live_test_reports`).

THE FIX (data_model — ONE whole-class symbol patch on `SessionApi`; five pinned deltas, everything else byte-for-byte): reproduce the staged class EXACTLY as-is EXCEPT:

1. DELETE the `_gate_transition` stub method entirely (it is the last `def` in the class).
2. REPLACE `_evaluate_gate` (the stub's only caller) with this version that calls the real MODULE-LEVEL gate (same name `_gate_transition`, but now resolving to the module-level import once the shadowing method is gone) — keep the 3-arg signature so no other caller changes:

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

3. REPLACE `create_session` (keep the duck-typed saver; restore the `ok` envelope):

    def create_session(self, session_id, target_info=None):
        state = {'session_id': session_id, 'phase': _PHASES[0], 'target': dict(target_info or {})}
        saver = getattr(self.db, 'save_session', None)
        if callable(saver):
            saver(session_id, state)
        return {'ok': True, 'session_id': session_id, 'phase': _PHASES[0]}

4. REPLACE `get_state` (keep the duck-typed getter; restore the 404 envelope and the `ok` envelope):

    def get_state(self, session_id):
        getter = getattr(self.db, 'get_session', None)
        state = getter(session_id) if callable(getter) else None
        if not isinstance(state, dict):
            return {'ok': False, 'status': 404, 'error': 'unknown session_id: %r' % (session_id,)}
        envelope = dict(state)
        envelope['ok'] = True
        envelope.setdefault('session_id', session_id)
        return envelope

5. REPLACE `transition` (restore 404-on-unknown, the ALLOWED_TRANSITIONS allow-map check via the existing `_allowed_targets` helper, the always-written audit row, the 422 envelope, and the `'from'`/`'to'` success envelope — keep the `approvals=None` third parameter because the current `advance` calls `self.transition(session_id, to_phase, approvals)` with three arguments, and keep the duck-typed saver):

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

Every helper these methods touch (`_PHASES`, `_allowed_targets`, `_truthy_approval`, `_now_fn`, `_append_audit`, `_as_text`, `_load_table`) already exists in the class — NO new imports, NO new module-level symbols, NO other method changes. This exact five-delta class was validated live in a throwaway worktree on 2026-06-11: the 7 RED oracle cases flip GREEN, the verification command below passes 47/47 (3 pre-existing reds deselected), and a full tests/ngv2 sweep shows the candidate failure set is a STRICT SUBSET of HEAD's (zero new failures; it even flips `test_unknown_session_transition_does_not_touch_now_fn` green as a side effect). Read the read-only staged target at `{WORK_DIR}/inbox/targets/ngv2/session_api.py` FIRST and reproduce everything outside the five deltas byte-for-byte.

Keep the class pure/deterministic (no clock/randomness/network/subprocess beyond what HEAD already does). Verify GREEN with `python -m pytest tests/ngv2/test_session_api_wired.py tests/ngv2/test_session_mcp_wired.py tests/ngv2/test_session_db_wired.py tests/ngv2/test_session_api_persistence_wired.py tests/ngv2/test_session_api_dup_wired.py tests/ngv2/test_session_api_classify_phase_wired.py tests/ngv2/test_session_api_audit_now_fn_wired.py tests/ngv2/test_session_mcp_main_wired.py --deselect tests/ngv2/test_session_api_persistence_wired.py::test_advance_full_lifecycle_to_done_over_bare_sessiondb --deselect tests/ngv2/test_session_api_persistence_wired.py::test_fsm_state_persists_across_sessiondb_reopen --deselect tests/ngv2/test_session_api_audit_now_fn_wired.py::test_default_construction_has_now_fn_attribute -q`; working_dir is /home/xnihil0zer0/NobleGreedv2. (The three deselects are PRE-EXISTING reds — see Inputs — caused by the separate advance-clobber/now_fn defects, NOT by this brief's surface; they are deselected explicitly rather than silently swallowed.)

DISPATCH DIRECTIVE — PATCH FORMAT (single whole-symbol patch on an EXISTING 1-part top-level class — the canonical safe shape): emit a single top-level `__JANUSMASK_PATCHES__` list with EXACTLY ONE entry:

    __JANUSMASK_PATCHES__ = [
        {'file': 'ngv2/session_api.py', 'kind': 'symbol', 'name': 'SessionApi',
         'code': r'''<the ENTIRE corrected SessionApi class: the staged HEAD class byte-for-byte EXCEPT the five deltas pinned in Scope>'''},
    ]

The `name` MUST be the 1-part TOP-LEVEL name `'SessionApi'` — never a dotted qualname, never a manifest, never a whole-file rewrite, never any extra top-level node (the fix needs NO new symbol and NO new import: `_gate_transition` (module-level), `_ALLOWED_TRANSITIONS`, `_PHASES`, `_not_found`, `Any`, `json` all already exist at module level; `_PHASES` is defined AFTER the class in the file, which is fine because it is resolved at call time). The emitted `code` must reproduce the WHOLE class — docstring, every untouched method byte-for-byte in the original order — with ONLY the five Scope deltas applied. POST-EMIT SELF-CHECK (mandatory): your emitted `code` must START with `class SessionApi:` at column 0; contain EXACTLY 44 `def ` method definitions (HEAD has 45; deleting the `_gate_transition` stub leaves 44 — COUNT THEM); contain NO occurrence of `def _gate_transition` and NO occurrence of `{'ok': True, 'allowed': True, 'reasons': []}`; contain exactly ONE `class ` statement and no `import ` statements; `_evaluate_gate` must reference the module-level `_gate_transition` bare name (not `self._gate_transition`); `create_session` must return `{'ok': True, 'session_id': session_id, 'phase': _PHASES[0]}`; `get_state` must contain the `'status': 404` envelope; `transition` must contain `self._allowed_targets(current)`, the `'status': 422` envelope, and the `{'ok': True, 'session_id': session_id, 'from': current, 'to': to_phase}` success envelope.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM: `task_id`: `ngv2-fix-session-api-envelopes`. meta_task_type=`data_model` (external NGv2 target — the diff-fuzzer cannot resolve external imports, so use a fuzzer-bypassed, smoke-gated meta-type). priority: high. dependencies: []. working_dir: `/home/xnihil0zer0/NobleGreedv2`. files_touched: `["ngv2/session_api.py"]` ONLY. partial_edit semantics: a single `__JANUSMASK_PATCHES__` list with EXACTLY ONE `'symbol'` entry whose `name` is the 1-part top-level `'SessionApi'` (whole-class replacement per the DISPATCH DIRECTIVE — never dotted, never a manifest, never a whole-file rewrite, no extra nodes). The DISPATCH DIRECTIVE — PATCH FORMAT paragraph above MUST be copied VERBATIM into the task's `implementation_notes` together with the five pinned method/deletion deltas so the blind worker sees them. verification_command: `python -m pytest tests/ngv2/test_session_api_wired.py tests/ngv2/test_session_mcp_wired.py tests/ngv2/test_session_db_wired.py tests/ngv2/test_session_api_persistence_wired.py tests/ngv2/test_session_api_dup_wired.py tests/ngv2/test_session_api_classify_phase_wired.py tests/ngv2/test_session_api_audit_now_fn_wired.py tests/ngv2/test_session_mcp_main_wired.py --deselect tests/ngv2/test_session_api_persistence_wired.py::test_advance_full_lifecycle_to_done_over_bare_sessiondb --deselect tests/ngv2/test_session_api_persistence_wired.py::test_fsm_state_persists_across_sessiondb_reopen --deselect tests/ngv2/test_session_api_audit_now_fn_wired.py::test_default_construction_has_now_fn_attribute -q` (the three deselects are pre-existing reds from the SEPARATE advance-clobber/now_fn defects — do NOT try to fix them here and do NOT drop the deselects). The committed RED oracles tests/ngv2/test_session_api_wired.py (5 failing) and tests/ngv2/test_session_mcp_wired.py (2 failing) are the authoritative acceptance contract — make them GREEN; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from this brief's committed RED oracle files (plan descriptors referencing committed/landed tests — this does NOT authorize authoring new tests), so every `spec.edge_cases` entry is reflected per the validator's edge-case rule (e.g. `test_get_state_unknown_session_returns_404` and `test_transition_disallowed_returns_422_and_failed_audit`; also good: `test_transition_allowed_but_gate_fails_does_not_advance`, `test_create_session_then_get_state_reflects_hunt`, `test_transition_tool_delegates`).

# Non-Goals

This is an EDIT and integration is out of scope: the task's non_goals MUST declare integration testing out of scope — do NOT add integration/e2e tests; this fix is verified solely by the committed unit oracles listed in the verification command. Do NOT author or modify any test — those oracles are committed and authoritative. Apply ONLY the five Scope deltas inside `SessionApi`. Do NOT touch ngv2/session_gate.py (the dual-shape `gate_transition` landed at `ebb4a18` and is consumed as-is), ngv2/session_db.py, ngv2/session_mcp.py, ngv2/state_machine.py, ngv2/contracts.py, ngv2/phase_runner.py, or any other module. Do NOT change `__init__` (`self._now_fn` stays — the separate `now_fn` oracle red is OUT of scope), `advance` (the rich-lifecycle restoration of the advance-clobber is a SEPARATE follow-up brief; its 6 pre-existing red tests in test_session_api_persistence_wired.py and test_session_api_surface_wired.py stay red), `submit_artifacts`, `_append_audit`, `_load_table` (the reports table is `reports` in this schema — do NOT resurrect `live_test_reports`), `_classify`/`_validate_artifact`/`_persist_artifact`, the duck-typed `_load`/`_save`/`_as_dict` helpers, or any module-level symbol (`__all__`, `PHASE_ORDER`, `MANUAL_REVIEW`, `_PHASES`, `_KIND_CLASSES`, `_not_found`, `is_error`, the import blocks). Do NOT add new top-level symbols, imports, network, wall-clock, randomness, or third-party dependencies. The currently-green stay-green oracles (test_session_db_wired.py, test_session_api_dup_wired.py, test_session_api_classify_phase_wired.py, test_session_mcp_main_wired.py, the green subsets of test_session_api_persistence_wired.py and test_session_api_audit_now_fn_wired.py, and the 8 currently-green api/mcp cases) MUST STAY GREEN.

# Inputs

The committed authoritative RED oracles (NGv2 HEAD `ebb4a18`; fail counts confirmed live 2026-06-11, AFTER the sibling dual-shape gate fix landed — these 7 are pure session_api regressions):

- tests/ngv2/test_session_api_wired.py — 5/9 failing: `test_create_session_then_get_state_reflects_hunt`, `test_get_state_unknown_session_returns_404`, `test_transition_allowed_succeeds_and_writes_audit_row`, `test_transition_disallowed_returns_422_and_failed_audit`, `test_transition_allowed_but_gate_fails_does_not_advance`. Pins: `create_session` -> `{'ok': True, ..., 'phase': 'hunt'}`; `get_state` unknown -> `{'ok': False, 'status': 404, 'error': <non-empty str>}`; `transition` hunt->report (NOT in ALLOWED_TRANSITIONS = `{'hunt': ('triage','done'), ...}` from ngv2/state_machine.py:25) -> 422 + failed audit + phase unchanged; allowed-but-gate-failing hunt->triage with zero findings -> not ok, phase unchanged, audit row still written; allowed+gate-passing -> `{'ok': True, ..., 'to': to_phase}` + audit row + persisted phase advance.
- tests/ngv2/test_session_mcp_wired.py — 2/6 failing: `test_create_session_tool_delegates`, `test_transition_tool_delegates` — the MCP tool callables delegate straight to SessionApi, so they pin the same envelopes (`out.get('ok') is True`, `out.get('to') == 'triage'`, `api.get_state(...)['phase'] == 'triage'`).
- MUST-STAY-GREEN (run live 2026-06-11): tests/ngv2/test_session_db_wired.py, tests/ngv2/test_session_api_dup_wired.py (6 passing), tests/ngv2/test_session_api_classify_phase_wired.py (8 passing), tests/ngv2/test_session_mcp_main_wired.py — ALL currently green. tests/ngv2/test_session_api_persistence_wired.py is green EXCEPT 2 PRE-EXISTING reds (`test_advance_full_lifecycle_to_done_over_bare_sessiondb`, `test_fsm_state_persists_across_sessiondb_reopen` — the `1c525e9` advance-clobber storage-gap defect, separate brief) and tests/ngv2/test_session_api_audit_now_fn_wired.py is green EXCEPT 1 PRE-EXISTING red (`test_default_construction_has_now_fn_attribute` — wants `self.now_fn = None`, a separate `__init__` defect). Those 3 are explicitly `--deselect`ed in the verification command, NOT silently included. (Bonus, validated: this fix flips `test_unknown_session_transition_does_not_touch_now_fn` in the audit_now_fn file from red to green, because restored `transition` 404s before auditing.)

The `7ab704e` reference versions of the changed parts (READ-ONLY historical contract context from `git -C /home/xnihil0zer0/NobleGreedv2 show 7ab704e:ngv2/session_api.py` — the corrected methods in Scope keep these ENVELOPES but route storage through `1c525e9`'s duck-typed accessors instead of raw `_conn` SQL; reproduce Scope's versions, NOT these):

    def create_session(self, session_id: Any, target_spec: Any) -> Dict[str, Any]:
        """Persist a new session at phase 'hunt' via ``session_pipeline``."""
        data = {'session_id': session_id, 'target_spec': target_spec, 'phase': _INITIAL_PHASE}
        self.db._conn.execute('INSERT INTO session_pipeline (phase, data) VALUES (?, ?)', (_INITIAL_PHASE, json.dumps(data, sort_keys=True)))
        self._commit()
        return {'ok': True, 'session_id': session_id, 'phase': _INITIAL_PHASE}

    def get_state(self, session_id: Any) -> Dict[str, Any]:
        """Return the stored state for ``session_id`` or a 404-style dict."""
        data = self._load_session(session_id)
        if data is None:
            return {'ok': False, 'status': 404, 'error': 'unknown session_id: %r' % (session_id,)}
        return {'ok': True, 'session_id': session_id, 'phase': data.get('phase'), 'target_spec': data.get('target_spec')}

    def transition(self, session_id: Any, to_phase: Any) -> Dict[str, Any]:
        """Attempt a phase transition, auditing every attempt.

        Flow (per the reconciled contract):
          * 404 if the session is unknown.
          * ``allowed = to_phase in ALLOWED_TRANSITIONS.get(current, ())``.
          * ``gate_transition(rows, current, to_phase)`` is always evaluated.
          * An audit row is ALWAYS written (allowed, disallowed, gate-fail)
             before returning.
          * Only an allowed + gate-passing attempt advances the phase.
        """
        state = self.get_state(session_id)
        if not state.get('ok'):
            return state
        current = state.get('phase')
        target_spec = state.get('target_spec')
        allowed = to_phase in self._allowed_targets(current)
        gr_ok, gr_error = self._evaluate_gate(current, to_phase)
        ok = bool(allowed and gr_ok)
        if ok:
            audit_error: Optional[str] = None
        elif not gr_ok:
            audit_error = gr_error
        else:
            audit_error = 'transition not allowed'
        self._append_audit(session_id=session_id, from_phase=current, to_phase=to_phase, ok=ok, error=audit_error)
        if not allowed:
            return {'ok': False, 'status': 422, 'error': self._as_text(audit_error, 'transition not allowed: %r -> %r' % (current, to_phase))}
        if not gr_ok:
            return {'ok': False, 'status': 422, 'error': self._as_text(gr_error, 'gate validation failed')}
        self._delegate_next_phase(current)
        self._advance(session_id, target_spec, to_phase)
        self._commit()
        return {'ok': True, 'session_id': session_id, 'from': current, 'to': to_phase}

    def _evaluate_gate(self, current: Any, to_phase: Any) -> Tuple[bool, Optional[str]]:
        if _gate_transition is None:
            return (False, 'gate unavailable')
        rows = {'findings': self._load_table('findings'), 'pocs': self._load_table('pocs'), 'reports': self._load_table('live_test_reports')}
        try:
            result = _gate_transition(rows, current, to_phase)
        except Exception as exc:
            return (False, str(exc))
        gr_ok = bool(getattr(result, 'ok', False))
        gr_error = getattr(result, 'error', None)
        if gr_error is not None:
            gr_error = str(gr_error)
        return (gr_ok, gr_error)

(Note the deliberate divergences in Scope's corrected versions: storage stays duck-typed (`save_session`/`get_session`), `transition` keeps the current `approvals=None` third parameter because the current `advance` passes three arguments, `_evaluate_gate` keeps its current 3-arg signature, `_append_audit` keeps its current `(session_id, to_phase, record)` shape with a record dict carrying `from`/`to`/`ok`/`error`/`at`, and `_load_table('reports')` keeps the CURRENT schema's table name.)

stdlib + ngv2 only.

# Deliverables

Edited ngv2/session_api.py in which `SessionApi` is the staged HEAD class byte-for-byte EXCEPT the five Scope deltas: the permissive `_gate_transition` stub is GONE (44 method defs, down from 45), `_evaluate_gate` calls the real module-level `session_gate.gate_transition` over the legacy rows shape and normalizes to an `(ok, error)` tuple, `create_session` returns the `{'ok': True, 'session_id', 'phase': 'hunt'}` envelope, `get_state` returns the ok-envelope or the `{'ok': False, 'status': 404, 'error': ...}` envelope, and `transition` enforces the ALLOWED_TRANSITIONS allow-map, 404s on unknown sessions, always writes the audit row, 422s on disallowed/gate-failing attempts, and returns `{'ok': True, 'session_id', 'from', 'to'}` on success with the phase persisted through the duck-typed saver — with NO change to any other method, helper, or module-level symbol, so the duck-typed SessionDB storage reconciliation of `1c525e9` survives intact. Verified GREEN by the verification command in Required plan shape (the 7 RED api/mcp cases flip green; 47 pass with the 3 pre-existing reds deselected; validated end-to-end in a worktree on 2026-06-11 with zero new failures across the full tests/ngv2 sweep).
