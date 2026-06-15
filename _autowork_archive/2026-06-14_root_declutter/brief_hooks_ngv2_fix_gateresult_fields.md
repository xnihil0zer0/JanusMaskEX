---
interfaces: "edits ngv2/session_gate.py to add three missing fields to the GateResult dataclass — phase_from: str = \"\", phase_to: str = \"\", error: Optional[str] = None — so the kwargs every lifecycle gate handler AND the no_gate fallback already pass (phase_from=/phase_to=/error=) become valid, and gate_transition(phase_from, phase_to, evidence) returns a GateResult instead of raising TypeError on every one of the nine lifecycle edges and the unknown-edge fallback, making the evidence-gated bounty-FSM dispatch surface functional end-to-end"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/session_gate.py — add the missing `phase_from` / `phase_to` / `error` fields to the `GateResult` dataclass so `gate_transition(phase_from, phase_to, evidence)` returns a real `GateResult` instead of raising `TypeError: GateResult.__init__() got an unexpected keyword argument 'phase_from'` on every one of the nine lifecycle edges and the unknown-edge `no_gate` fallback

# Scope

EDIT the EXISTING module ngv2/session_gate.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). DEFECT (verified live 2026-06-11): the `GateResult` dataclass declares only `ok` and `payload`:

    @dataclass
    class GateResult:
        """Outcome of a single FSM gate evaluation."""

        ok: bool
        payload: Dict[str, Any] = field(default_factory=dict)

…but EVERY lifecycle gate handler in the module AND the `no_gate` fallback inside `gate_transition` construct it with `phase_from=` / `phase_to=` / `error=` keyword arguments, e.g.:

    return GateResult(ok=True, phase_from=pf, phase_to=pt, payload={'novelty': classification, 'route': route})
    return GateResult(ok=False, phase_from=pf, phase_to=pt, error='poc_build_failed', payload={'poc': poc})
    return GateResult(ok=False, error='No artifacts found')                       # _gate_hunt_to_triage
    return GateResult(ok=True, error=None)                                        # _gate_triage_to_poc
    return GateResult(ok=False, phase_from=phase_from, phase_to=phase_to, error='no_gate')   # gate_transition fallback

Because the dataclass has none of `phase_from` / `phase_to` / `error`, *every* call to `gate_transition` (and every one of the `_HANDLERS` gates plus the legacy `_gate_hunt_to_triage` / `_gate_triage_to_poc` / `_gate_detonate_to_report` helpers) raises `TypeError: GateResult.__init__() got an unexpected keyword argument 'phase_from'`. The entire evidence-gated FSM dispatch surface is non-functional for all nine lifecycle edges (`source->hunt`, `triage->verify`, `verify->poc`, `poc->detonate`, `detonate->novelty`, `novelty->report`, `report->awaiting_submission`, `awaiting_submission->submitted`, `submitted->done`) and the unknown-edge fallback. The defect slipped through because the impl's oracle only pinned the legacy `PHASES` table, never exercising `gate_transition`.

THE FIX (data_model — purely additive fields, NO handler-logic change): add exactly the three missing fields to `GateResult`, each with a default that makes EVERY existing construction site valid. `ok` stays first (the only required positional); `payload` keeps its `field(default_factory=dict)` default; the three new fields follow with defaults so the dataclass remains constructible as `GateResult(ok=...)` and as `GateResult(ok=..., phase_from=..., phase_to=..., error=..., payload=...)`. Read the read-only staged target at `{WORK_DIR}/inbox/targets/ngv2/session_gate.py` FIRST to confirm the exact current class body and the already-present module imports (`from dataclasses import dataclass` line ~30, `from typing import Dict` / `from typing import Any` / `from typing import Optional` lines ~31-34, `from dataclasses import field` line ~39). NO new imports are needed — `dataclass`, `field`, `Dict`, `Any`, and `Optional` are all already imported at module level. EXACT corrected target (reproduce VERBATIM):

    @dataclass
    class GateResult:
        """Outcome of a single FSM gate evaluation."""

        ok: bool
        payload: Dict[str, Any] = field(default_factory=dict)
        phase_from: str = ""
        phase_to: str = ""
        error: Optional[str] = None

Keep the class pure/inert (a plain dataclass — no methods, no `__post_init__`, no validation, no clock/randomness/network/subprocess). Verify GREEN with `python -m pytest tests/ngv2/test_gate_result_fields_wired.py -q`; working_dir is /home/xnihil0zer0/NobleGreedv2.

