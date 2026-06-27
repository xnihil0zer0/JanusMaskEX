---
interfaces: "EDITS existing ngv2/session_gate.py to insert the Stage-3 LLM scope/auth triage into the (triage->verify) lifecycle gate: adds helper _reachability_triage_band(ev) and makes _gate_triage_to_verify consult it before the confidence gate — DROP->out_of_scope, MANUAL->manual_review_scope, ADMIT/absent->existing confidence path; legacy seam-free callers are unaffected"
dependencies: ["ngv2_reachability_triage"]
meta_task_type: state_machine
spec_author: "Phase-III BUILD-PREP agent (JanusMask)"
spec_reviewed_by: "owner (CodeQL CLI use APPROVED 2026-06-12)"
---

# Title

ngv2/session_gate.py — EDIT to wire the Stage-3 reachability triage band into the live (triage->verify) FSM gate, the integration that makes the LLM scope/auth judgment actually filter candidates on the hunt path.

# Scope

EDIT the EXISTING module `ngv2/session_gate.py` (NGv2 external-target task — `working_dir` = /home/xnihil0zer0/NobleGreedv2). Two changes, nothing else: (1) ADD a new top-level helper `_reachability_triage_band(ev)` that, ONLY when the evidence carries an LLM seam (`ev['llm_complete']` or `ev['llm_client']`), consults `ngv2.reachability_triage.judge` over the proven taint path and returns its `ADMIT`/`MANUAL`/`DROP` band (None to skip when no seam — so legacy callers are untouched; any error fail-safes to `MANUAL`). (2) MODIFY the existing `_gate_triage_to_verify` handler to call the helper first: a `DROP` band short-circuits to `GateResult(ok=False, error='out_of_scope')`, a `MANUAL` band to `error='manual_review_scope'`, and `ADMIT`/None falls through UNCHANGED to the existing confidence-signal path. The ('triage','verify') edge is already registered in `_HANDLERS`; this makes that edge consult scope/auth before confidence. No other handler, the `_HANDLERS` table, or any helper changes.

DISPATCH DIRECTIVE — PATCH FORMAT (MANDATORY — R-ANCHORED PARTIAL EDIT): `_reachability_triage_band` is a NEW top-level symbol — it must ride as a node anchored on the existing `_gate_triage_to_verify` patch (do NOT whole-file re-emit this 438-line module; do NOT patch any class method or the `_HANDLERS` dict). Emit a partial-edit patch that re-emits the modified existing function `_gate_triage_to_verify` VERBATIM and includes the NEW `_reachability_triage_band` immediately before it, BYTE-FOR-BYTE as follows (both functions, in this order):

```python
def _reachability_triage_band(ev: Any) -> Optional[str]:
    """Consult the Stage-3 LLM scope/auth triage when an LLM seam is supplied.

    Returns 'ADMIT'/'MANUAL'/'DROP', or None to skip triage (no seam present, so
    legacy callers are unaffected). Any error fail-safes to 'MANUAL'.
    """
    if not isinstance(ev, dict):
        return None
    complete = ev.get('llm_complete')
    client = ev.get('llm_client')
    if complete is None and client is None:
        return None
    finding = _first(ev, ('finding', 'findings'), {})
    path = ev.get('taint_path') or ev.get('path')
    snippets = ev.get('snippets')
    try:
        from ngv2.reachability_triage import judge
        return judge(finding, path, snippets, client=client, complete=complete).get('band')
    except Exception:
        return 'MANUAL'

def _gate_triage_to_verify(pf: str, pt: str, ev: Any) -> GateResult:
    finding = _first(ev, ('finding', 'findings'), ev)
    triage_band = _reachability_triage_band(ev)
    if triage_band == 'DROP':
        return GateResult(ok=False, phase_from=pf, phase_to=pt, error='out_of_scope', payload={'triage': 'DROP'})
    if triage_band == 'MANUAL':
        return GateResult(ok=False, phase_from=pf, phase_to=pt, error='manual_review_scope', payload={'triage': 'MANUAL'})
    try:
        from ngv2.confidence_signals import resolve_signals
        signals = resolve_signals(ev, finding)
    except Exception:
        signals = None
    confidence = _call(compute_confidence, finding, signals)
    route = _call(route_confidence, confidence)
    if route is None:
        route = confidence
    band = _confidence_band(route)
    if band == 'ADMIT':
        return GateResult(ok=True, phase_from=pf, phase_to=pt, payload={'confidence': confidence, 'route': route})
    if band == 'MANUAL':
        return GateResult(ok=False, phase_from=pf, phase_to=pt, error='manual_review', payload={'confidence': confidence, 'route': route})
    if band == 'DROP':
        return GateResult(ok=False, phase_from=pf, phase_to=pt, error='dropped', payload={'confidence': confidence, 'route': route})
    return GateResult(ok=False, phase_from=pf, phase_to=pt, error='unrouted', payload={'confidence': confidence, 'route': route})
```

