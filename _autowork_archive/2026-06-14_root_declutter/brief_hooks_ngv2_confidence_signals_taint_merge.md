---
interfaces: "EDITS existing ngv2/confidence_signals.py to fold CodeQL interprocedural taint-path proofs into the compute_confidence signal list: adds an optional taint_proofs param to build_confidence_signals (merged verbatim, same shape as semantic taint_flow proofs) and threads ev['taint_proofs'] through resolve_signals — so a CodeQL taint_flow/result:proof signal drives the ADMIT band"
dependencies: ["ngv2_taint_path_signal"]
meta_task_type: state_machine
spec_author: "Phase-III BUILD-PREP agent (JanusMask)"
spec_reviewed_by: "owner (CodeQL CLI use APPROVED 2026-06-12)"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/confidence_signals.py — EDIT to merge CodeQL taint-path proofs into the confidence signal list, the single production seam that lets a Stage-2 taint flow reach the ADMIT band.

# Scope

EDIT the EXISTING module `ngv2/confidence_signals.py` (NGv2 external-target task — `working_dir` = /home/xnihil0zer0/NobleGreedv2). Two existing top-level functions change, nothing else: (1) `build_confidence_signals` gains an optional keyword-only `taint_proofs: list | None = None` param and, right after the `semantic_signals` merge, appends each dict in `taint_proofs` VERBATIM (CodeQL `taint_flow`/`result:proof` proofs share the shape of the structural semantic proofs the function already merges, so `compute_confidence` reads them identically and routes ADMIT). (2) `resolve_signals` threads `taint_proofs=get('taint_proofs')` into its `build_confidence_signals` call so the live FSM gate path picks proofs up from `ev['taint_proofs']`. Both changes are additive and keyword-only — absent `taint_proofs`, output is byte-identical to before, so marker-spoofing/non-confirmed paths still cannot manufacture confidence.

DISPATCH DIRECTIVE — PATCH FORMAT (MANDATORY — PARTIAL EDIT, TWO EXISTING TOP-LEVEL FUNCTIONS): patch the two existing module-level functions `resolve_signals` and `build_confidence_signals` by re-emitting each VERBATIM in its new form (these are top-level functions, NOT class methods). Do NOT whole-file re-emit the module. Emit them BYTE-FOR-BYTE as follows.

`resolve_signals` (only the final `return build_confidence_signals(...)` line changes — it now passes `taint_proofs=get('taint_proofs')`):

```python
def resolve_signals(ev, finding=None):
    """Turn an evidence dict into the ``compute_confidence`` signal list.

    Single entry point the live triage->verify FSM gate calls. Honors a
    verbatim ``ev['signals']`` list when present; otherwise runs the structural
    semantic verifier over ``ev['source']`` and folds in any
    ``ev['live_report']`` detonation verdict via ``build_confidence_signals``.

    Totally tolerant: any import/derivation/build failure degrades to an
    empty/None list and never raises. ``ev`` may be ``None``, ``{}``, or any
    non-dict value.
    """
    get = ev.get if isinstance(ev, dict) else lambda key, default=None: default
    signals = get('signals')
    if signals is not None:
        return signals
    finding_d = finding if isinstance(finding, dict) else None
    if finding_d is None:
        ev_finding = get('finding')
        finding_d = ev_finding if isinstance(ev_finding, dict) else {}
    semantic = []
    source = get('source')
    if source:
        try:
            from ngv2.semantic_signals import produce_semantic_signals
            language = get('language')
            semantic = produce_semantic_signals(finding_d, source, language) or []
        except Exception:
            semantic = []
    try:
        return build_confidence_signals(finding_d, semantic_signals=semantic, taint_proofs=get('taint_proofs'), live_report=get('live_report'))
    except Exception:
        return semantic or None
```

`build_confidence_signals` (new `taint_proofs` kw param + the new merge block between the semantic merge and the live-detonation block):

