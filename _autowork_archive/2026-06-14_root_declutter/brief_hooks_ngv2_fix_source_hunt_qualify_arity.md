---
interfaces: "edits ngv2/session_gate.py to repair _gate_source_to_hunt so it invokes the qualify seam with BOTH required positional arguments (target AND oracle_result, the latter extracted from the evidence payload) — currently it calls qualify(target) with one arg, _call swallows the resulting TypeError, qualify never runs, and the FSM's first edge (source->hunt) can never return GO; after the fix a GO-worthy target+oracle_result yields an ok GateResult so the bounty lifecycle can actually leave the source phase"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/session_gate.py — repair `_gate_source_to_hunt` so it calls the `qualify` seam with its FULL two-positional signature (`qualify(target, oracle_result, *, ...)`), extracting `oracle_result` from the evidence payload, so the FSM's first edge (`source -> hunt`) can return GO instead of being permanently wedged at `unqualified`

# Scope

EDIT the EXISTING module ngv2/session_gate.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). DEFECT (verified live 2026-06-11): the top-level handler `_gate_source_to_hunt` invokes the `qualify` seam with ONE positional argument:

    def _gate_source_to_hunt(pf: str, pt: str, ev: Any) -> GateResult:
        target = _first(ev, ('target', 'targets', 'candidate'), ev)
        result = _call(qualify, target)
        if result is None:
            result = _call(qualify, ev)
        if _is_go(result):
            return GateResult(ok=True, phase_from=pf, phase_to=pt, payload={'qualification': result})
        return GateResult(ok=False, phase_from=pf, phase_to=pt, error='unqualified', payload={'qualification': result})

…but the real seam `ngv2.source_qualify_gate.qualify(target, oracle_result, *, saturation_cap=50, freshness_min=7)` requires TWO positional arguments — `target` (a dict with `repo`/`package`) AND `oracle_result` (a dict carrying the REQUIRED_FIELDS `expected_payout`, `open_submissions`, `days_since_audit`, `fp_risk`). The `_call` helper invokes `fn` tolerantly, trying `args`, then `args[:1]`, then `()`, and on a persistent `TypeError` returns `None`. Because `qualify(target)` is missing the required `oracle_result`, EVERY attempt raises `TypeError`, `_call` returns `None`, `qualify` NEVER actually runs, `_is_go(None)` is `False`, and the gate ALWAYS returns a *fail* `GateResult(ok=False, error='unqualified', payload={'qualification': None})`. The bounty FSM's very first edge (`source -> hunt`) can therefore NEVER return GO, no matter how qualifying the target is — the entire lifecycle is wedged at the entrance. The defect slipped through because no committed test exercised `_gate_source_to_hunt` end-to-end with a real `oracle_result` payload.

THE FIX (data_model — a single whole-symbol replacement of `_gate_source_to_hunt`, NO change to any other handler, helper, seam binding, or table): extract the `oracle_result` from the evidence payload (the key the FSM driver already supplies — confirmed by `tests/ngv2/test_lifecycle_fsm_wiring_wired.py`, which calls `gate_transition('source', 'hunt', {'target': target, 'oracle_result': oracle_result})`) using the module's existing `_first` extraction idiom, and pass it as the second positional argument to `qualify`. Fail closed when it is absent (`None` -> `qualify` raises -> `_call` returns `None` -> `unqualified`), consistent with the module's tolerant style. Read the read-only staged target at `{WORK_DIR}/inbox/targets/ngv2/session_gate.py` FIRST to confirm the exact current function body and the already-present module-level names the fix relies on (`_first`, `_call`, `_is_go`, `qualify`, `GateResult` — all defined/bound at module level; NO new import is needed). EXACT corrected target (reproduce VERBATIM):

    def _gate_source_to_hunt(pf: str, pt: str, ev: Any) -> GateResult:
        target = _first(ev, ('target', 'targets', 'candidate'), ev)
        oracle_result = _first(ev, ('oracle_result', 'oracle', 'qualification_inputs'), None)
        result = _call(qualify, target, oracle_result)
        if result is None:
            result = _call(qualify, ev, oracle_result)
        if _is_go(result):
            return GateResult(ok=True, phase_from=pf, phase_to=pt, payload={'qualification': result})
        return GateResult(ok=False, phase_from=pf, phase_to=pt, error='unqualified', payload={'qualification': result})

Keep the function pure/total/deterministic (no clock, randomness, network, subprocess, or filesystem). The ONLY changes vs. HEAD are: (1) the new `oracle_result = _first(...)` extraction line, and (2) threading `oracle_result` as the second positional into both `_call(qualify, ...)` calls. The two `return GateResult(...)` lines, the `_is_go` branch, and the `target` extraction line are BYTE-FOR-BYTE unchanged.

