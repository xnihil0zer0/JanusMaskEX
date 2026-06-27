"""ngv2.verdict — the triage Verdict artifact (TP/FP label + confidence).

A self-contained, pure/deterministic, stdlib-only dataclass describing the
adjudication of a single finding: whether it is a true positive (``TP``) or
false positive (``FP``), how confident that call is, and the supporting
reasoning. Provides ``to_dict``/``from_dict`` for JSON-friendly serialization
and ``validate`` to enforce invariants.

This module imports no third-party packages, performs no file or network I/O,
and does not depend on any sibling ngv2 modules.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, fields
from typing import Any, Dict
VERDICT_LABELS = ('TP', 'FP')
CONFIDENCE_LEVELS = ('HIGH', 'MEDIUM', 'LOW')

@dataclass
class Verdict:
    """A triage verdict for a single finding.

    Attributes:
        finding_id: Non-empty identifier of the finding being adjudicated.
        label: One of :data:`VERDICT_LABELS` (``'TP'`` or ``'FP'``).
        confidence: One of :data:`CONFIDENCE_LEVELS`.
        reasoning: Free-text justification for the verdict.
    """
    finding_id: str
    label: str
    confidence: str
    reasoning: str = ''

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain, JSON-friendly dict representation of this verdict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Verdict':
        """Reconstruct a :class:`Verdict` from a :meth:`to_dict` mapping.

        Only recognised keys are consumed; extra keys are ignored so that the
        round-trip ``Verdict -> to_dict() -> from_dict()`` yields an equal
        instance.
        """
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known}
        return cls(**kwargs)

    def validate(self) -> 'Verdict':
        """Validate the verdict's invariants.

        Raises:
            ValueError: if ``finding_id`` is empty, ``label`` is not one of
                :data:`VERDICT_LABELS`, or ``confidence`` is not one of
                :data:`CONFIDENCE_LEVELS`.

        Returns:
            This verdict, to allow fluent chaining.
        """
        if not self.finding_id:
            raise ValueError('finding_id must be a non-empty string')
        if self.label not in VERDICT_LABELS:
            raise ValueError(f'label must be one of {VERDICT_LABELS}, got {self.label!r}')
        if self.confidence not in CONFIDENCE_LEVELS:
            raise ValueError(f'confidence must be one of {CONFIDENCE_LEVELS}, got {self.confidence!r}')
        return self