```python
def build_confidence_signals(finding: dict, *, semantic_signals: list | None = None, taint_proofs: list | None = None, live_report: dict | object | None = None) -> list[dict]:
    """Assemble the ``compute_confidence`` input list for a single finding.

    Combines the scan finding (a ``pattern`` match), any P3.1 structural
    ``semantic_signals``, and a real live-detonation ``live_report`` (a
    ``confirmed`` verdict -> a ``live_poc`` structural proof). A non-confirmed
    detonation never contributes a proof, so marker-spoofing cannot manufacture
    confidence.
    """
    signals: list[dict] = []
    finding = finding if isinstance(finding, dict) else {}

    # The scan finding itself contributes exactly one pattern match.
    if finding:
        signals.append({
            'tool': 'scan',
            'kind': 'pattern',
            'result': 'match',
            'finding_id': finding.get('id'),
            'category': finding.get('category'),
            'cwe': finding.get('cwe'),
        })

    # Merge the structural semantic signals through unchanged.
    if semantic_signals:
        for sem in semantic_signals:
            if isinstance(sem, dict):
                signals.append(sem)

    # Merge CodeQL interprocedural taint-path proofs through verbatim (same
    # shape as semantic taint_flow proofs): a taint_flow/result:proof signal
    # drives the ADMIT band in compute_confidence.
    if taint_proofs:
        for proof in taint_proofs:
            if isinstance(proof, dict):
                signals.append(proof)

    # Only a confirmed live detonation contributes a live_poc proof.
    verdict = None
    if isinstance(live_report, dict):
        verdict = live_report.get('verdict')
    elif live_report is not None:
        verdict = getattr(live_report, 'verdict', None)
    if verdict == 'confirmed':
        signals.append({
            'tool': 'live_detonation',
            'kind': 'live_poc',
            'result': 'proof',
            'finding_id': finding.get('id'),
        })

    return signals
```

POST-EMIT SELF-CHECK (mandatory): `taint_proofs` is keyword-only and defaults to None; with `taint_proofs=None` the output equals the pre-edit output; non-dict items in `taint_proofs` are skipped; the live-detonation `confirmed` block and the `_scan_match_signal` / `_live_poc_signal` helpers are unchanged.

# Non-Goals

Do NOT change the live-detonation `confirmed` logic, the scan-match block, or the helper functions. Do NOT make `taint_proofs` positional. Do NOT touch taint_path_signal, semantic_signals, or any other module. Do NOT add network/clock/subprocess. The producer of the proofs (taint_path_signal) and the gate INTEGRATION that supplies `ev['taint_proofs']` are separate leaves — this leaf only adds the merge seam. ANTI-SEESAW: this edit shares `confidence_signals` with tests/test_confidence_signals_wired.py, tests/test_resolve_signals_wired.py, and tests/test_triage_verify_signals_wired.py — your `regression_tests` MUST keep the UNION of all four (those three + the new tests/ngv2/test_confidence_signals_taint_merge_wired.py) green.

# Inputs

The committed RED oracle tests/ngv2/test_confidence_signals_taint_merge_wired.py (5 tests; RED — param absent). It pins: a taint proof merged into the signal list verbatim; absent `taint_proofs` → output unchanged (no taint_flow signal); taint + semantic both merge; `resolve_signals` threads `ev['taint_proofs']` (live-path); non-dict proofs skipped. The three existing confidence_signals oracles are the anti-seesaw UNION partners (verified green against the edited module).

# Deliverables

The edited `ngv2/confidence_signals.py` (two functions changed), verified GREEN by `python3 -m pytest -q tests/ngv2/test_confidence_signals_taint_merge_wired.py tests/test_confidence_signals_wired.py tests/test_resolve_signals_wired.py tests/test_triage_verify_signals_wired.py`.

# Required plan shape

EXACTLY ONE impl task. task_id VERBATIM: `ngv2_confidence_signals_taint_merge`. meta_task_type=`state_machine` (confidence-gate signal assembly — partial edit of two existing top-level functions, NOT whole-file, NOT a class method). priority: high. dependencies: `["ngv2_taint_path_signal"]`. working_dir: "/home/xnihil0zer0/NobleGreedv2". files_touched: `["ngv2/confidence_signals.py"]` ONLY. partial_edit semantics: re-emit `resolve_signals` and `build_confidence_signals` verbatim per the DISPATCH DIRECTIVE (copy both blocks VERBATIM into `implementation_notes`). verification_command: `python3 -m pytest -q tests/ngv2/test_confidence_signals_taint_merge_wired.py tests/test_confidence_signals_wired.py tests/test_resolve_signals_wired.py tests/test_triage_verify_signals_wired.py` (CWD-relative — NO `cd`). `test_spec.regression_tests` (≥2 named, across the UNION): `test_taint_proof_merged_into_signal_list`, `test_resolve_signals_threads_taint_proofs_live_path`, plus the existing confidence_signals/resolve_signals oracles. `test_spec.edge_cases` (≥2): `test_absent_taint_proofs_unchanged`, `test_non_dict_taint_proofs_are_skipped`. `test_spec.integration_test`: `test_resolve_signals_threads_taint_proofs_live_path` (live FSM-gate path).
