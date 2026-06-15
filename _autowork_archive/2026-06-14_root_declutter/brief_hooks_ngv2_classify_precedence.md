---
interfaces: "edits ngv2/session_api.py in the external NobleGreedv2 repo to reorder SessionApi._classify resolution from explicit->phase->structural to explicit->structural->phase, so an artifact's KIND is decided by its SHAPE (structural) not by the lifecycle phase it was submitted at — fixing the bug where a PoC-shaped dict submitted at phase 'detonate' mis-classifies as 'report'"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/session_api.py — reorder SessionApi._classify to explicit->structural->phase so artifacts self-classify by SHAPE, not by submission phase (fixes PoC-at-detonate mis-tagging as report)

# Scope

EDIT the EXISTING method `SessionApi._classify` in ngv2/session_api.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). DEFECT (verified live 2026-06-11): `_classify` resolves `explicit -> phase -> structural`. Putting the phase-string ahead of structure means an artifact's KIND is decided by which phase it was submitted at, not by its shape — so a PoC dict (`{language, entrypoint, code}`) submitted at phase `detonate` mis-classifies as `report` (because `_phase_to_kind('detonate') == 'report'` fires before `_structural_kind` ever sees the PoC shape). The only reason the e2e path works today is the driver manually injecting `artifact_type:'report'`.

THE FIX (data_model — a pure single-method reordering, NO new symbol, NO signature change): reorder the resolution to `explicit -> structural -> phase`. `_structural_kind` is authoritative (it already detects `{'poc_finding_id','verdict'} -> 'report'` and `{'language','entrypoint','code'} -> 'poc'`, and returns `'finding'` as its dict default); `_phase_to_kind(phase)` becomes the last-resort fallback (it only actually fires for non-dict payloads, since `_structural_kind` never returns None for a dict). An explicit `artifact_type` still wins (the explicit check is unchanged and stays first).

Read the read-only staged target at `{WORK_DIR}/inbox/targets/ngv2/session_api.py` FIRST to confirm the current `_classify` body. Verify GREEN with `python -m pytest tests/ngv2/test_classify_structural_precedence_wired.py -q`; working_dir is /home/xnihil0zer0/NobleGreedv2.

DISPATCH DIRECTIVE — PARTIAL-EDIT (__JANUSMASK_PATCHES__) symbol patch: ngv2/session_api.py is a LARGE file (700+ lines). DO NOT reproduce the whole file. Read its CURRENT on-disk content (read-only) from `{WORK_DIR}/inbox/targets/ngv2/session_api.py`. Emit a single top-level Python list assigned to `__JANUSMASK_PATCHES__` with EXACTLY ONE 'symbol' entry that replaces the method `SessionApi._classify` (dotted Outer.method name). The submission file MUST contain ONLY this `__JANUSMASK_PATCHES__` assignment at top level (no other statements, imports, or decorators). Exact shape:

    __JANUSMASK_PATCHES__ = [
        {'file': 'ngv2/session_api.py', 'kind': 'symbol', 'name': 'SessionApi._classify',
         'code': r'''    def _classify(self, data, phase):
        explicit = self._explicit_kind(data)
        if explicit is not None:
            return explicit
        structural = self._structural_kind(data)
        if structural is not None:
            return structural
        return self._phase_to_kind(phase)
'''},
    ]

Rules: `code` MUST be exactly ONE method `def` whose name matches the leaf (`_classify`), reproduced with its real indentation as it sits inside the class (4-space method indent as shown). Use a raw triple-quoted string. Replace ONLY this one method — every other byte of session_api.py is preserved by the harness. Do NOT rename, add, or remove parameters; the signature `_classify(self, data, phase)` is unchanged. Do NOT emit a whole-file manifest. POST-EMIT SELF-CHECK: your replacement body must call `self._explicit_kind` first (return if not None), then `self._structural_kind` (return if not None), then fall through to `self._phase_to_kind(phase)` — exactly that order.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the committed oracle is keyed to this brief): `task_id`: `ngv2-classify-precedence`. meta_task_type=`data_model` (a pure in-place single-method reordering on an external NGv2 target — fuzzer-bypassed per META_TASK_POLICY; there is no new behavior surface for the diff-fuzzer, the classification logic is exercised by the committed oracle). priority: high. dependencies: []. working_dir: `/home/xnihil0zer0/NobleGreedv2`. files_touched: `["ngv2/session_api.py"]` ONLY. Emission semantics: a single `__JANUSMASK_PATCHES__` list with EXACTLY ONE 'symbol' entry on `SessionApi._classify` (per the DISPATCH DIRECTIVE — never a `__JANUSMASK_MANIFEST__` dict, never a whole-file). The DISPATCH DIRECTIVE — PARTIAL-EDIT paragraph above MUST be copied VERBATIM into the task's `implementation_notes` so the blind worker sees it. verification_command: `python -m pytest tests/ngv2/test_classify_structural_precedence_wired.py -q`. The committed RED oracle tests/ngv2/test_classify_structural_precedence_wired.py is the authoritative acceptance contract — make it GREEN; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from the committed oracle (plan descriptors referencing committed/landed tests — this does NOT authorize authoring new tests), so every `spec.edge_cases` entry is reflected per the validator's edge-case rule (e.g. `test_poc_shaped_dict_at_detonate_classifies_poc`, `test_report_shaped_dict_at_detonate_classifies_report`, `test_explicit_artifact_type_wins`, `test_shapeless_dict_at_hunt_falls_through_to_finding`).

