---
interfaces: "NEW data_model module ngv2/verdict_feedback.py exposing is_fp_signal(verdict) and apply_reject_verdict(verdict, finding, fp_file, now=None); a CONSUMER of ngv2.fp_patterns.add_fp_pattern that grows the FP store on a rejected/duplicate huntr verdict (returns None on non-rejections). Imports SubmissionVerdict from ngv2.submission_verdict."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
meta_task_type: data_model
---

# Title

ngv2/verdict_feedback.py — NEW Phase-7.2a consumer: a rejected/duplicate huntr verdict grows the FP-pattern store (via fp_patterns.add_fp_pattern)

# Scope

Build a NEW data_model module ngv2/verdict_feedback.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). This is Phase-7.2a: it applies a huntr SubmissionVerdict to the false-positive knowledge base. It is a pure CONSUMER of the existing ngv2.fp_patterns.add_fp_pattern — it NEVER re-implements the store and NEVER edits ngv2/fp_patterns.py (anti-seesaw: a new consumer module, not an edit of the shared FP store). On a rejected/duplicate verdict it appends exactly one FP pattern to the given fp_file and returns the new entry; on any non-rejection it returns None and leaves the store untouched. Deterministic — the ``now`` timestamp is an injected seam passed straight through to add_fp_pattern; no clock/network/randomness. Imports SubmissionVerdict from ngv2.submission_verdict (built by the P7.1 leaf). Emit the whole file VERBATIM from Deliverables. Name the committed oracle tests/test_verdict_feedback_wired.py in the verification_command. Required plan shape: EXACTLY ONE impl task building this one new single file.

# Non-Goals

This is a NEW single-file module, not an edit; integration is out of scope — do NOT author or modify any test (tests/test_verdict_feedback_wired.py is committed and authoritative) and do NOT add integration/e2e tests. Do NOT edit ngv2/fp_patterns.py, ngv2/fp_filter.py, ngv2/fp_patterns.json, or any other module — consume add_fp_pattern as-is. Do NOT call the network, a clock, or randomness (the only side effect is add_fp_pattern's own file write to the caller-supplied fp_file). No LLM, no third-party imports. Touch exactly the one new file ngv2/verdict_feedback.py.

# Inputs

``ngv2.fp_patterns.add_fp_pattern(finding, reason, source='auto', context='', fp_file=None, now=None) -> dict`` already exists (HEAD): it appends a pattern derived from ``finding`` (its rule id from finding['id']/['rule_id']/['rule_short'], cwe, file_pattern, code) and persists to fp_file, returning the entry. ``ngv2.fp_patterns.load_fp_patterns(fp_file) -> list`` reads them back. ``SubmissionVerdict`` (ngv2.submission_verdict, P7.1) exposes ``.state`` and ``.reason``; ``.is_rejected`` is True for state in {rejected, duplicate}. The oracle passes a tmp_path fp_file and a verdict built via parse_verdict_response, asserting the store grows by exactly one and the new entry's reason embeds the verdict state.

# Deliverables

ngv2/verdict_feedback.py with EXACTLY this content:

```python
"""ngv2.verdict_feedback — apply a rejected/duplicate SubmissionVerdict to the
FP knowledge base (Phase 7.2a).

A CONSUMER of ngv2.fp_patterns.add_fp_pattern: it never re-implements the store.
A rejected/duplicate verdict for a finding grows the FP-pattern JSON so the same
class of finding is suppressed next run. Deterministic — the ``now`` timestamp
is an injected seam; no clock/network/randomness.
"""
from __future__ import annotations
from typing import Any, Dict, Optional
from ngv2.fp_patterns import add_fp_pattern
from ngv2.submission_verdict import SubmissionVerdict


def _verdict_state(verdict: Any) -> str:
    if isinstance(verdict, SubmissionVerdict):
        return verdict.state
    if isinstance(verdict, dict):
        return str(verdict.get('state', '')).strip().lower()
    return str(getattr(verdict, 'state', '') or '').strip().lower()


def is_fp_signal(verdict: Any) -> bool:
    """True iff the verdict is a rejection/duplicate (an FP teaching signal)."""
    return _verdict_state(verdict) in ('rejected', 'duplicate')


def apply_reject_verdict(verdict: Any, finding: Dict[str, Any],
                         fp_file, now: Optional[str] = None) -> Optional[dict]:
    """Grow the FP store from a reject/duplicate verdict; else return ``None``.

    The reason embeds the verdict state so the resulting pattern is traceable
    back to the maintainer's adjudication.
    """
    if not is_fp_signal(verdict):
        return None
    state = _verdict_state(verdict)
    reason = 'huntr verdict: %s' % state
    if isinstance(verdict, SubmissionVerdict) and verdict.reason:
        reason = '%s — %s' % (reason, verdict.reason)
    return add_fp_pattern(finding, reason=reason, source='huntr_verdict',
                          fp_file=fp_file, now=now)
```

DISPATCH DIRECTIVE — this is a NEW single-file module. Emit it as a single whole-file deliverable for ngv2/verdict_feedback.py reproducing the Deliverables content BYTE-FOR-BYTE, including the two real imports `from ngv2.fp_patterns import add_fp_pattern` and `from ngv2.submission_verdict import SubmissionVerdict`. Do NOT emit a `__JANUSMASK_PATCHES__` list — this is a new file, not a symbol patch. meta_task_type=data_model (external NGv2 target; fuzzer-bypassed, smoke-gated). Use this task_id VERBATIM: `ngv2-verdict-feedback-fp`. priority: high. dependencies: []. files_touched: `["ngv2/verdict_feedback.py"]` ONLY. verification_command (CWD-relative, NO `cd`): `.venv/bin/python -m pytest tests/test_verdict_feedback_wired.py -q`. The committed oracle tests/test_verdict_feedback_wired.py is the authoritative acceptance contract; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from this brief's committed oracle (descriptors referencing the committed oracle — NOT authorization to author tests), e.g. `test_reject_verdict_grows_fp_store_by_one` and `test_accepted_verdict_does_not_grow_store` (also good: `test_duplicate_verdict_also_grows_store`, `test_is_fp_signal_only_for_rejections`).
