---
interfaces: "edits ngv2/session_api.py so SessionApi speaks BOTH reconciled contracts at once — KEEPS commit 1865c5e's restored ok/404/422 legacy envelopes (create_session/get_state/transition untouched) AND restores the bounty-lifecycle FSM advance() public surface that 1865c5e's integration clobbered: public `now_fn` attribute initialized in __init__, `advance(session_id, approval_decision=None)` driving the autonomous PHASE_ORDER walk that parks at awaiting_submission and releases to done on approval, returning top-level `phase`/`parked`/`reason`/`transitions` keys, plus the dict-aware @staticmethod `_truthy_approval` so `{'approved': False}` REJECTS"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/session_api.py — FINAL SessionApi reconciliation: restore the FSM `advance()` public surface (public `now_fn`, `approval_decision=` kwarg, top-level `phase`/`parked`/`reason`/`transitions` result keys, dict-aware approval rejection) that the `1865c5e` envelope fix clobbered, while keeping every `1865c5e` envelope byte-for-byte — un-breaking the 7 RED committed-oracle cases, verified by the FULL anti-seesaw UNION of all 9 SessionApi-touching oracle files (56 cases)

# Scope

EDIT the EXISTING module ngv2/session_api.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). This brief is the FINAL leg of the SessionApi seesaw: the envelope sibling (`ngv2_fix_session_api_envelopes`, integrated as NGv2 `1865c5e`) restored the legacy ok/404/422 envelopes on `create_session`/`get_state`/`transition` but its integration left `advance()` as the LEGACY one-step stub, `_truthy_approval` as a naive instance method, and `__init__` without the public `now_fn` attribute — clobbering the rich bounty-lifecycle FSM surface that commit `2b3d9c4` added and that committed oracles + the live e2e driver pin. This brief is dispatchable now; do NOT touch any envelope behavior `1865c5e` restored.

DEFECT (verified live against NGv2 HEAD `c010797`, 2026-06-11). Three coupled regressions, all inside class `SessionApi`:

(i) `__init__` (session_api.py:60) stores only the PRIVATE delegate:

    def __init__(self, db, now_fn=None):
        self.db = db
        self._now_fn = now_fn if now_fn is not None else lambda: 0

so `hasattr(api, 'now_fn')` is False — the committed audit oracle requires a PUBLIC `now_fn` attribute that defaults to None.

(ii) `advance` (session_api.py:520) is the legacy one-step stub:

    def advance(self, session_id, approvals=None):
        state = self.get_state(session_id) or {'session_id': session_id, 'phase': _PHASES[0]}
        current = state.get('phase', _PHASES[0])
        try:
            index = _PHASES.index(current)
        except ValueError:
            index = 0
        to_phase = _PHASES[min(index + 1, len(_PHASES) - 1)]
        return self.transition(session_id, to_phase, approvals)

It takes `approvals=` (the oracles call `advance(sid, approval_decision={...})` -> TypeError: unexpected keyword argument 'approval_decision') and returns `transition`'s envelope `{'ok', 'session_id', 'from', 'to'}` with NO top-level `phase`/`parked`/`reason`/`transitions` keys (-> KeyError 'phase' / KeyError 'parked' in the oracles and in _e2e_run/drive_full_lifecycle.py:232-233, which pins `parked["parked"] is True and parked["phase"] == "awaiting_submission"`). CHECKED 2026-06-11: NO caller anywhere in ngv2/, _e2e_run/, or scripts/ passes `approvals=` to `advance` (the only live caller is drive_full_lifecycle.py:232, positional, no kwarg), so renaming the kwarg to `approval_decision` breaks nothing; `transition` keeps its own `approvals=None` parameter UNTOUCHED.

