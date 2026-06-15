---
dependencies: []
interfaces: "edits ngv2/pipeline.py run_pipeline to thread an optional handlers['expected_fs_signature'] through to DetonationChamber.detonate(..., expected_fs_signature=...) so a genuine fs-effect PoC reaches the strong semantic gate"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
verification_command: ".venv/bin/python -m pytest tests/test_pipeline.py::test_run_pipeline_full_flow_confirmed tests/test_pipeline.py::test_run_pipeline_triage_drops_findings tests/test_pipeline.py::test_run_pipeline_invokes_report_handler tests/test_pipeline.py::test_run_pipeline_no_findings_still_completes -q"
---

# Title

ngv2/pipeline.py — thread optional expected_fs_signature from handlers through run_pipeline into DetonationChamber.detonate so fs-effect PoCs reach the strong semantic gate

# Scope

EDIT the EXISTING module `ngv2/pipeline.py` in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). The ONLY behavioral change vs the current file is inside `run_pipeline`: read an OPTIONAL `expected_fs_signature` from the injected `handlers` dict via `handlers.get('expected_fs_signature')` and pass it as the keyword-only argument `expected_fs_signature=...` to every `chamber.detonate(...)` call. When `handlers` has no `'expected_fs_signature'` key the value is `None` and behavior is identical to today (the chamber's no-signature path applies). When a handler supplies a string `expected_fs_signature` (and the runner returns a 5-tuple carrying the fs diff), the verdict is delegated to the strong `semantic_verdict` gate inside the chamber, so a genuine filesystem-effect PoC reaches `'confirmed'`.

This is a whole-file replacement of a SHORT module. The complete VALIDATED file content is embedded below (oracle-proven green against it) — ship `ngv2/pipeline.py` EXACTLY as the whole file below, byte-for-byte. Do NOT restructure, do NOT invent a different handler contract (the real handlers are `hunt`/`triage`/`poc`/`runner` driving a `HuntStateMachine` — NOT a `handlers['pocs']` list), do NOT drop the state-machine transitions, and do NOT change the returned `{'phase','reports','report'}` dict shape.

meta_task_type=`refactor`. # Required plan shape: EXACTLY ONE impl task (no decomposition — this is a tiny whole-file edit), meta_task_type=refactor, files_touched=[`ngv2/pipeline.py`]; integration tests EXCUSED via Non-Goals; author NO new tests — the committed oracle `tests/test_pipeline.py` is authoritative. The plan's `spec.edge_cases` MUST mirror into `test_spec.regression_tests` by NAME referencing the already-committed oracle tests (do NOT author them): set `regression_tests` to at least these two existing tests — `test_run_pipeline_full_flow_confirmed` (fs-signature threads through → 'confirmed') and `test_run_pipeline_marker_only_is_inconclusive` (absent key → 'inconclusive'). verification_command exactly as in the front-matter (the four committed `tests/test_pipeline.py` flow tests).

# Non-Goals

This is an EDIT and integration is out of scope — the literal word integration: do NOT add integration/e2e tests, do NOT author or modify any test (the oracle `tests/test_pipeline.py` is committed and authoritative). Do NOT modify `ngv2/detonation.py`, `ngv2/poc_runner.py`, `ngv2/poc_runner_live.py`, `ngv2/handlers.py`, `ngv2/contracts.py`, `ngv2/state_machine.py`, or any module other than `ngv2/pipeline.py`. Do NOT change `run_pipeline`'s signature `(handlers, *, success_marker='VULNERABLE') -> dict`, the existing handler-key contract (`hunt`/`triage`/`poc`/`runner`/`target_spec`/`report`), the state-machine transition sequence, or the returned dict shape. Do NOT make `expected_fs_signature` a positional/required argument. Do NOT perform any real fork/execve/subprocess/network/clock/random work; keep the module pure and deterministic (stdlib + ngv2 only). Do NOT rewrite the orchestrator around a different/invented handler shape.

# Inputs

The current `ngv2/pipeline.py` (a short module: a module docstring, two `from ngv2.* import` lines, and the single `run_pipeline` function that builds a `HuntStateMachine`, walks hunt->triage->poc->detonate->report->done over the injected handler callables, and returns `{'phase','reports','report'}`). The read-only reference `ngv2.detonation.DetonationChamber.detonate(self, poc, target_spec, runner, *, expected_fs_signature=None) -> LiveTestReport` (already accepts the keyword-only `expected_fs_signature`; when a string is supplied it routes through `semantic_verdict` over an fs_snapshot_diff drawn from a 4-tuple (empty diff) or 5-tuple runner result). `ngv2.state_machine.HuntStateMachine` (read-only). The committed authoritative oracle `tests/test_pipeline.py` (asserts: a genuine fs-effect PoC with `handlers['expected_fs_signature']` set and a 5-tuple runner -> `'confirmed'`; marker-only with no signature -> `'inconclusive'` (handled by the chamber, not here); and the triage/report/no-findings flows unchanged). stdlib + ngv2 only.

# Deliverables

Replace the WHOLE file `ngv2/pipeline.py` with EXACTLY this VALIDATED content (oracle-proven green):

```python
"""Deterministic, stdlib-only hunt->triage->poc->detonate->report->done orchestrator.

Drives a :class:`HuntStateMachine` through its phases over injected phase-handler
callables, detonating each poc through an injected runner via
:class:`DetonationChamber`, and returns a fixed-shape result dict. The module is
pure: no module-level state, no logging, no I/O, no randomness.
"""
from __future__ import annotations
from ngv2.detonation import DetonationChamber
from ngv2.state_machine import HuntStateMachine

def run_pipeline(handlers: dict, *, success_marker: str='VULNERABLE') -> dict:
    """Walk the hunt pipeline to completion and return its result dict.

    ``handlers`` supplies the phase-handler callables:
      * ``'hunt'() -> findings``
      * ``'triage'(findings) -> kept`` (may drop findings)
      * ``'poc'(findings) -> pocs``
      * ``'runner'(poc, target_spec) -> (exit_code, stdout, stderr, duration_ms)``
      * optional ``'target_spec'``
      * optional ``'expected_fs_signature'`` -- when a string is supplied it is
        threaded into every ``DetonationChamber.detonate`` call so a genuine
        filesystem-effect PoC reaches the strong semantic gate; when the key is
        absent ``handlers.get(...)`` is ``None`` and the no-signature path applies
      * optional ``'report'(state, reports) -> object``

    Returns ``{'phase': 'done', 'reports': [LiveTestReport.to_dict() in poc
    order], 'report': handlers['report'](state, reports) or None}``.
    """
    sm = HuntStateMachine()
    for f in handlers['hunt']():
        sm.add_finding(f)
    sm.transition('triage')
    kept = handlers['triage'](list(sm.state.findings))
    sm.state.findings = list(kept)
    sm.transition('poc')
    pocs = handlers['poc'](list(sm.state.findings))
    sm.transition('detonate')
    chamber = DetonationChamber(success_marker=success_marker)
    expected_fs_signature = handlers.get('expected_fs_signature')
    reports = [
        chamber.detonate(
            poc,
            handlers.get('target_spec'),
            handlers['runner'],
            expected_fs_signature=expected_fs_signature,
        )
        for poc in pocs
    ]
    sm.transition('report')
    report = handlers['report'](sm.state, reports) if 'report' in handlers else None
    sm.transition('done')
    return {'phase': sm.state.phase, 'reports': [r.to_dict() for r in reports], 'report': report}
```

Verified GREEN by the verification_command (the four `tests/test_pipeline.py` flow tests, including `test_run_pipeline_full_flow_confirmed` which proves the fs-signature threads through to a `'confirmed'` verdict).
