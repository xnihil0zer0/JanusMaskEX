---
interfaces: "re-patches ngv2/session_api.py SessionApi._classify so a POSITIVE structural shape (poc/report) wins, but a shapeless dict (structural's 'finding' default) falls through to the phase mapping — reconciling the new structural-precedence contract with the EXISTING phase->kind oracle that C-2's naive reorder regressed"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/session_api.py — reconcile SessionApi._classify: positive structural shape wins, shapeless dicts fall through to the phase mapping (fixes the anti-seesaw regression C-2 introduced in test_session_api_classify_phase_wired.py)

# Scope

EDIT the EXISTING method `SessionApi._classify` in ngv2/session_api.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). DEFECT (verified live 2026-06-12): the prior leaf reordered `_classify` to `explicit -> structural -> phase`, but `_structural_kind` returns `'finding'` as a DEFAULT (not None) for any dict with no poc/report shape. So structural-first means the phase mapping NEVER fires for a dict, which regressed the committed oracle `tests/ngv2/test_session_api_classify_phase_wired.py::test_classify_poc_phase_still_maps_to_poc` — it asserts `_classify({"some":"data"}, "poc") == "poc"` (phase-based), but the naive reorder now returns `'finding'`.

THE FIX (data_model — a pure single-method reordering with a positive-structural guard, NO new symbol, NO signature change): structural wins ONLY when it positively identifies a poc/report shape; a shapeless dict (structural's `'finding'` default) falls through to the phase mapping; phase's `'finding'`/`None` fallback ends at the structural default. Resolution order: explicit -> (positive structural) -> phase -> structural-default. This satisfies the UNION of both committed oracles:
- `tests/ngv2/test_classify_structural_precedence_wired.py` (new): PoC-shaped `{language,entrypoint,code}` and report-shaped `{poc_finding_id,verdict}` self-classify by shape at any phase; explicit wins; shapeless@hunt -> finding.
- `tests/ngv2/test_session_api_classify_phase_wired.py` (existing): bare report@detonate/report -> report (structural is positive here, so still works); explicit wins; shapeless@poc -> poc (PHASE fallback — the case the naive reorder broke); finding@hunt -> finding.

Read the read-only staged target at `{WORK_DIR}/inbox/targets/ngv2/session_api.py` FIRST to confirm the current `_classify` body. Do NOT touch `_structural_kind`, `_phase_to_kind`, or `_explicit_kind`. Verify GREEN with `python -m pytest tests/ngv2/test_classify_structural_precedence_wired.py tests/ngv2/test_session_api_classify_phase_wired.py -q`; working_dir is /home/xnihil0zer0/NobleGreedv2.

DISPATCH DIRECTIVE — PARTIAL-EDIT (__JANUSMASK_PATCHES__) symbol patch: ngv2/session_api.py is a LARGE file (700+ lines). DO NOT reproduce the whole file. Read its CURRENT on-disk content (read-only) from `{WORK_DIR}/inbox/targets/ngv2/session_api.py`. Emit a single top-level Python list assigned to `__JANUSMASK_PATCHES__` with EXACTLY ONE 'symbol' entry that replaces the method `SessionApi._classify` (dotted Outer.method name). The submission file MUST contain ONLY this `__JANUSMASK_PATCHES__` assignment at top level (no other statements, imports, or decorators). Exact shape:

    __JANUSMASK_PATCHES__ = [
        {'file': 'ngv2/session_api.py', 'kind': 'symbol', 'name': 'SessionApi._classify',
         'code': r'''    def _classify(self, data, phase):
        explicit = self._explicit_kind(data)
        if explicit is not None:
            return explicit
        structural = self._structural_kind(data)
        if structural is not None and structural != 'finding':
            return structural
        phase_kind = self._phase_to_kind(phase)
        if phase_kind is not None:
            return phase_kind
        return structural
'''},
    ]

Rules: `code` MUST be exactly ONE method `def` whose name matches the leaf (`_classify`), reproduced with its real 4-space method indentation as shown. Use a raw triple-quoted string. Replace ONLY this one method — every other byte of session_api.py is preserved by the harness. Do NOT rename, add, or remove parameters; the signature `_classify(self, data, phase)` is unchanged. Do NOT emit a whole-file manifest. POST-EMIT SELF-CHECK: explicit first; then structural ONLY IF `structural is not None and structural != 'finding'`; then `_phase_to_kind(phase)` if not None; else fall back to `structural`. Exactly that order — the `!= 'finding'` guard is load-bearing.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM: `task_id`: `ngv2-classify-reconcile`. meta_task_type=`data_model` (a pure in-place single-method reordering on an external NGv2 target — fuzzer-bypassed per META_TASK_POLICY). priority: high. dependencies: []. working_dir: `/home/xnihil0zer0/NobleGreedv2`. files_touched: `["ngv2/session_api.py"]` ONLY. Emission semantics: a single `__JANUSMASK_PATCHES__` list with EXACTLY ONE 'symbol' entry on `SessionApi._classify` (per the DISPATCH DIRECTIVE — never a manifest, never whole-file). The DISPATCH DIRECTIVE — PARTIAL-EDIT paragraph above MUST be copied VERBATIM into the task's `implementation_notes`. verification_command: `python -m pytest tests/ngv2/test_classify_structural_precedence_wired.py tests/ngv2/test_session_api_classify_phase_wired.py -q` (BOTH committed oracle files — the union; this pins the anti-seesaw contract so the fix cannot satisfy one while regressing the other). These two committed oracles are the authoritative acceptance contract — make BOTH fully GREEN; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries naming existing test cases from the committed oracles (plan descriptors referencing committed/landed tests — this does NOT authorize authoring new tests), so every `spec.edge_cases` entry is reflected per the validator's edge-case rule (e.g. `test_classify_poc_phase_still_maps_to_poc`, `test_classify_detonate_phase_maps_bare_report_to_report`, `test_poc_shaped_dict_at_detonate_classifies_poc`, `test_shapeless_dict_at_hunt_falls_through_to_finding`).

# Non-Goals

This is an in-place EDIT of one method and integration is out of scope: the task's non_goals MUST declare integration testing out of scope — do NOT add integration/e2e tests; this change is verified solely by the two committed unit oracles named above. Do NOT author or modify any test — those oracles are committed and authoritative. Do NOT touch any other method, function, or symbol in session_api.py — ONLY `_classify`. Do NOT touch `_structural_kind`, `_phase_to_kind`, or `_explicit_kind`. Do NOT touch any gate handler (session_gate.py), the FSM (state_machine.py), or the e2e drivers. Do NOT change `_classify`'s signature. PATCH-SHAPE non-goals: do NOT emit a `__JANUSMASK_MANIFEST__` dict and do NOT emit a whole-file — the edit rides ONLY as the single 'symbol' `__JANUSMASK_PATCHES__` entry on `SessionApi._classify`. No network, no wall-clock, no randomness, no new dependencies.

# Inputs

The TWO committed authoritative oracles (the union that must BOTH be green):
- tests/ngv2/test_classify_structural_precedence_wired.py (committed, currently GREEN — must STAY green): pins explicit->structural->phase precedence for positively-shaped artifacts.
- tests/ngv2/test_session_api_classify_phase_wired.py (committed, currently has 1 RED case after the prior leaf): `test_classify_poc_phase_still_maps_to_poc` asserts `_classify({"some":"data"}, "poc") == "poc"` and is the regressed case the guard restores; its other cases (`test_classify_detonate_phase_maps_bare_report_to_report`, `test_classify_report_phase_maps_bare_report_to_report`, `test_explicit_artifact_type_key_overrides_phase_mapping`, `test_classify_hunt_phase_defaults_to_finding`, plus the two submit_artifacts acceptance tests) must all stay green.

The EXACT current `_classify` (the naive reorder being replaced — explicit -> structural -> phase, no guard):

    def _classify(self, data, phase):
        explicit = self._explicit_kind(data)
        if explicit is not None:
            return explicit
        structural = self._structural_kind(data)
        if structural is not None:
            return structural
        return self._phase_to_kind(phase)

The EXACT corrected `_classify` (reproduce VERBATIM as the patch `code` — explicit -> positive-structural -> phase -> structural-default):

    def _classify(self, data, phase):
        explicit = self._explicit_kind(data)
        if explicit is not None:
            return explicit
        structural = self._structural_kind(data)
        if structural is not None and structural != 'finding':
            return structural
        phase_kind = self._phase_to_kind(phase)
        if phase_kind is not None:
            return phase_kind
        return structural

Helper behavior (do NOT modify these): `_structural_kind` returns `'report'` if keys intersect `{poc_finding_id,verdict}`, `'poc'` if keys intersect `{language,entrypoint,code}`, else `'finding'` (the default for any dict; `'finding'` for non-dicts too). `_phase_to_kind` maps `hunt/triage->finding, poc->poc, detonate/report->report` and returns None for an unknown/None phase. `_explicit_kind` returns a normalized kind from a discriminator key or None.

# Deliverables

Edited ngv2/session_api.py whose `SessionApi._classify` resolves `explicit -> positive-structural -> phase -> structural-default` (the `!= 'finding'` guard lets phase act as the fallback for shapeless dicts) — with NO change to any other symbol or file — so BOTH committed oracles pass: a positively poc/report-shaped artifact self-classifies by shape at any phase, AND a shapeless dict still maps by phase (poc->poc, detonate->report). Verified GREEN by `python -m pytest tests/ngv2/test_classify_structural_precedence_wired.py tests/ngv2/test_session_api_classify_phase_wired.py -q` (all cases across BOTH files).
