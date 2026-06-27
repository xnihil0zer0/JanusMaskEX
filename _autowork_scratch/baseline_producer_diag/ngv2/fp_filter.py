"""False-positive filtering for NobleGreedv2 (ngv2).

Pure, deterministic, stdlib-only module that drops by-design or
protocol-mandated false positives from a list of findings by matching
each finding against a set of false-positive patterns.

Matching rules for a single :class:`FPPattern`:

* ``cwe``            -> exact string equality with ``finding['cwe']``.
* ``file_pattern``   -> :func:`fnmatch.fnmatch` against ``finding['file']``.
* ``code_signature`` -> substring (``in``) check inside ``finding['code']``.

A finding is considered a false positive when it matches *all three*
criteria of *any* loaded pattern.

This module performs no file or network I/O: patterns are sourced from an
in-memory dictionary payload.
"""
from __future__ import annotations
import fnmatch
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence
__all__ = ['FPPattern', 'load_fp_patterns', 'matches', 'filter_findings']

@dataclass
class FPPattern:
    """A criteria pattern describing a known false positive.

    Attributes:
        id: Stable identifier for the pattern (e.g. ``"fp_001"``).
        cwe: CWE identifier that a finding must match exactly.
        code_signature: Substring that must appear in a finding's code.
        file_pattern: ``fnmatch`` glob a finding's file path must match.
        reason: Human-readable justification for why this is a FP.
    """
    id: str
    cwe: str
    code_signature: str
    file_pattern: str
    reason: str

def load_fp_patterns(data: Mapping[str, Any]) -> List[FPPattern]:
    """Convert a raw in-memory payload into :class:`FPPattern` objects.

    Args:
        data: Mapping containing a ``"patterns"`` key whose value is an
            iterable of raw pattern dictionaries. A missing or falsy
            ``"patterns"`` key yields an empty list.

    Returns:
        A list of :class:`FPPattern` instances, preserving input order.
    """
    raw_patterns: Iterable[Mapping[str, Any]] = (data or {}).get('patterns') or []
    return [FPPattern(id=raw.get('id', ''), cwe=raw.get('cwe', ''), code_signature=raw.get('code_signature', ''), file_pattern=raw.get('file_pattern', '*'), reason=raw.get('reason', '')) for raw in raw_patterns]

def matches(pattern: FPPattern, finding: Mapping[str, Any]) -> bool:
    """Return ``True`` if ``finding`` matches ``pattern`` on all criteria.

    A match requires:

    * exact equality between ``pattern.cwe`` and ``finding['cwe']``,
    * ``fnmatch`` of ``finding['file']`` against ``pattern.file_pattern``,
    * ``pattern.code_signature`` being a substring of ``finding['code']``.

    Missing finding fields are treated as empty values and therefore do
    not match (unless the pattern criterion is itself empty/wildcard).
    """
    cwe = finding.get('cwe', '')
    file_path = finding.get('file', '')
    code = finding.get('code', '')
    if pattern.cwe != cwe:
        return False
    if not fnmatch.fnmatch(file_path, pattern.file_pattern):
        return False
    if pattern.code_signature not in code:
        return False
    return True

def filter_findings(findings: Sequence[Mapping[str, Any]], patterns: Sequence[FPPattern]) -> List[Dict[str, Any]]:
    """Drop findings that match any false-positive pattern.

    Args:
        findings: The findings to filter.
        patterns: The loaded false-positive patterns.

    Returns:
        A new list containing only the findings that do not match any
        pattern, preserving the original order. If ``patterns`` is empty
        all findings are kept; if ``findings`` is empty an empty list is
        returned. Neither empty case raises.
    """
    return [finding for finding in findings if not any((matches(pattern, finding) for pattern in patterns))]