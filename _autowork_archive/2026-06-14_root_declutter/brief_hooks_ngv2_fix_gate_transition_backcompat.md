---
interfaces: "edits ngv2/session_gate.py so gate_transition accepts BOTH calling conventions — the new lifecycle shape gate_transition(phase_from: str, phase_to: str, evidence) dispatching over _HANDLERS, AND the legacy rows shape gate_transition(rows: dict, from_phase, to_phase) restoring the four legacy artifact-gated edges (hunt->triage, triage->poc, poc->detonate orphan-check, detonate->report) plus the every-phase->'done' early-abort — un-breaking the production caller SessionApi._evaluate_gate (which still calls _gate_transition(rows, current, to_phase) and today gets TypeError: unhashable type: 'dict' at session_gate.py:142) and honoring state_machine.py:102's additive-compatibility promise"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/session_gate.py — make `gate_transition` accept BOTH calling conventions (new lifecycle `(phase_from, phase_to, evidence)` over `_HANDLERS`, and the legacy `(rows, from_phase, to_phase)` artifact-gate shape with the `*->done` early-abort), restoring the contract the bounty-FSM epic silently broke for the production caller `SessionApi._evaluate_gate`

# Scope

EDIT the EXISTING module ngv2/session_gate.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). DISPATCH ORDER: both sibling briefs (`ngv2_fix_audit_log_arity` = NGv2 `7ab704e`, `ngv2_reconcile_sessiondb_contract` = NGv2 `1c525e9`) have ALREADY integrated — this brief is dispatchable now.

⚠️ 2026-06-11 RE-DISPATCH UPDATE (attempt 1 post-mortem — READ THIS): attempt 1's draft was BYTE-PERFECT (it flipped all 19 legacy gate tests green and kept all 49 new-lifecycle tests green) but was rejected ONLY because the verification command also ran tests/ngv2/test_session_api_wired.py and tests/ngv2/test_session_mcp_wired.py. Those 7 residual failures are UNREACHABLE from ngv2/session_gate.py: sibling commit `1c525e9` rewrote SessionApi so that `_evaluate_gate` now calls `self._gate_transition` — a permissive INSTANCE-METHOD STUB at ngv2/session_api.py:586 returning `{'ok': True, 'allowed': True, 'reasons': []}` that shadows the module-level import of the real gate — and dropped the legacy `ok`/404/422/`to` envelopes and the ALLOWED_TRANSITIONS check from `create_session`/`get_state`/`transition`. Restoring those is a SEPARATE follow-up brief against ngv2/session_api.py. The two api/mcp test files have therefore been REMOVED from this brief's verification command; everything else (the fix, the pinned function, the patch format) is UNCHANGED.

DEFECT (verified against NGv2 HEAD `44bfb3c`, 2026-06-11): the lifecycle epic REPLACED the legacy signature `gate_transition(rows, from_phase, to_phase)` with `gate_transition(phase_from, phase_to, evidence)` dispatching over the new `_HANDLERS` table. The current source at ngv2/session_gate.py lines 140-145 is:

    def gate_transition(phase_from: str, phase_to: str, evidence: Any) -> GateResult:
        """Dispatch an evidence-gated lifecycle transition to its sibling gate."""
        handler = _HANDLERS.get((phase_from, phase_to))
        if handler is None:
            return GateResult(ok=False, phase_from=phase_from, phase_to=phase_to, error='no_gate')
        return handler(phase_from, phase_to, evidence)

The legacy `_TRANSITIONS` table (line 138) is now DEAD CODE — and it is itself BROKEN for re-use because its `('poc', 'detonate')` entry points at the REWRITTEN 3-arg `_gate_poc_to_detonate(pf, pt, ev)` (lines 118-123, semantic-verdict based), not the legacy rows-based orphan-PoC gate. The production caller `SessionApi._evaluate_gate` (ngv2/session_api.py line 190) STILL calls the legacy shape:

    result = _gate_transition(rows, current, to_phase)

