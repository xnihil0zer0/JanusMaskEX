---
interfaces: "edits ngv2/submission_readiness_gate.py so the gate has a REAL readiness_score provider — the phantom ngv2_submission_package_builder / ngv2.submission_package_builder import resolves _readiness_score to None, making _report_package_ok constant-False and {'ready': True, 'missing': None} unreachable; the fix rewrites _report_package_ok to fall back at call time to a new inlined module-level readiness_score(package) (legacy 0-3 artifact-group semantics) riding as a trailing R-anchor node, unblocking the bounty-FSM report -> awaiting_submission edge"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/submission_readiness_gate.py — give the readiness gate a REAL `readiness_score` provider (inline legacy 0-3 scoring as a call-time fallback in `_report_package_ok`) so `readiness()` can actually return `{'ready': True, 'missing': None}` instead of forever parking every fully-stocked finding at `missing == 'report_package'`

# Scope

EDIT the EXISTING module ngv2/submission_readiness_gate.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). DEFECT (verified live): the gate's module-level import chain tries `from ngv2_submission_package_builder import readiness_score` then `from ngv2.submission_package_builder import readiness_score` — BOTH modules are PHANTOM (neither exists anywhere in the repo; the real package module is `ngv2.submission_package`, which exposes `build_submission_package`/`render_template` but NO `readiness_score`; the only other `readiness_score` in the tree is a dataclass FIELD on `ngv2.submission_readiness.FindingScore`, not a callable provider). The chain therefore falls through to `_readiness_score = None`, `_report_package_ok` returns False unconditionally (`if _readiness_score is None: return False`), and `readiness()` can NEVER return ready==True on the live path: every fully-stocked finding parks at `{'ready': False, 'missing': 'report_package'}` and the bounty-FSM `report -> awaiting_submission` edge is permanently blocked. The gate's own committed oracle (ngv2/tests/test_submission_readiness_gate.py, NGv2 commit 136585e) masks this with an autouse monkeypatch of `gate._readiness_score`. THE FIX (do NOT touch the module-level try/except import block — module-level statements are not symbol-addressable and the monkeypatched-oracle compatibility depends on `_readiness_score` keeping its current import-or-None semantics): (1) REWRITE the existing top-level function `_report_package_ok` to select its scorer AT CALL TIME — `scorer = _readiness_score if callable(_readiness_score) else readiness_score` — then keep the existing try/except + `score == _REQUIRED_READINESS_SCORE` logic; (2) ADD one NEW top-level function `readiness_score(package)` implementing the legacy 0-3 semantics: return 0 for non-dict input, else award one point per artifact GROUP present and truthy in the package dict — group 1 rendered submission package/report content `('submission_pkg', 'report', 'report_markdown', 'package_markdown', 'markdown', 'title')`, group 2 PoC reference `('poc', 'poc_file', 'poc_reference')`, group 3 live-test evidence `('live_test', 'live_test_evidence', 'live_report')` — never raising. EXACT corrected target (reproduce VERBATIM):

    def _report_package_ok(package: Any) -> bool:
        """True iff the effective readiness score of ``package`` is exactly 3; never raises."""
        scorer = _readiness_score if callable(_readiness_score) else readiness_score
        try:
            score = scorer(package)
        except Exception:
            return False
        return score == _REQUIRED_READINESS_SCORE

    def readiness_score(package: Any) -> int:
        """Legacy 0-3 submission-readiness score over a package dict.

        One point per artifact group present and truthy: the rendered
        submission package/report content, the PoC reference, and the
        live-test evidence. Total and deterministic: returns 0 for non-dict
        input; never raises.
        """
        if not isinstance(package, dict):
            return 0
        groups = (('submission_pkg', 'report', 'report_markdown', 'package_markdown', 'markdown', 'title'), ('poc', 'poc_file', 'poc_reference'), ('live_test', 'live_test_evidence', 'live_report'))
        score = 0
        for keys in groups:
            if any((bool(package.get(key)) for key in keys)):
                score += 1
        return score

Keep both functions pure/deterministic (no clock, randomness, network, subprocess; stdlib only). Read the read-only staged target at `{WORK_DIR}/inbox/targets/ngv2/submission_readiness_gate.py` FIRST for the exact current module layout. Verify GREEN with `python -m pytest tests/ngv2/test_submission_readiness_ready_path_wired.py ngv2/tests/test_submission_readiness_gate.py -q`; working_dir is /home/xnihil0zer0/NobleGreedv2.