DISPATCH DIRECTIVE — PATCH FORMAT (single whole-symbol patch on an EXISTING 1-part top-level class — the canonical safe shape): emit a single top-level `__JANUSMASK_PATCHES__` list with EXACTLY ONE entry:

    __JANUSMASK_PATCHES__ = [
        {'file': 'ngv2/session_gate.py', 'kind': 'symbol', 'name': 'GateResult',
         'code': r'''@dataclass
class GateResult:
    """Outcome of a single FSM gate evaluation."""

    ok: bool
    payload: Dict[str, Any] = field(default_factory=dict)
    phase_from: str = ""
    phase_to: str = ""
    error: Optional[str] = None
'''},
    ]

The `name` MUST be the 1-part TOP-LEVEL name `'GateResult'` — never a dotted qualname (never `GateResult.something`), never a manifest, never a whole-file rewrite, never any extra top-level node (the fix needs NO new symbol, NO new import: `dataclass`, `field`, `Dict`, `Any`, `Optional` already exist at module level). The emitted `code` must reproduce the class BYTE-FOR-BYTE as it exists at HEAD plus ONLY the three appended field lines — keep the `@dataclass` decorator line, the exact docstring, and the existing `ok` / `payload` lines unchanged. POST-EMIT SELF-CHECK (mandatory): your emitted `code` must START with `@dataclass` at column 0 followed by `class GateResult:`, contain the unchanged `ok: bool` and `payload: Dict[str, Any] = field(default_factory=dict)` lines, then the three NEW lines `phase_from: str = ""`, `phase_to: str = ""`, `error: Optional[str] = None`; it must contain exactly ONE top-level `class` and no extra `def` / `class ` / `import ` statements and no methods.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the committed oracle is keyed to this brief): `task_id`: `ngv2-fix-gateresult-fields`. meta_task_type=`data_model` (external NGv2 target — the diff-fuzzer cannot resolve external imports, so use a fuzzer-bypassed, smoke-gated meta-type; this is a pure additive-fields dataclass change, the archetypal data_model edit). priority: high. dependencies: []. working_dir: `/home/xnihil0zer0/NobleGreedv2`. files_touched: `["ngv2/session_gate.py"]` ONLY. partial_edit semantics: a single `__JANUSMASK_PATCHES__` list with EXACTLY ONE `'symbol'` entry whose `name` is the 1-part top-level `'GateResult'` (whole-class replacement per the DISPATCH DIRECTIVE — never dotted, never a manifest, never a whole-file rewrite, no extra nodes). The DISPATCH DIRECTIVE — PATCH FORMAT paragraph above MUST be copied VERBATIM into the task's `implementation_notes` so the blind worker sees it. verification_command: `python -m pytest tests/ngv2/test_gate_result_fields_wired.py -q`. The committed RED oracle tests/ngv2/test_gate_result_fields_wired.py (NGv2 commit bacf337) is the authoritative acceptance contract — make it GREEN; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from the committed oracle `tests/ngv2/test_gate_result_fields_wired.py` (plan descriptors referencing committed/landed tests — this does NOT authorize authoring new tests), so every `spec.edge_cases` entry is reflected per the validator's edge-case rule (e.g. `test_passing_edge_real_seam_returns_ok_gateresult`, `test_unknown_edge_returns_no_gate_fallback_gateresult`).

# Non-Goals

This is an EDIT and integration is out of scope: the task's non_goals MUST declare integration testing out of scope — do NOT add integration/e2e tests; this fix is verified solely by the committed unit oracle tests/ngv2/test_gate_result_fields_wired.py. Do NOT author or modify any test — that oracle is committed and authoritative. Rewrite the `GateResult` dataclass ONLY. Do NOT change ANY gate handler (`_gate_hunt_to_triage`, `_gate_triage_to_poc`, `_gate_detonate_to_report`, `_gate_source_to_hunt`, `_gate_triage_to_verify`, `_gate_verify_to_poc`, `_gate_poc_to_detonate`, `_gate_detonate_to_novelty`, `_gate_novelty_to_report`, `_gate_report_to_awaiting`, `_gate_awaiting_to_submitted`, `_gate_submitted_to_done`), `gate_transition`, the `_HANDLERS` / `_TRANSITIONS` tables, the `_bind` seam table, `semantic_verdict`, or any helper. In particular do NOT "fix" the separate `_gate_source_to_hunt` qualify-arity issue (it calls `qualify` with one positional arg while `qualify` needs two) — that is a DIFFERENT defect, explicitly out of scope here; this brief ONLY adds the dataclass fields. Do NOT add a `__post_init__`, methods, validation, properties, or `from_dict`/`to_dict` to `GateResult`. Do NOT reorder existing fields (`ok` MUST stay the first/only required positional; `payload` keeps its `field(default_factory=dict)` default) and do NOT change their types or defaults. Do NOT add new imports (all needed names are already imported), no network, no wall-clock, no randomness, no third-party dependencies. Do NOT touch ngv2/state_machine.py, ngv2/human_checkpoint_gate.py, ngv2/submission_readiness_gate.py, ngv2/session_api.py, ngv2/session_db.py, ngv2/contracts.py, or any other module.