so `_HANDLERS.get((phase_from, phase_to))` at session_gate.py line 142 computes `hash()` of a tuple whose first element is the `rows` DICT → `TypeError: unhashable type: 'dict'` on EVERY transition attempt (swallowed by `_evaluate_gate`'s `except Exception`, so every legacy transition 422s with `unhashable type: 'dict'`). This violates the additive-compatibility promise pinned in the ngv2/state_machine.py module docstring (line 102): "The canonical PHASES / ALLOWED_TRANSITIONS contract is preserved unchanged for backward compatibility -- existing callers and oracles keep working."

THE FIX (data_model — restore the dual-shape dispatch in ONE function, no other symbol changes): replace `gate_transition` with a version that dispatches on `isinstance(arg0, str)`: a string first argument routes to the NEW `_HANDLERS` lifecycle dispatch (byte-identical behavior to HEAD, including the `no_gate` fallback); a non-string first argument is the legacy `rows` dict and routes to the legacy artifact gates — the `*->done` early-abort FIRST (before the empty-rows guard), then the empty-rows guard, then the four legacy edges, with the legacy rows-based poc->detonate orphan-PoC check INLINED (its old helper body was clobbered; recovered verbatim from NGv2 commit `289707d`). `SessionApi._evaluate_gate` keeps its existing canonical call `_gate_transition(rows, current, to_phase)` UNCHANGED — once `gate_transition` self-dispatches, the caller works as-is, so this brief touches ONLY ngv2/session_gate.py. Read the read-only staged target at `{WORK_DIR}/inbox/targets/ngv2/session_gate.py` FIRST to confirm the current function body and that `GateResult` already carries `phase_from`/`phase_to`/`error` fields (lines 40-48) and that `_load_findings`/`_load_pocs`/`_gate_hunt_to_triage`/`_gate_triage_to_poc`/`_gate_detonate_to_report` (rows-based) all exist ABOVE line 140. NO new imports are needed. EXACT corrected target (reproduce VERBATIM):

    def gate_transition(phase_from: Any, phase_to: Any, evidence: Any=None) -> GateResult:
        """Dispatch a lifecycle gate; accepts BOTH calling conventions.

        New (lifecycle): ``gate_transition(phase_from: str, phase_to: str, evidence)``
        dispatches over ``_HANDLERS``.  Legacy (rows): ``gate_transition(rows: dict,
        from_phase, to_phase)`` evaluates the four artifact gates plus the
        every-phase -> 'done' early-abort, exactly as before the lifecycle epic.
        """
        if isinstance(phase_from, str):
            handler = _HANDLERS.get((phase_from, phase_to))
            if handler is None:
                return GateResult(ok=False, phase_from=phase_from, phase_to=phase_to, error='no_gate')
            return handler(phase_from, phase_to, evidence)
        rows, from_phase, to_phase = (phase_from, phase_to, evidence)
        if to_phase == 'done':
            return GateResult(ok=True, error=None)
        if not rows:
            return GateResult(ok=False, error='No artifacts found')
        if (from_phase, to_phase) == ('poc', 'detonate'):
            try:
                findings = _load_findings(rows)
                pocs = _load_pocs(rows)
            except (ValueError, TypeError, KeyError) as exc:
                return GateResult(ok=False, error='Invalid artifact: ' + str(exc))
            if not pocs:
                return GateResult(ok=False, error='No artifacts found')
            registered = {f.id for f in findings}
            orphans = [p.finding_id for p in pocs if p.finding_id not in registered]
            if orphans:
                return GateResult(ok=False, error='Orphan PoC(s) with no registered finding: ' + ', '.join(sorted(set(orphans))))
            return GateResult(ok=True, error=None)
        legacy_handlers = {('hunt', 'triage'): _gate_hunt_to_triage, ('triage', 'poc'): _gate_triage_to_poc, ('detonate', 'report'): _gate_detonate_to_report}
        handler = legacy_handlers.get((from_phase, to_phase))
        if handler is None:
            return GateResult(ok=False, error='Unknown transition: ' + str(from_phase) + ' -> ' + str(to_phase))
        return handler(rows)

Keep the function pure/deterministic (no clock/randomness/network/subprocess). Verify GREEN with `python -m pytest tests/ngv2/test_session_gate_wired.py tests/ngv2/test_session_gate_done_wired.py tests/ngv2/test_session_gate_bind_reconciliation_wired.py tests/ngv2/test_gate_result_fields_wired.py tests/ngv2/test_source_hunt_qualify_arity_wired.py tests/ngv2/test_lifecycle_fsm_wiring_wired.py -q`; working_dir is /home/xnihil0zer0/NobleGreedv2.

DISPATCH DIRECTIVE — PATCH FORMAT (single whole-symbol patch on an EXISTING 1-part top-level function — the canonical safe shape): emit a single top-level `__JANUSMASK_PATCHES__` list with EXACTLY ONE entry:

    __JANUSMASK_PATCHES__ = [
        {'file': 'ngv2/session_gate.py', 'kind': 'symbol', 'name': 'gate_transition',
         'code': r'''<the EXACT corrected gate_transition function pinned in Scope, byte-for-byte>'''},
    ]

The `name` MUST be the 1-part TOP-LEVEL name `'gate_transition'` — never a dotted qualname, never a manifest, never a whole-file rewrite, never any extra top-level node (the fix needs NO new symbol and NO new import: `GateResult`, `_HANDLERS`, `_load_findings`, `_load_pocs`, `_gate_hunt_to_triage`, `_gate_triage_to_poc`, `_gate_detonate_to_report`, `Any` all already exist at module level — `_HANDLERS` is defined AFTER `gate_transition` in the file, which is fine because it is resolved at call time). The emitted `code` must reproduce the corrected function from Scope BYTE-FOR-BYTE — minimal change relative to HEAD: only this one function body changes; `_TRANSITIONS`, `_HANDLERS`, every `_gate_*` helper, `GateResult`, `semantic_verdict`, and the `_bind` seam table stay untouched. POST-EMIT SELF-CHECK (mandatory): your emitted `code` must START with `def gate_transition(` at column 0; contain BOTH dispatch branches (`isinstance(phase_from, str)` then the legacy `rows, from_phase, to_phase = (phase_from, phase_to, evidence)` unpack); contain the `to_phase == 'done'` early-abort BEFORE the `if not rows:` guard; contain the inlined orphan-PoC block and the `legacy_handlers` dict with EXACTLY the three edges `('hunt', 'triage')`, `('triage', 'poc')`, `('detonate', 'report')`; and contain exactly ONE top-level `def` and no `class ` / `import ` statements.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM: `task_id`: `ngv2-fix-gate-transition-backcompat`. meta_task_type=`data_model` (external NGv2 target — the diff-fuzzer cannot resolve external imports, so use a fuzzer-bypassed, smoke-gated meta-type). priority: high. dependencies: []. working_dir: `/home/xnihil0zer0/NobleGreedv2`. files_touched: `["ngv2/session_gate.py"]` ONLY. partial_edit semantics: a single `__JANUSMASK_PATCHES__` list with EXACTLY ONE `'symbol'` entry whose `name` is the 1-part top-level `'gate_transition'` (whole-function replacement per the DISPATCH DIRECTIVE — never dotted, never a manifest, never a whole-file rewrite, no extra nodes). The DISPATCH DIRECTIVE — PATCH FORMAT paragraph above MUST be copied VERBATIM into the task's `implementation_notes` together with the full corrected function source so the blind worker sees it. verification_command: `python -m pytest tests/ngv2/test_session_gate_wired.py tests/ngv2/test_session_gate_done_wired.py tests/ngv2/test_session_gate_bind_reconciliation_wired.py tests/ngv2/test_gate_result_fields_wired.py tests/ngv2/test_source_hunt_qualify_arity_wired.py tests/ngv2/test_lifecycle_fsm_wiring_wired.py -q` (do NOT add tests/ngv2/test_session_api_wired.py or tests/ngv2/test_session_mcp_wired.py — their residual failures live in ngv2/session_api.py and are out of this brief's reach; see the RE-DISPATCH UPDATE in Scope). The committed RED oracles tests/ngv2/test_session_gate_wired.py (10 failing) and tests/ngv2/test_session_gate_done_wired.py (9 failing) are the authoritative acceptance contract — make them GREEN; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from this brief's committed RED oracle files (plan descriptors referencing committed/landed tests — this does NOT authorize authoring new tests), so every `spec.edge_cases` entry is reflected per the validator's edge-case rule (e.g. `test_hunt_to_triage_passes_with_valid_finding` and `test_every_phase_to_done_is_allowed`; also good: `test_done_with_empty_rows_dict_is_allowed`, `test_poc_to_detonate_fails_on_orphan_poc`).