LOUD DISPATCH DIRECTIVE — PATCH FORMAT (SINGLE R-ANCHORED SYMBOL PATCH; the new `readiness_score` function does NOT exist yet, so it can NEVER be its own patch anchor — a not-yet-existing symbol name raises KeyError): emit a single top-level `__JANUSMASK_PATCHES__` list with EXACTLY ONE entry:

    __JANUSMASK_PATCHES__ = [
        {'file': 'ngv2/submission_readiness_gate.py', 'kind': 'symbol', 'name': '_report_package_ok',
         'code': r'''def _report_package_ok(package: Any) -> bool:
    ... the corrected function, byte-for-byte per the Scope target ...

def readiness_score(package: Any) -> int:
    ... the new function, byte-for-byte per the Scope target ...
'''},
    ]

The `name` MUST be the 1-part TOP-LEVEL name `'_report_package_ok'` (an EXISTING symbol — never `'readiness_score'`, never a dotted qualname). The `code` raw string MUST contain exactly TWO top-level `def` nodes, both starting at column 0: first the rewritten `_report_package_ok` (the anchor), then the NEW `readiness_score` riding as the TRAILING extra node (the R-anchor pattern for introducing a new top-level symbol). POST-EMIT SELF-CHECK (mandatory): your emitted `code` must START with `def _report_package_ok(package: Any) -> bool:` at column 0, must contain `def readiness_score(package: Any) -> int:` at column 0 exactly once, and must NOT contain `class `, `import `, or any third top-level statement. Do NOT emit a `__JANUSMASK_MANIFEST__`, do NOT emit a whole-file rewrite, do NOT touch the module-level try/except import block, the module docstring, the constants (`MISSING_*`, `PRECEDENCE`, `ELIGIBLE_CONFIDENCE`, `_CONFIRMED_VERDICT`, `_REQUIRED_NOVELTY`, `_GO_DECISION`, `_REQUIRED_READINESS_SCORE`), or any other top-level symbol (`_attr_or_item`, `_confidence_ok`, `_live_test_ok`, `_novelty_ok`, `_bounty_ok`, `readiness`).

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the committed oracle is keyed to this brief): `task_id`: `ngv2-fix-submission-readiness-import`. meta_task_type=`data_model` (external NGv2 target — the diff-fuzzer cannot resolve external imports, so use a fuzzer-bypassed, smoke-gated meta-type). priority: high. dependencies: []. working_dir: `/home/xnihil0zer0/NobleGreedv2`. files_touched: `["ngv2/submission_readiness_gate.py"]` ONLY. partial_edit semantics: a single `__JANUSMASK_PATCHES__` list with EXACTLY ONE `'symbol'` entry whose `name` is the 1-part top-level `'_report_package_ok'`, with the new `readiness_score` function riding as the trailing extra node per the LOUD DISPATCH DIRECTIVE (never a `'readiness_score'` anchor, never a dotted qualname, never a manifest, never a whole-file rewrite). The LOUD DISPATCH DIRECTIVE — PATCH FORMAT paragraph above MUST be copied VERBATIM into the task's `implementation_notes` so the blind worker sees it. verification_command: `python -m pytest tests/ngv2/test_submission_readiness_ready_path_wired.py ngv2/tests/test_submission_readiness_gate.py -q`. The committed RED oracle tests/ngv2/test_submission_readiness_ready_path_wired.py (NGv2 commit 8aea034) is the authoritative, variant-agnostic acceptance contract — make it GREEN while keeping the previously-green committed gate oracle ngv2/tests/test_submission_readiness_gate.py GREEN; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from the committed oracle `tests/ngv2/test_submission_readiness_ready_path_wired.py` (plan descriptors referencing committed/landed tests — this does NOT authorize authoring new tests), so every `spec.edge_cases` entry is reflected per the validator's edge-case rule (e.g. `test_ready_true_is_reachable_without_monkeypatch`, `test_partial_package_still_parks_on_report_package`, `test_confidence_precedence_unbroken`, `test_gate_has_a_real_readiness_score_provider`).

# Non-Goals