# Non-Goals

This is an in-place EDIT of one method and integration is out of scope: the task's non_goals MUST declare integration testing out of scope — do NOT add integration/e2e tests; this change is verified solely by the committed unit oracle tests/ngv2/test_classify_structural_precedence_wired.py. Do NOT author or modify any test — that oracle is committed and authoritative. Do NOT touch any other method, function, or symbol in session_api.py — ONLY `_classify`. Do NOT touch `_structural_kind`, `_phase_to_kind`, or `_explicit_kind` (they are correct as-is and the reorder relies on their current behavior). Do NOT touch any gate handler (session_gate.py), the FSM transition logic (state_machine.py), or the e2e drivers (`_e2e_run/`). Do NOT change `_classify`'s signature or add new parameters. PATCH-SHAPE non-goals: do NOT emit a `__JANUSMASK_MANIFEST__` dict and do NOT emit a whole-file — the edit rides ONLY as the single 'symbol' `__JANUSMASK_PATCHES__` entry on `SessionApi._classify`. No network, no wall-clock, no randomness, no new dependencies.

# Inputs

The committed authoritative oracle at tests/ngv2/test_classify_structural_precedence_wired.py (currently RED: 1 failed / 3 passed). It constructs a SessionApi and asserts the precedence exhaustively, one case per branch: (a) `test_report_shaped_dict_at_detonate_classifies_report` — a LiveTestReport-shaped dict (`poc_finding_id`+`verdict`, no explicit artifact_type) at phase 'detonate' -> 'report' (GREEN today, a regression guard); (b) `test_poc_shaped_dict_at_detonate_classifies_poc` — a PoC-shaped dict (`language`+`entrypoint`+`code`, no artifact_type) at phase 'detonate' -> 'poc' (THE BUG CASE — RED today, currently returns 'report'); (c) `test_explicit_artifact_type_wins` — an explicit artifact_type always wins (GREEN today); (d) `test_shapeless_dict_at_hunt_falls_through_to_finding` — a shapeless dict at phase 'hunt' -> 'finding' (GREEN today; identical value via structural default or phase fallback). The single RED case flips GREEN once the reorder lands.

The EXACT current defective `_classify` (lines ~232-239 of session_api.py — explicit -> phase -> structural):

    def _classify(self, data, phase):
        explicit = self._explicit_kind(data)
        if explicit is not None:
            return explicit
        phase_kind = self._phase_to_kind(phase)
        if phase_kind is not None:
            return phase_kind
        return self._structural_kind(data)

The EXACT corrected `_classify` (reproduce VERBATIM as the patch `code` — explicit -> structural -> phase):

    def _classify(self, data, phase):
        explicit = self._explicit_kind(data)
        if explicit is not None:
            return explicit
        structural = self._structural_kind(data)
        if structural is not None:
            return structural
        return self._phase_to_kind(phase)

# Deliverables

Edited ngv2/session_api.py in the NobleGreedv2 repo whose `SessionApi._classify` method resolves `explicit -> structural -> phase` (structural authoritative, phase last-resort) — with NO change to any other symbol or file — so a PoC-shaped dict submitted at any phase classifies `poc` by its shape and the manual `artifact_type` workaround in the e2e drivers becomes unnecessary. Verified GREEN by `python -m pytest tests/ngv2/test_classify_structural_precedence_wired.py -q` (all 4 precedence cases).