# Non-Goals

This is an EDIT and integration is out of scope: the task's non_goals MUST declare integration testing out of scope — do NOT add integration/e2e tests; this fix is verified solely by the committed unit oracles listed in the verification command. Do NOT author or modify any test — those oracles are committed and authoritative. Rewrite `gate_transition` ONLY. Do NOT touch ngv2/session_api.py — `SessionApi._evaluate_gate`'s existing call `_gate_transition(rows, current, to_phase)` is the canonical legacy call and works unchanged once `gate_transition` self-dispatches. Do NOT change ANY gate handler (`_gate_hunt_to_triage`, `_gate_triage_to_poc`, `_gate_poc_to_detonate` (the new 3-arg one), `_gate_detonate_to_report`, `_gate_source_to_hunt`, `_gate_triage_to_verify`, `_gate_verify_to_poc`, `_gate_detonate_to_novelty`, `_gate_novelty_to_report`, `_gate_report_to_awaiting`, `_gate_awaiting_to_submitted`, `_gate_submitted_to_done`), the `_HANDLERS` table, the now-dead `_TRANSITIONS` table (leave it byte-for-byte as-is; the legacy edges are dispatched via the function-local `legacy_handlers` dict because `_TRANSITIONS[('poc','detonate')]` points at the WRONG, rewritten 3-arg handler), the `GateResult` dataclass, the `_bind` seam table, `semantic_verdict`, or any helper. Do NOT add new top-level symbols, imports, network, wall-clock, randomness, or third-party dependencies. Do NOT touch ngv2/state_machine.py, ngv2/session_db.py, ngv2/contracts.py, ngv2/phase_runner.py, or any other module. The new-lifecycle oracles tests/ngv2/test_session_gate_bind_reconciliation_wired.py, test_gate_result_fields_wired.py, test_source_hunt_qualify_arity_wired.py and test_lifecycle_fsm_wiring_wired.py are currently GREEN (49 passing) and MUST STAY GREEN — the string-typed first-argument branch must remain byte-identical in behavior to HEAD's `_HANDLERS` dispatch incl. the `no_gate` fallback for unknown edges like `('nowhere', 'elsewhere')`.