NOTE — CONCURRENT IN-FLIGHT FIX (do NOT touch): a separate brief `ngv2_fix_gateresult_fields` (committed oracle `tests/ngv2/test_gate_result_fields_wired.py`, NGv2 `bacf337`) adds the missing `phase_from` / `phase_to` / `error` fields to the `GateResult` dataclass. That patch lands on the `GateResult` dataclass ONLY and does NOT touch `_gate_source_to_hunt`. Your patch lands on `_gate_source_to_hunt` ONLY and does NOT touch `GateResult`. The two are disjoint and order-independent. Do NOT modify the `GateResult` dataclass here.

DISPATCH DIRECTIVE — PATCH FORMAT (single whole-symbol patch on an EXISTING 1-part TOP-LEVEL function — the canonical safe shape): emit a single top-level `__JANUSMASK_PATCHES__` list with EXACTLY ONE entry:

    __JANUSMASK_PATCHES__ = [
        {'file': 'ngv2/session_gate.py', 'kind': 'symbol', 'name': '_gate_source_to_hunt',
         'code': r'''def _gate_source_to_hunt(pf: str, pt: str, ev: Any) -> GateResult:
    target = _first(ev, ('target', 'targets', 'candidate'), ev)
    oracle_result = _first(ev, ('oracle_result', 'oracle', 'qualification_inputs'), None)
    result = _call(qualify, target, oracle_result)
    if result is None:
        result = _call(qualify, ev, oracle_result)
    if _is_go(result):
        return GateResult(ok=True, phase_from=pf, phase_to=pt, payload={'qualification': result})
    return GateResult(ok=False, phase_from=pf, phase_to=pt, error='unqualified', payload={'qualification': result})
'''},
    ]

The `name` MUST be the 1-part TOP-LEVEL name `'_gate_source_to_hunt'` (verified top-level — it is defined at column 0, NOT nested inside any class or function) — never a dotted qualname, never a manifest, never a whole-file rewrite, never any extra top-level node (the fix needs NO new symbol and NO new import: `_first`, `_call`, `_is_go`, `qualify`, `GateResult` already exist at module level). The emitted `code` must reproduce the function BYTE-FOR-BYTE as it exists at HEAD plus ONLY the one new `oracle_result = _first(...)` line and the two-arg threading into the `_call(qualify, ...)` calls. POST-EMIT SELF-CHECK (mandatory): your emitted `code` must START with `def _gate_source_to_hunt(pf: str, pt: str, ev: Any) -> GateResult:` at column 0; contain the unchanged `target = _first(ev, ('target', 'targets', 'candidate'), ev)` line; contain the new `oracle_result = _first(ev, ('oracle_result', 'oracle', 'qualification_inputs'), None)` line; call `_call(qualify, target, oracle_result)` and `_call(qualify, ev, oracle_result)` (each with TWO positional args after `qualify`); contain exactly ONE top-level `def` and NO extra `def` / `class ` / `import ` statements; keep the two `return GateResult(...)` lines verbatim.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the committed oracle is keyed to this brief): `task_id`: `ngv2-fix-source-hunt-qualify-arity`. meta_task_type=`data_model` (external NGv2 target — the differential diff-fuzzer cannot resolve external imports, so use a fuzzer-bypassed, smoke-gated meta-type; this is a localized whole-symbol edit to a single pure function with no new import, which the data_model archetype covers). priority: high. dependencies: []. working_dir: `/home/xnihil0zer0/NobleGreedv2`. files_touched: `["ngv2/session_gate.py"]` ONLY. partial_edit semantics: a single `__JANUSMASK_PATCHES__` list with EXACTLY ONE `'symbol'` entry whose `name` is the 1-part top-level `'_gate_source_to_hunt'` (whole-function replacement per the DISPATCH DIRECTIVE — never dotted, never a manifest, never a whole-file rewrite, no extra nodes). The DISPATCH DIRECTIVE — PATCH FORMAT paragraph above MUST be copied VERBATIM into the task's `implementation_notes` so the blind worker sees it. verification_command: `python -m pytest tests/ngv2/test_source_hunt_qualify_arity_wired.py -q`. The committed RED oracle tests/ngv2/test_source_hunt_qualify_arity_wired.py is the authoritative acceptance contract — make it GREEN; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). VALIDATOR FLOOR: `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from the committed oracle tests/ngv2/test_source_hunt_qualify_arity_wired.py — namely `test_source_to_hunt_returns_go_for_qualifying_target` and `test_oracle_result_is_threaded_into_qualify_skip_decision` — so every `spec.edge_cases` entry (the GO edge and the SKIP-threading edge) is reflected per the validator's edge-case rule (plan descriptors referencing the committed/landed oracle — this does NOT authorize authoring new tests).

# Non-Goals

