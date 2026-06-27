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
    return SubmissionVerdict(submission_id=submission_id, state=state, payout=payout, reason=reason, raw=dict(response))

def ingest_verdict(submission_id: str, fetcher: Callable[[str], Dict[str, Any]]) -> SubmissionVerdict:
    """Poll the huntr verdict for ``submission_id`` via the INJECTED ``fetcher``.

    ``fetcher`` maps a submission id to a raw response mapping; it is the only
    seam that would touch the network in production. Here it is always injected,
    keeping the function hermetic and deterministic.
    """
    response = fetcher(submission_id)
    return parse_verdict_response(submission_id, response).validate()