# Inputs

The committed authoritative RED oracles (NGv2 HEAD `44bfb3c`; fail counts confirmed live 2026-06-11):

- tests/ngv2/test_session_gate_wired.py — 10/10 failing (`test_gateresult_shape`, `test_hunt_to_triage_passes_with_valid_finding`, `test_hunt_to_triage_fails_with_zero_findings`, `test_hunt_to_triage_fails_with_missing_findings_key`, `test_triage_to_poc_passes_with_deduped_findings`, `test_triage_to_poc_fails_on_duplicate_finding_ids`, `test_poc_to_detonate_passes_when_every_poc_maps_to_finding`, `test_poc_to_detonate_fails_on_orphan_poc`, `test_detonate_to_report_passes_when_every_poc_has_report`, `test_detonate_to_report_fails_when_a_poc_lacks_report`) — all call the legacy shape `gate_transition({'findings': [...], ...}, 'hunt', 'triage')` etc. and today die on `TypeError: unhashable type: 'dict'`.
- tests/ngv2/test_session_gate_done_wired.py — 9/9 failing — pins the `*->done` early-abort: `gate_transition(rows, from_phase, 'done')` returns `ok=True, error=None` for ANY from_phase, BEFORE the empty-rows guard (`test_done_with_empty_rows_dict_is_allowed` passes `rows == {}`) and with NO artifact deserialization (`test_done_skips_artifact_gating_entirely` passes duplicate finding ids that fail triage->poc); unknown NON-done edges still fail with a non-empty diagnostic (`test_regression_unknown_non_done_transition_still_fails`, hunt->report).
- tests/ngv2/test_session_api_wired.py and tests/ngv2/test_session_mcp_wired.py are NOT part of this brief's contract (removed 2026-06-11): their 7 residual failures are caused by ngv2/session_api.py at NGv2 `1c525e9` (permissive `self._gate_transition` stub at session_api.py:586 shadowing the real gate; legacy `ok`/404/422/`to` envelopes and the ALLOWED_TRANSITIONS check dropped from `create_session`/`get_state`/`transition`) and are unreachable from ngv2/session_gate.py. They belong to the follow-up session_api legacy-surface brief.
- MUST-STAY-GREEN: tests/ngv2/test_session_gate_bind_reconciliation_wired.py, tests/ngv2/test_gate_result_fields_wired.py, tests/ngv2/test_source_hunt_qualify_arity_wired.py, tests/ngv2/test_lifecycle_fsm_wiring_wired.py (49 passing today).