This is an EDIT and integration is out of scope: the task's non_goals MUST declare integration/e2e testing out of scope — do NOT add integration/e2e tests; this fix is verified solely by the committed unit oracle tests/ngv2/test_source_hunt_qualify_arity_wired.py. Do NOT author or modify any test — that oracle is committed and authoritative. Rewrite the `_gate_source_to_hunt` function ONLY. Do NOT change the `GateResult` dataclass (that is the SEPARATE, concurrent `ngv2_fix_gateresult_fields` fix — explicitly out of scope here). Do NOT change ANY other gate handler (`_gate_hunt_to_triage`, `_gate_triage_to_poc`, `_gate_detonate_to_report`, `_gate_triage_to_verify`, `_gate_verify_to_poc`, `_gate_poc_to_detonate`, `_gate_detonate_to_novelty`, `_gate_novelty_to_report`, `_gate_report_to_awaiting`, `_gate_awaiting_to_submitted`, `_gate_submitted_to_done`), `gate_transition`, the `_HANDLERS` / `_TRANSITIONS` tables, the `_bind` seam table or any seam binding, the `_call` / `_first` / `_get` / `_is_go` / `_decision` / `_confidence_band` helpers, `semantic_verdict`, or the module docstring. Do NOT change `ngv2/source_qualify_gate.py` — the seam's two-positional signature is correct; the caller is what must be fixed. Do NOT add new imports (all needed names are already at module level), no network, no wall-clock, no randomness, no subprocess, no third-party dependencies. Do NOT touch ngv2/state_machine.py, ngv2/session_api.py, ngv2/session_db.py, ngv2/contracts.py, or any other module.

# Inputs

The committed authoritative oracle at tests/ngv2/test_source_hunt_qualify_arity_wired.py (currently RED — three cases, all failing on the arity defect: `_gate_source_to_hunt returned NO-GO for a qualifying target` / `qualify produced no verdict`). It pins:
- (a) `test_source_to_hunt_returns_go_for_qualifying_target` — `gate_transition('source', 'hunt', {'target': {'repo': 'owner/repo', 'package': 'pkg-x'}, 'oracle_result': {'expected_payout': 1000, 'open_submissions': 0, 'days_since_audit': 30, 'fp_risk': False}})` MUST return `ok=True`, `phase_from='source'`, `phase_to='hunt'`, `error is None`, `payload['qualification']['decision'] == 'GO'`.
- (a2) `test_handler_directly_returns_go_for_qualifying_target` — the same GO assertion calling the top-level `_gate_source_to_hunt` directly.
- (b) `test_oracle_result_is_threaded_into_qualify_skip_decision` — a SKIP-worthy `oracle_result` (`expected_payout=0`) must thread through so `payload['qualification']['decision'] == 'SKIP'` (today it is `None` because qualify never runs).

The oracle is deliberately DECOUPLED from the in-flight GateResult-fields fix: each test swaps in a locally-defined corrected `GateResult` (carrying the `phase_from`/`phase_to`/`error` fields) so a missing-field `TypeError` cannot mask the arity defect. It is therefore meaningfully RED on the ARITY defect ALONE both before and after `ngv2_fix_gateresult_fields` lands, and flips GREEN only once `_gate_source_to_hunt` threads `oracle_result`.

The EXACT current defective source being replaced (from ngv2/session_gate.py at HEAD):

    def _gate_source_to_hunt(pf: str, pt: str, ev: Any) -> GateResult:
        target = _first(ev, ('target', 'targets', 'candidate'), ev)
        result = _call(qualify, target)
        if result is None:
            result = _call(qualify, ev)
        if _is_go(result):
            return GateResult(ok=True, phase_from=pf, phase_to=pt, payload={'qualification': result})
        return GateResult(ok=False, phase_from=pf, phase_to=pt, error='unqualified', payload={'qualification': result})

The seam contract being satisfied (read-only — do NOT edit; from ngv2/source_qualify_gate.py):

    REQUIRED_FIELDS = ('expected_payout', 'open_submissions', 'days_since_audit', 'fp_risk')

    def qualify(target: Dict[str, Any], oracle_result: Dict[str, Any], *, saturation_cap: int=50, freshness_min: int=7) -> Dict[str, Any]:
        # returns {'decision': 'GO'|'SKIP'|'UNKNOWN', 'reason': str, 'target_spec': dict|None}
        # 'GO' iff every REQUIRED_FIELD present in oracle_result AND payout>0 AND
        # open_submissions<cap AND days_since_audit>=min AND fp_risk is False.

Already-present module-level names the fix relies on (read-only — do NOT add or change): `_first`, `_call`, `_is_go`, `GateResult`, and the `qualify = _bind('qualify', ...)` seam binding. stdlib + ngv2 only.

# Deliverables

Edited ngv2/session_gate.py in which `_gate_source_to_hunt` extracts `oracle_result` from the evidence payload via `_first(ev, ('oracle_result', 'oracle', 'qualification_inputs'), None)` and passes it as the second positional argument to BOTH `_call(qualify, target, oracle_result)` and the fallback `_call(qualify, ev, oracle_result)`, with NO change to any other handler, helper, table, seam binding, the `GateResult` dataclass, import, or the module docstring — so the `source -> hunt` edge actually runs `qualify` and returns an `ok` `GateResult` (`payload['qualification']['decision'] == 'GO'`) for a qualifying target+oracle_result, fails closed (`unqualified`) when `oracle_result` is absent, and the bounty FSM can leave the source phase. Verified GREEN by `python -m pytest tests/ngv2/test_source_hunt_qualify_arity_wired.py -q`.