(iii) `_truthy_approval` (session_api.py:558) was downgraded to a naive instance method:

    def _truthy_approval(self, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ('1', 'true', 'yes', 'y', 'approve', 'approved', 'ok')
        return bool(value)

`bool({'approved': False})` is True (non-empty dict), so a REJECTING decision would RELEASE the parked FSM — the oracle `test_rejecting_approval_stays_parked` pins the opposite. The dict-aware `2b3d9c4`/`044740a` @staticmethod version (which `_is_approved` at session_api.py:541 already calls via `SessionApi._truthy_approval(...)` — an unbound 1-arg call that TypeErrors against the current instance method) must come back. The module-level `_APPROVE_LABELS` frozenset it needs already exists at session_api.py:621. NOTE: `ngv2.human_approval_gate` does NOT exist in this tree, so `_approval_gate` is None and `_is_approved` always falls through to `_truthy_approval` — the staticmethod IS the live approval seam.

All supporting plumbing ALREADY EXISTS and is untouched: the FSM helpers `_load`/`_save`/`_as_dict`/`_extract_phase`/`_set_phase`/`_next_phase`/`_record`/`_build_package`/`_compute_readiness_reason`/`_is_approved`, the module constants `PHASE_ORDER`/`MANUAL_REVIEW`/`_REQUIRED_ARTIFACTS`/`_APPROVE_LABELS`/`_not_found`, AND — critically — `ngv2.session_db.SessionDB` now has REAL `get_session`/`save_session` accessors (session_db.py:240/252, backed by the `session_pipeline` table), so the restored FSM `advance` persists over a BARE SessionDB with zero storage work (the old storage-gap memory entry is OBSOLETE for this path).

THE FIX (data_model — ONE whole-class symbol patch on `SessionApi`; THREE pinned deltas, everything else byte-for-byte): reproduce the staged class EXACTLY as-is EXCEPT:

1. REPLACE `__init__` (add the public attribute; KEEP the private delegate — `transition` still reads `self._now_fn()` for the audit `'at'` stamp):

    def __init__(self, db, now_fn=None):
        self.db = db
        self.now_fn = now_fn
        self._now_fn = now_fn if now_fn is not None else lambda: 0

2. REPLACE `advance` with the FSM driver (the `2b3d9c4`/`044740a` body verbatim, plus `'ok': True` added to the success envelope to match the `1865c5e` envelope convention; signature kwarg is `approval_decision=None`, NOT `approvals`):

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

3. REPLACE `_truthy_approval` with the dict-aware @staticmethod (the `044740a` version verbatim; `_APPROVE_LABELS` already exists at module level; `transition`'s existing `self._truthy_approval(approvals)` call keeps working — bound staticmethod lookup):

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

Every other method — `create_session`, `get_state`, `transition`, `submit_artifacts`, `_append_audit`, `_evaluate_gate`, `_load_table`, the dead `_gate_transition` instance stub at the end of the class (shadowed dead code; leave it EXACTLY as-is), all `_load`/`_save` plumbing — stays byte-for-byte. NO new imports, NO new module-level symbols, NO other method changes. This exact three-delta class was validated live in a scratch run on 2026-06-11 (then reverted): the 7 RED oracle cases flip GREEN, the verification command below passes 56/56, and a full tests/ngv2 sweep shows ZERO new failures. Read the read-only staged target at `{WORK_DIR}/inbox/targets/ngv2/session_api.py` FIRST and reproduce everything outside the three deltas byte-for-byte.

Keep the class pure/deterministic (no clock/randomness/network/subprocess beyond what HEAD already does). Verify GREEN with the ANTI-SEESAW UNION command — the FULL set of all 9 committed SessionApi-touching oracle files, NO deselects, so no contract can silently drop again: `python -m pytest tests/ngv2/test_session_api_wired.py tests/ngv2/test_session_api_surface_wired.py tests/ngv2/test_session_api_persistence_wired.py tests/ngv2/test_session_api_audit_now_fn_wired.py tests/ngv2/test_session_api_dup_wired.py tests/ngv2/test_session_api_classify_phase_wired.py tests/ngv2/test_session_mcp_wired.py tests/ngv2/test_session_mcp_main_wired.py tests/ngv2/test_session_db_wired.py -q`; working_dir is /home/xnihil0zer0/NobleGreedv2. Expected: 56 passed, 0 failed (verified live: 56/56 with the deltas; 49 passed / 7 failed without them).

DISPATCH DIRECTIVE — PATCH FORMAT (single whole-symbol patch on an EXISTING 1-part top-level class — the canonical safe shape): emit a single top-level `__JANUSMASK_PATCHES__` list with EXACTLY ONE entry:

    __JANUSMASK_PATCHES__ = [
        {'file': 'ngv2/session_api.py', 'kind': 'symbol', 'name': 'SessionApi',
         'code': r'''<the ENTIRE corrected SessionApi class: the staged HEAD class byte-for-byte EXCEPT the three deltas pinned in Scope>'''},
    ]

The `name` MUST be the 1-part TOP-LEVEL name `'SessionApi'` — never a dotted qualname, never a manifest, never a whole-file rewrite, never any extra top-level node (the fix needs NO new symbol and NO new import: `PHASE_ORDER`, `MANUAL_REVIEW`, `_APPROVE_LABELS`, `_not_found`, `_PHASES` all already exist at module level; several are defined AFTER the class in the file, which is fine because they are resolved at call time). The emitted `code` must reproduce the WHOLE class — docstring, every untouched method byte-for-byte in the original order — with ONLY the three Scope deltas applied. POST-EMIT SELF-CHECK (mandatory): your emitted `code` must START with `class SessionApi:` at column 0; contain EXACTLY 45 method `def `s (HEAD has 45 and the three deltas REPLACE methods 1-for-1 — COUNT THEM; the whole FILE has 47 `def `s, the extra 2 are the module-level `_not_found`/`is_error` which you must NOT emit); contain exactly ONE `class ` statement and no `import ` statements; `__init__` must contain BOTH `self.now_fn = now_fn` AND `self._now_fn = now_fn if now_fn is not None else lambda: 0`; `advance`'s signature must be `def advance(self, session_id, approval_decision=None):` and its body must contain `'parked': parked` and `'transitions': transitions` and NO call to `self.transition`; `_truthy_approval` must carry a `@staticmethod` decorator and reference `_APPROVE_LABELS`; the legacy advance markers `approvals=None` must appear EXACTLY ONCE in your emitted class (on `transition`, which is untouched — NOT on `advance`); the dead `def _gate_transition(self, rows, current, to_phase):` stub must still be present unchanged.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM: `task_id`: `ngv2-fix-advance-surface`. meta_task_type=`data_model` (external NGv2 target — the diff-fuzzer cannot resolve external imports, so use a fuzzer-bypassed, smoke-gated meta-type). priority: high. dependencies: []. working_dir: `/home/xnihil0zer0/NobleGreedv2`. files_touched: `["ngv2/session_api.py"]` ONLY. partial_edit semantics: a single `__JANUSMASK_PATCHES__` list with EXACTLY ONE `'symbol'` entry whose `name` is the 1-part top-level `'SessionApi'` (whole-class replacement per the DISPATCH DIRECTIVE — never dotted, never a manifest, never a whole-file rewrite, no extra nodes). The DISPATCH DIRECTIVE — PATCH FORMAT paragraph above MUST be copied VERBATIM into the task's `implementation_notes` together with the three pinned method deltas so the blind worker sees them. verification_command: `python -m pytest tests/ngv2/test_session_api_wired.py tests/ngv2/test_session_api_surface_wired.py tests/ngv2/test_session_api_persistence_wired.py tests/ngv2/test_session_api_audit_now_fn_wired.py tests/ngv2/test_session_api_dup_wired.py tests/ngv2/test_session_api_classify_phase_wired.py tests/ngv2/test_session_mcp_wired.py tests/ngv2/test_session_mcp_main_wired.py tests/ngv2/test_session_db_wired.py -q` (the FULL anti-seesaw union, 56 cases, NO deselects — every prior SessionApi contract must hold simultaneously). The committed RED oracles tests/ngv2/test_session_api_surface_wired.py (4 failing), tests/ngv2/test_session_api_persistence_wired.py (2 failing), and tests/ngv2/test_session_api_audit_now_fn_wired.py (1 failing) are the authoritative acceptance contract — make them GREEN; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from this brief's committed RED oracle files (plan descriptors referencing committed/landed tests — this does NOT authorize authoring new tests), so every `spec.edge_cases` entry is reflected per the validator's edge-case rule (e.g. `test_advance_halts_at_awaiting_submission_without_approval` and `test_rejecting_approval_stays_parked`; also good: `test_advance_parks_on_missing_required_artifact`, `test_approving_decision_advances_to_done`, `test_advance_full_lifecycle_to_done_over_bare_sessiondb`, `test_default_construction_has_now_fn_attribute`).

# Non-Goals

This is an EDIT and integration is out of scope: the task's non_goals MUST declare integration testing out of scope — do NOT add integration/e2e tests; this fix is verified solely by the committed unit oracles in the verification command. Do NOT author or modify any test — those oracles are committed and authoritative. Apply ONLY the three Scope deltas inside `SessionApi`. Do NOT touch `create_session`, `get_state`, `transition`, or `submit_artifacts` — the `1865c5e` ok/404/422 envelopes they speak are pinned green by tests/ngv2/test_session_api_wired.py and test_session_mcp_wired.py and MUST survive byte-for-byte (`transition` KEEPS its `approvals=None` parameter and its `self._truthy_approval(approvals)` call — only `advance`'s kwarg is renamed). Do NOT delete or alter the dead `_gate_transition` instance stub at the end of the class (out of scope; it is shadowed dead code). Do NOT touch ngv2/session_gate.py, ngv2/session_db.py (its `get_session`/`save_session` accessors are consumed as-is), ngv2/session_mcp.py, ngv2/state_machine.py, ngv2/contracts.py, ngv2/phase_runner.py, or any other module. Do NOT change `_append_audit`, `_evaluate_gate`, `_load_table`, `_classify`/`_validate_artifact`/`_persist_artifact`, the duck-typed `_load`/`_save`/`_as_dict` helpers, `_is_approved`, or any module-level symbol (`__all__`, `PHASE_ORDER`, `MANUAL_REVIEW`, `HALT_PHASES`, `_REQUIRED_ARTIFACTS`, `_APPROVE_LABELS`, `_PHASES`, `_KIND_CLASSES`, `_not_found`, `is_error`, the import blocks). Do NOT remove `self._now_fn` (the audit `'at'` stamp in `transition` reads it). Do NOT add new top-level symbols, imports, network, wall-clock, randomness, or third-party dependencies. The 49 currently-green union cases MUST STAY GREEN.

# Inputs

The committed authoritative RED oracles. RED/GREEN SPLIT recorded live 2026-06-11 against NGv2 HEAD `c010797` by running the exact verification command: **49 passed, 7 failed** — the 7 reds, ALL regressions of the `advance` surface:

- tests/ngv2/test_session_api_surface_wired.py — 4/6 failing: `test_advance_parks_on_missing_required_artifact` (KeyError 'parked'), `test_advance_halts_at_awaiting_submission_without_approval` (KeyError 'phase'), `test_rejecting_approval_stays_parked` and `test_approving_decision_advances_to_done` (both: TypeError advance() got an unexpected keyword argument 'approval_decision'). Pins: `advance(session_id)` walks PHASE_ORDER from 'source', parks at `awaiting_submission` with `{'parked': True, 'reason': 'awaiting_operator_approval', 'transitions': [...]}` when ready, parks earlier with `reason` naming the missing `_REQUIRED_ARTIFACTS` entry when not; `advance(sid, approval_decision={'approved': False})` stays parked; `{'approved': True}` releases through 'submitted' to `{'phase': 'done', 'parked': False}`; `get_parked_package` returns the fully-populated turn-in package.
- tests/ngv2/test_session_api_persistence_wired.py — 2/3 failing: `test_advance_full_lifecycle_to_done_over_bare_sessiondb`, `test_fsm_state_persists_across_sessiondb_reopen` (both: KeyError 'phase'). Pins the SAME surface over a BARE, un-subclassed SessionDB (its real `get_session`/`save_session` at session_db.py:240/252 carry the FSM state in `session_pipeline`), including survival across close + reopen.
- tests/ngv2/test_session_api_audit_now_fn_wired.py — 1/3 failing: `test_default_construction_has_now_fn_attribute` — pins `hasattr(api, 'now_fn')` and `api.now_fn is None` on default construction; the other 2 cases in that file (audit row written with `from`/`to`, no `'ts'` key; 404 before audit) are GREEN and pin the CURRENT `transition`/`_append_audit` behavior — delta 1 must not disturb them.
- MUST-STAY-GREEN (the other 49 union cases, run live 2026-06-11): tests/ngv2/test_session_api_wired.py (9 — the `1865c5e` envelopes), tests/ngv2/test_session_api_dup_wired.py (6), tests/ngv2/test_session_api_classify_phase_wired.py (8), tests/ngv2/test_session_mcp_wired.py (6), tests/ngv2/test_session_mcp_main_wired.py, tests/ngv2/test_session_db_wired.py, plus the green subsets of the three red files (incl. `test_initial_phase_is_source`, `test_advance_is_non_vacuous`, `test_get_current_phase_reads_bare_sessiondb_storage`).
- Live-path pin: _e2e_run/drive_full_lifecycle.py:232-233 calls `parked = api.advance(SID)` and asserts `parked["parked"] is True and parked["phase"] == "awaiting_submission"` — the same surface, no kwarg.

The `044740a` reference version of the FSM surface (READ-ONLY historical contract context from `git -C /home/xnihil0zer0/NobleGreedv2 show 044740a:ngv2/session_api.py`): its `advance` and `_truthy_approval` are the bodies pinned in Scope deltas 2-3 (Scope's `advance` additionally carries `'ok': True` in the success envelope; reproduce Scope's versions, NOT raw history). Note the deliberate divergences: `__init__` keeps `1865c5e`'s `self._now_fn` delegate ALONGSIDE the new public `self.now_fn`; `transition` (untouched) keeps `approvals=`; type annotations on the restored methods are optional — match the staged class's prevailing un-annotated style.

stdlib + ngv2 only.

# Deliverables

Edited ngv2/session_api.py in which `SessionApi` is the staged HEAD class byte-for-byte EXCEPT the three Scope deltas: `__init__` initializes the PUBLIC `self.now_fn = now_fn` (None by default) while keeping the private `_now_fn` delegate; `advance(session_id, approval_decision=None)` is the restored FSM driver that walks PHASE_ORDER, builds and parks the turn-in package at 'report', consults the readiness gate, halts parked at `awaiting_submission` pending approval, releases `awaiting_submission -> submitted -> done` on an approving decision, persists through the duck-typed `_save` (live over a bare SessionDB via session_db.py:240/252), 404s via `_not_found` on unknown sessions, and returns `{'ok': True, 'session_id', 'phase', 'parked', 'reason', 'transitions'}`; and `_truthy_approval` is the dict-aware @staticmethod over `_APPROVE_LABELS` so `{'approved': False}` rejects and `{'approved': True}` approves — with NO change to any other method, helper, or module-level symbol, so every `1865c5e` envelope survives intact. Verified GREEN by the anti-seesaw union verification command in Required plan shape: all 56 cases pass (the 7 REDs flip green, the 49 greens stay green; validated end-to-end in a scratch run on 2026-06-11 with zero new failures across the full tests/ngv2 sweep — 250 cases).