POST-EMIT SELF-CHECK (mandatory): with NO `llm_complete`/`llm_client` in `ev`, `_gate_triage_to_verify` behaves byte-identically to before (triage skipped, confidence path); `('triage','verify')` is still in `_HANDLERS`; only these two functions changed; the import of `reachability_triage` is lazy inside the helper; any judge error → MANUAL (never a silent ADMIT/DROP).

# Non-Goals

Do NOT change any other gate handler, the `_HANDLERS` table, `semantic_verdict`, or the `_confidence_band` logic. Do NOT make the triage run when no LLM seam is supplied (legacy callers MUST be unaffected). Do NOT touch reachability_triage or confidence_signals. Do NOT add network/clock/subprocess. The driver that supplies `ev['llm_complete']` + `ev['taint_path']` on the live hunt path is a separate INTEGRATION leaf (`_e2e_run/drive_reachability.py`); this leaf wires only the gate consult. ANTI-SEESAW: this edit shares `session_gate` with a large UNION of existing oracles — at minimum tests/ngv2/test_session_gate_wired.py, test_state_machine_gate_wired.py, test_lifecycle_fsm_wiring_wired.py, test_session_gate_done_wired.py, test_session_gate_import_and_bind_wired.py, test_session_gate_bind_reconciliation_wired.py, test_source_hunt_qualify_arity_wired.py, test_gate_result_fields_wired.py, test_submission_readiness_ready_path_wired.py, test_session_api_wired.py, test_session_api_persistence_wired.py, test_session_api_audit_now_fn_wired.py, test_persist_submission_sessiondb_wired.py, and tests/test_triage_verify_signals_wired.py — your `regression_tests` MUST keep that whole UNION green (verified: all stay green against the edited module).

# Inputs

The committed RED oracle tests/ngv2/test_session_gate_reachability_triage_wired.py (5 tests; RED — helper/consult absent). It pins: the ('triage','verify') edge registered; an `internal_only` verdict → ok=False error='out_of_scope'; `auth_gated` → error='manual_review_scope'; `reachable_unauth` falls through to the confidence path (not out_of_scope/manual_review_scope); and a seam-free legacy call behaves as before. The session_gate + triage_verify oracles are the anti-seesaw UNION partners (verified green against the edited module).

# Deliverables

The edited `ngv2/session_gate.py` (helper added + `_gate_triage_to_verify` consult), verified GREEN by `python3 -m pytest -q tests/ngv2/test_session_gate_reachability_triage_wired.py tests/ngv2/test_session_gate_wired.py tests/ngv2/test_state_machine_gate_wired.py tests/test_triage_verify_signals_wired.py`.

# Required plan shape

EXACTLY ONE impl task. task_id VERBATIM: `ngv2_session_gate_reachability_triage`. meta_task_type=`state_machine` (FSM transition-gate edit — R-anchored partial edit of an existing top-level function + a new top-level helper; NOT whole-file, NOT a class method). priority: high. dependencies: `["ngv2_reachability_triage"]`. working_dir: "/home/xnihil0zer0/NobleGreedv2". files_touched: `["ngv2/session_gate.py"]` ONLY. partial_edit semantics: R-ANCHORED — re-emit `_gate_triage_to_verify` verbatim with `_reachability_triage_band` riding immediately before it per the DISPATCH DIRECTIVE (copy that block VERBATIM into `implementation_notes`). verification_command: `python3 -m pytest -q tests/ngv2/test_session_gate_reachability_triage_wired.py tests/ngv2/test_session_gate_wired.py tests/ngv2/test_state_machine_gate_wired.py tests/test_triage_verify_signals_wired.py` (CWD-relative — NO `cd`). `test_spec.regression_tests` (≥2 named, across the UNION): `test_out_of_scope_drops_at_gate`, `test_admit_falls_through_to_confidence_path`, plus the existing session_gate/state_machine oracles. `test_spec.edge_cases` (≥2): `test_auth_gated_routes_manual_at_gate`, `test_legacy_no_seam_unaffected`. `test_spec.integration_test`: `test_triage_verify_edge_registered` (live `_HANDLERS` reachability via gate_transition).