This is an EDIT and integration is out of scope: the task's non_goals MUST declare integration testing out of scope — do NOT add integration/e2e tests; this fix is verified solely by the committed unit oracles tests/ngv2/test_submission_readiness_ready_path_wired.py and ngv2/tests/test_submission_readiness_gate.py. Do NOT author or modify any test — both oracles are committed and authoritative. Do NOT create the module ngv2/submission_package_builder.py (or a top-level ngv2_submission_package_builder.py) — the phantom import stays phantom; the fix is the call-time fallback inside `_report_package_ok`, which preserves the committed gate oracle's `gate._readiness_score` monkeypatch seam. Do NOT modify ngv2/submission_package.py, ngv2/submission_readiness.py, ngv2/session_gate.py, ngv2/session_api.py, ngv2/contracts.py, or any other module — edit ngv2/submission_readiness_gate.py ONLY. Do NOT change the module-level try/except import block, the module docstring, any module constant (`_REQUIRED_READINESS_SCORE` stays 3), the `readiness()` function, its precedence order, or any helper other than `_report_package_ok`. Do NOT make `readiness_score` honor a `'_mock_score'` key (that is an oracle-side monkeypatch convention, not production behavior). PATCH-SHAPE non-goals: do NOT anchor the patch on the not-yet-existing `'readiness_score'` (KeyError), do NOT emit a dotted qualname, a `__JANUSMASK_MANIFEST__`, or a whole-file rewrite; the new function rides ONLY as the trailing extra node of the `'_report_package_ok'` symbol patch. No new imports, no network, no wall-clock, no randomness, no third-party dependencies.

# Inputs

The committed authoritative oracle at tests/ngv2/test_submission_readiness_ready_path_wired.py (NGv2 commit 8aea034; currently RED with `AssertionError: ready==True must be reachable on the live (un-monkeypatched) path for a fully-stocked package; got {'ready': False, 'missing': 'report_package'}` plus the provider assertion `PHANTOM IMPORT: ... _readiness_score fell back to None`). It drives `readiness()` UNPATCHED with real `ngv2.contracts` fixtures (Finding/PoC/LiveTestReport with `live_tested=True`, verdict `'confirmed'`, novelty `'NOVEL'`, bounty `{'decision': 'GO', 'target_spec': {...}}`, confidence `'CONFIRMED'`) and a fully-stocked package dict carrying every key group named in Scope, asserting `{'ready': True, 'missing': None}`; it also asserts a package stripped of all live-test keys still parks on `'report_package'` and that confidence precedence is undisturbed. The previously-green committed gate oracle ngv2/tests/test_submission_readiness_gate.py (NGv2 commit 136585e) must STAY green — its autouse fixture monkeypatches `gate._readiness_score` to a callable, which the corrected `_report_package_ok` must keep honoring via the `callable(_readiness_score)` call-time check. The EXACT current source being replaced (from ngv2/submission_readiness_gate.py at HEAD — the phantom-import fallback context, read-only, do NOT edit:

    try:
        from ngv2_submission_package_builder import readiness_score as _readiness_score
    except Exception:
        try:
            from ngv2.submission_package_builder import readiness_score as _readiness_score
        except Exception:
            _readiness_score = None

and the defective function to rewrite):

    def _report_package_ok(package: Any) -> bool:
        """True iff readiness_score(package) is exactly 3; never raises."""
        if _readiness_score is None:
            return False
        try:
            score = _readiness_score(package)
        except Exception:
            return False
        return score == _REQUIRED_READINESS_SCORE

Legacy readiness_score semantics reference (read-only): /home/xnihil0zer0/AI-Data/NobleGreed-legacy/services/submission_scorer.py `score_finding` computes `readiness_score = sum([pkg.exists, poc.exists, live_test.exists])` (0-3), mirrored in ngv2/submission_readiness.py `score_finding`. stdlib + ngv2 only.

# Deliverables

Edited ngv2/submission_readiness_gate.py in which `_report_package_ok` selects its scorer at call time (`_readiness_score` when callable — preserving the committed oracle's monkeypatch seam and any future real builder import — else the new inlined `readiness_score`) and the new top-level `readiness_score(package)` implements the legacy 0-3 artifact-group scoring exactly as pinned in Scope, with NO change to any other symbol, constant, import, or module, so `readiness()` returns `{'ready': True, 'missing': None}` for a fully-stocked finding on the live un-monkeypatched path and the bounty-FSM `report -> awaiting_submission` edge unblocks. Verified GREEN by `python -m pytest tests/ngv2/test_submission_readiness_ready_path_wired.py ngv2/tests/test_submission_readiness_gate.py -q`.
