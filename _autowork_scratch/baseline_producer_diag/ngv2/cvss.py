"""Deterministic, pure, stdlib-only CVSS v3.1 utilities.

This module parses CVSS v3.1 vector strings, computes the CVSS v3.1 base
score exactly per the official specification arithmetic, and maps a numeric
base score to its qualitative severity rating.

All functions are pure and deterministic: no file or network I/O, no third
party imports, and no mutation of module-level state.
"""
from __future__ import annotations
import math
from typing import Dict, Mapping, Union
__all__ = ['parse_vector', 'base_score', 'severity_label']
_AV = {'N': 0.85, 'A': 0.62, 'L': 0.55, 'P': 0.2}
_AC = {'L': 0.77, 'H': 0.44}
_UI = {'N': 0.85, 'R': 0.62}
_PR_UNCHANGED = {'N': 0.85, 'L': 0.62, 'H': 0.27}
_PR_CHANGED = {'N': 0.85, 'L': 0.68, 'H': 0.5}
_CIA = {'H': 0.56, 'M': 0.22, 'L': 0.22, 'N': 0.0}
_ALLOWED_VALUES: Dict[str, frozenset] = {'AV': frozenset({'N', 'A', 'L', 'P'}), 'AC': frozenset({'L', 'H'}), 'PR': frozenset({'N', 'L', 'H'}), 'UI': frozenset({'N', 'R'}), 'S': frozenset({'U', 'C'}), 'C': frozenset({'H', 'L', 'N'}), 'I': frozenset({'H', 'L', 'N'}), 'A': frozenset({'H', 'L', 'N'})}
_REQUIRED_BASE_METRICS = ('AV', 'AC', 'PR', 'UI', 'S', 'C', 'I', 'A')

def parse_vector(vector: str) -> Dict[str, str]:
    """Parse a CVSS v3.1 vector string into its base metric components.

    Accepts vectors with or without the leading ``CVSS:3.1`` prefix segment.
    When the prefix is present it must declare version ``3.1``.

    Returns a mapping of metric abbreviation -> value for every base metric.

    Raises ``ValueError`` for any malformed input: bad prefix/version,
    missing required base metric, unknown metric key, invalid metric value,
    or a duplicated metric.
    """
    if not isinstance(vector, str):
        raise ValueError('vector must be a string')
    text = vector.strip()
    if not text:
        raise ValueError('empty CVSS vector string')
    segments = text.split('/')
    first = segments[0]
    if first.upper().startswith('CVSS:'):
        version = first.split(':', 1)[1]
        if version != '3.1':
            raise ValueError('unsupported CVSS version: %r' % version)
        segments = segments[1:]
    if not segments:
        raise ValueError('CVSS vector contains no metrics')
    metrics: Dict[str, str] = {}
    for segment in segments:
        if not segment:
            raise ValueError('empty metric segment in CVSS vector')
        if ':' not in segment:
            raise ValueError('malformed metric segment: %r' % segment)
        key, _, value = segment.partition(':')
        if not key or not value:
            raise ValueError('malformed metric segment: %r' % segment)
        if key in metrics:
            raise ValueError('duplicate metric: %r' % key)
        metrics[key] = value
    for key in _REQUIRED_BASE_METRICS:
        if key not in metrics:
            raise ValueError('missing required base metric: %r' % key)
        if metrics[key] not in _ALLOWED_VALUES[key]:
            raise ValueError('invalid value %r for metric %r' % (metrics[key], key))
    for key, value in metrics.items():
        if key not in _ALLOWED_VALUES:
            raise ValueError('unknown metric key: %r' % key)
        if value not in _ALLOWED_VALUES[key]:
            raise ValueError('invalid value %r for metric %r' % (value, key))
    return metrics

def _roundup(value: float) -> float:
    """CVSS v3.1 spec Roundup: round half up to one decimal place using
    integer arithmetic to avoid float-precision divergence."""
    int_input = int(round(value * 100000))
    if int_input % 10000 == 0:
        return int_input / 100000.0
    return (math.floor(int_input / 10000.0) + 1) / 10.0

def base_score(vector: Union[str, Mapping[str, str]]) -> float:
    """Compute the CVSS v3.1 base score for a vector string or parsed mapping.

    Returns a float rounded to one decimal place per the spec Roundup.
    """
    if isinstance(vector, str):
        metrics = parse_vector(vector)
    else:
        metrics = dict(vector)
        for key in _REQUIRED_BASE_METRICS:
            if key not in metrics:
                raise ValueError('missing required base metric: %r' % key)
            if metrics[key] not in _ALLOWED_VALUES[key]:
                raise ValueError('invalid value %r for metric %r' % (metrics[key], key))
    scope_changed = metrics['S'] == 'C'
    isc_base = 1.0 - (1.0 - _CIA[metrics['C']]) * (1.0 - _CIA[metrics['I']]) * (1.0 - _CIA[metrics['A']])
    if scope_changed:
        impact = 7.52 * (isc_base - 0.029) - 3.25 * (isc_base - 0.02) ** 15
    else:
        impact = 6.42 * isc_base
    if impact <= 0:
        return 0.0
    pr_table = _PR_CHANGED if scope_changed else _PR_UNCHANGED
    exploitability = 8.22 * _AV[metrics['AV']] * _AC[metrics['AC']] * pr_table[metrics['PR']] * _UI[metrics['UI']]
    if scope_changed:
        return _roundup(min(1.08 * (impact + exploitability), 10.0))
    return _roundup(min(impact + exploitability, 10.0))

def severity_label(score: float) -> str:
    """Map a numeric CVSS v3.1 base score to its qualitative rating."""
    if score < 0.0 or score > 10.0:
        raise ValueError('score out of range [0.0, 10.0]: %r' % score)
    if score == 0.0:
        return 'NONE'
    if score < 4.0:
        return 'LOW'
    if score < 7.0:
        return 'MEDIUM'
    if score < 9.0:
        return 'HIGH'
    return 'CRITICAL'