The EXACT current defective source (ngv2/session_gate.py lines 140-145 at HEAD) and the dead/broken legacy table (line 138) are quoted in Scope. The CANONICAL legacy production caller (as it stood at NGv2 `7ab704e`, before `1c525e9` temporarily swapped in a stub — READ-ONLY historical context; the follow-up session_api brief restores this call shape; do not edit session_api.py):

    def _evaluate_gate(self, current: Any, to_phase: Any) -> Tuple[bool, Optional[str]]:
        if _gate_transition is None:
            return (False, 'gate unavailable')
        rows = {'findings': self._load_table('findings'), 'pocs': self._load_table('pocs'), 'reports': self._load_table('live_test_reports')}
        try:
            result = _gate_transition(rows, current, to_phase)
        except Exception as exc:
            return (False, str(exc))
        ...

The LEGACY reference implementation this fix restores (recovered verbatim from `git -C /home/xnihil0zer0/NobleGreedv2 show 289707d:ngv2/session_gate.py` — the pre-epic `gate_transition` plus the legacy rows-based `_gate_poc_to_detonate` whose orphan-check body is inlined into the corrected function):

    def _gate_poc_to_detonate(rows: Dict[str, List[dict]]) -> GateResult:   # legacy, now clobbered
        try:
            findings = _load_findings(rows)
            pocs = _load_pocs(rows)
        except (ValueError, TypeError, KeyError) as exc:
            return GateResult(ok=False, error='Invalid artifact: ' + str(exc))
        if not pocs:
            return GateResult(ok=False, error='No artifacts found')
        registered = {f.id for f in findings}
        orphans = [p.finding_id for p in pocs if p.finding_id not in registered]
        if orphans:
            return GateResult(ok=False, error='Orphan PoC(s) with no registered finding: ' + ', '.join(sorted(set(orphans))))
        return GateResult(ok=True, error=None)

    def gate_transition(rows, from_phase, to_phase):                        # legacy dispatch
        if to_phase == 'done':
            return GateResult(ok=True, error=None)
        if not rows:
            return GateResult(ok=False, error='No artifacts found')
        handler = _TRANSITIONS.get((from_phase, to_phase))
        if handler is None:
            return GateResult(ok=False, error='Unknown transition: ' + str(from_phase) + ' -> ' + str(to_phase))
        return handler(rows)

stdlib + ngv2 only.

# Deliverables

Edited ngv2/session_gate.py in which `gate_transition` is the EXACT dual-shape function pinned in Scope — string first argument → byte-identical new `_HANDLERS` lifecycle dispatch with the `no_gate` fallback; dict (rows) first argument → legacy dispatch with the `*->done` early-abort before the empty-rows guard, the inlined legacy orphan-PoC poc->detonate gate, and the three remaining legacy edges via `_gate_hunt_to_triage` / `_gate_triage_to_poc` / `_gate_detonate_to_report` — with NO change to any other symbol, table, import, or docstring, so the production caller `SessionApi._evaluate_gate` works again and the additive-compatibility promise of state_machine.py:102 holds. Verified GREEN by the verification command in Required plan shape (19 legacy gate tests flip green; the 49 new-lifecycle tests stay green — 68 total).