# Inputs

The committed authoritative oracle at tests/ngv2/test_gate_result_fields_wired.py (NGv2 commit bacf337; currently RED with `TypeError: GateResult.__init__() got an unexpected keyword argument 'phase_from'` on all four cases). It exercises `gate_transition` end-to-end on: (a) a PASSING edge over a REAL seam — `gate_transition('detonate', 'novelty', {'finding': {...}, 'corpus': []})` runs the real `ngv2.novelty_gate.classify_novelty` seam (empty corpus -> NOVEL -> GO) and asserts `result.ok is True`, `result.phase_from == 'detonate'`, `result.phase_to == 'novelty'`, `result.payload['novelty'] == 'NOVEL'`, `result.error is None`; (b) a FAILING-gate edge — `gate_transition('verify', 'poc', {'poc': {'built': False, 'exit_code': 1}})` returns `ok=False`, `error='poc_build_failed'`, with the phases populated, instead of raising TypeError; a fail-PATH construction check on `source -> hunt` asserting the phases populate and `error == 'unqualified'`; and (c) the UNKNOWN-edge `no_gate` fallback — `gate_transition('nowhere', 'elsewhere', {})` returns `ok=False`, `error='no_gate'`, `phase_from='nowhere'`, `phase_to='elsewhere'`. Each case raises TypeError TODAY at the `GateResult(...)` construction inside the handler / fallback and flips GREEN once the three fields land.

The EXACT current defective source being replaced (from ngv2/session_gate.py at HEAD):

    @dataclass
    class GateResult:
        """Outcome of a single FSM gate evaluation."""

        ok: bool
        payload: Dict[str, Any] = field(default_factory=dict)

The construction sites that REQUIRE the new fields (read-only context — do NOT edit any of them; they already pass these kwargs and only the dataclass must change):

    # _gate_source_to_hunt / _gate_triage_to_verify / _gate_verify_to_poc / _gate_poc_to_detonate /
    # _gate_detonate_to_novelty / _gate_novelty_to_report / _gate_report_to_awaiting /
    # _gate_awaiting_to_submitted / _gate_submitted_to_done all do, e.g.:
    return GateResult(ok=True, phase_from=pf, phase_to=pt, payload={...})
    return GateResult(ok=False, phase_from=pf, phase_to=pt, error='<reason>', payload={...})
    # the legacy rows-gates do, e.g.:
    return GateResult(ok=False, error='No artifacts found')
    return GateResult(ok=True, error=None)
    # gate_transition's unknown-edge fallback:
    return GateResult(ok=False, phase_from=phase_from, phase_to=phase_to, error='no_gate')

Already-present module imports the fix relies on (read-only — do NOT add or change): `from dataclasses import dataclass`, `from dataclasses import field`, `from typing import Any`, `from typing import Dict`, `from typing import Optional`. stdlib + ngv2 only.

# Deliverables

Edited ngv2/session_gate.py in which the `GateResult` dataclass carries five fields — the unchanged `ok: bool` and `payload: Dict[str, Any] = field(default_factory=dict)`, plus the three NEW additive fields `phase_from: str = ""`, `phase_to: str = ""`, `error: Optional[str] = None` — exactly as pinned in Scope, with NO change to any handler, helper, table, seam binding, import, or the module docstring, so `gate_transition(phase_from, phase_to, evidence)` and every gate handler return a real `GateResult` (carrying the from/to phases and an optional error string) instead of raising `TypeError`, making the evidence-gated bounty-FSM dispatch surface functional end-to-end across all nine lifecycle edges and the unknown-edge fallback. Verified GREEN by `python -m pytest tests/ngv2/test_gate_result_fields_wired.py -q`.
