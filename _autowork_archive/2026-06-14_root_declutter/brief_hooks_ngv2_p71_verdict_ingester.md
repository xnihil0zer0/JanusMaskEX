---
interfaces: "NEW io_adapter module ngv2/submission_verdict.py exposing the SubmissionVerdict dataclass (submission_id/state/payout/reason/raw, to_dict/from_dict/validate, is_accepted/is_rejected), VERDICT_STATES, parse_verdict_response(submission_id, response) (pure), and ingest_verdict(submission_id, fetcher) which polls the huntr verdict through an INJECTED fetcher seam so the oracle is hermetic (no real network)"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
meta_task_type: io_adapter
---

# Title

ngv2/submission_verdict.py — NEW Phase-7.1 huntr SUBMISSION verdict ingester (SubmissionVerdict dataclass + hermetic ingest via injected fetcher seam)

# Scope

Build a NEW io_adapter module ngv2/submission_verdict.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). This is the Phase-7.1 verdict ingester: per submitted finding it records the EXTERNAL huntr maintainer/program verdict (submitted / triage / accepted / rejected / duplicate, plus payout) into a typed record. It is DISTINCT from the existing ngv2/verdict.py (which is the INTERNAL TP/FP triage artifact) — do NOT touch or import ngv2/verdict.py. The only impure operation — fetching the huntr verdict — is behind an INJECTED ``fetcher(submission_id) -> dict`` seam, so ingestion is fully hermetic, deterministic, and stdlib-only (no real network, clock, randomness, or sibling-module dependency). Emit the whole file VERBATIM from Deliverables. Name the committed oracle tests/test_submission_verdict_wired.py in the verification_command. Required plan shape: EXACTLY ONE impl task building this one new single file.

# Non-Goals

This is a NEW single-file module, not an edit; integration is out of scope — do NOT author or modify any test (the oracle tests/test_submission_verdict_wired.py is committed and authoritative) and do NOT add integration/e2e tests. Do NOT touch, import, or alter ngv2/verdict.py (the internal triage artifact), ngv2/submission.py, ngv2/submission_parser.py, or any other module. Do NOT call the network, a real huntr endpoint, a clock, or randomness in any path — the huntr fetch goes ONLY through the injected ``fetcher`` seam. No LLM, no third-party imports (stdlib only). Touch exactly the one new file ngv2/submission_verdict.py.

# Inputs

The injected ``fetcher(submission_id: str) -> dict`` returns a raw huntr response mapping; the oracle always injects a canned fetcher so no network is touched. Recognised response keys: ``state`` or ``status`` (the verdict state), ``payout`` or ``amount`` (numeric payout), ``reason`` or ``message`` (free text). VERDICT_STATES is the tuple of valid states (submitted, triage, accepted, rejected, duplicate); an unknown/absent state falls back to ``submitted``. ``is_rejected`` is True for both ``rejected`` and ``duplicate``.

# Deliverables

ngv2/submission_verdict.py with EXACTLY this content:

```python
"""ngv2.submission_verdict — huntr SUBMISSION verdict ingester (Phase 7.1).

Distinct from ngv2.verdict (which is the internal TP/FP triage artifact): this
module records the EXTERNAL huntr maintainer/program verdict for a submitted
finding (triage / accepted / rejected / duplicate, plus payout). The huntr fetch
is routed through an INJECTED fetcher seam so ingestion is fully hermetic — no
real network, clock, randomness, or sibling-module dependency.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Callable, Dict

VERDICT_STATES = ('submitted', 'triage', 'accepted', 'rejected', 'duplicate')
_REJECT_STATES = ('rejected', 'duplicate')


@dataclass
class SubmissionVerdict:
    """The external huntr verdict for one submitted finding."""
    submission_id: str
    state: str = 'submitted'
    payout: float = 0.0
    reason: str = ''
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SubmissionVerdict':
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def validate(self) -> 'SubmissionVerdict':
        if not self.submission_id:
            raise ValueError('submission_id must be a non-empty string')
        if self.state not in VERDICT_STATES:
            raise ValueError('state must be one of %r, got %r' % (VERDICT_STATES, self.state))
        return self

    @property
    def is_accepted(self) -> bool:
        return self.state == 'accepted'

    @property
    def is_rejected(self) -> bool:
        return self.state in _REJECT_STATES


def _coerce_state(raw_state: Any) -> str:
    s = str(raw_state or '').strip().lower()
    return s if s in VERDICT_STATES else 'submitted'


def _coerce_payout(raw: Any) -> float:
    if isinstance(raw, bool) or raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def parse_verdict_response(submission_id: str, response: Dict[str, Any]) -> SubmissionVerdict:
    """Parse a (already-fetched) huntr response mapping into a SubmissionVerdict.

    Pure: no I/O. Recognises ``state``/``status``, ``payout``/``amount``,
    ``reason``/``message``. Unknown/absent state falls back to ``submitted``.
    """
    if not isinstance(response, dict):
        response = {}
    state = _coerce_state(response.get('state', response.get('status')))
    payout = _coerce_payout(response.get('payout', response.get('amount')))
    reason = str(response.get('reason', response.get('message', '')) or '')
    return SubmissionVerdict(submission_id=submission_id, state=state,
                             payout=payout, reason=reason, raw=dict(response))


def ingest_verdict(submission_id: str,
                   fetcher: Callable[[str], Dict[str, Any]]) -> SubmissionVerdict:
    """Poll the huntr verdict for ``submission_id`` via the INJECTED ``fetcher``.

    ``fetcher`` maps a submission id to a raw response mapping; it is the only
    seam that would touch the network in production. Here it is always injected,
    keeping the function hermetic and deterministic.
    """
    response = fetcher(submission_id)
    return parse_verdict_response(submission_id, response).validate()
```

DISPATCH DIRECTIVE — this is a NEW single-file module. Emit it as a single whole-file deliverable for ngv2/submission_verdict.py reproducing the Deliverables content BYTE-FOR-BYTE (it already imports everything it needs from the stdlib; no ngv2 sibling imports). Do NOT emit a `__JANUSMASK_PATCHES__` list — this is a new file, not a symbol patch. meta_task_type=io_adapter (external NGv2 target; the diff-fuzzer cannot resolve external imports, so use the fuzzer-bypassed, smoke-gated io_adapter meta-type). Use this task_id VERBATIM: `ngv2-submission-verdict-ingester`. priority: high. dependencies: []. files_touched: `["ngv2/submission_verdict.py"]` ONLY. verification_command (CWD-relative, NO `cd`): `.venv/bin/python -m pytest tests/test_submission_verdict_wired.py -q`. The committed oracle tests/test_submission_verdict_wired.py is the authoritative acceptance contract; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from this brief's committed oracle (plan descriptors referencing the committed oracle — this does NOT authorize authoring tests), e.g. `test_ingest_parses_accepted_with_payout_and_is_hermetic` and `test_unknown_state_falls_back_to_submitted` (also good: `test_validate_rejects_empty_id_and_bad_state`, `test_payout_coercion_is_robust`).
