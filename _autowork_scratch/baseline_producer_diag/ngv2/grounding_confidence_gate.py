"""ngv2/grounding_confidence_gate.py

Pure, deterministic, stdlib-only confidence gate classifier.

Ports the legacy grounding.py confidence algorithm to classify a finding into
one of four confidence tiers based on a list of tool signals.

The function ``compute_confidence`` is total and exception-safe: any malformed
input (missing keys, wrong types, non-dict signals, etc.) is handled gracefully
and never raises. It performs no I/O, database, network, LLM, wall-clock, or
subprocess calls and uses no randomness, so identical inputs always produce the
identical output.
"""
from __future__ import annotations
from typing import Any, Dict, List, Set
CONFIRMED: str = 'CONFIRMED'
HIGH: str = 'HIGH'
MEDIUM: str = 'MEDIUM'
LOW: str = 'LOW'
_PROOF_KINDS: frozenset = frozenset({'taint_flow', 'formal_path', 'live_poc'})

def _get(signal: Any, field_name: str) -> Any:
    """Safely read ``field_name`` from a signal that should be a mapping.

    Returns ``None`` for non-mapping signals or missing fields instead of
    raising, keeping the classifier total over malformed inputs.
    """
    if isinstance(signal, dict):
        return signal.get(field_name)
    getter = getattr(signal, 'get', None)
    if callable(getter):
        try:
            return getter(field_name)
        except Exception:
            return None
    return None

def _is_known_fp(signal: Any) -> bool:
    """A signal is a known false-positive match if it reports ``known_fp`` or is
    an ``fp_filter`` kind that matched."""
    result = _get(signal, 'result')
    if result == 'known_fp':
        return True
    if _get(signal, 'kind') == 'fp_filter' and result == 'match':
        return True
    return False

def _is_structural_proof(signal: Any) -> bool:
    """A signal is a structural proof when its kind is one of the proof kinds
    and its result is ``proof``."""
    return _get(signal, 'kind') in _PROOF_KINDS and _get(signal, 'result') == 'proof'

def compute_confidence(finding: Dict[str, Any], signals: List[Any]) -> str:
    """Classify a finding into a confidence tier from its tool signals.

    Tiers (highest wins), evaluated in this exact priority order:

      1. ``LOW``       -- if ANY signal is a known-FP match (result == 'known_fp',
                          or kind == 'fp_filter' with result == 'match').
                          Known-FP dominates everything else.
      2. ``CONFIRMED`` -- if no known-FP and ANY signal is a structural proof
                          (kind in {taint_flow, formal_path, live_poc} and
                          result == 'proof').
      3. ``HIGH``      -- if no known-FP and >= 2 distinct tools each produced a
                          'match' result.
      4. ``MEDIUM``    -- if no known-FP and exactly one signal has result
                          == 'match'.
      5. ``LOW``       -- default (empty signals, or no matches/proofs).

    The ``finding`` argument is accepted for interface compatibility; the tier
    is derived purely from ``signals``. The function is deterministic and never
    raises on malformed input.
    """
    if isinstance(signals, (list, tuple)):
        signal_list: List[Any] = list(signals)
    elif signals is None:
        signal_list = []
    else:
        try:
            signal_list = list(signals)
        except Exception:
            signal_list = []
    has_known_fp = False
    has_proof = False
    matching_tools: Set[Any] = set()
    match_count = 0
    for signal in signal_list:
        if _is_known_fp(signal):
            has_known_fp = True
        if _is_structural_proof(signal):
            has_proof = True
        if _get(signal, 'result') == 'match':
            match_count += 1
            tool = _get(signal, 'tool')
            try:
                matching_tools.add(tool)
            except TypeError:
                matching_tools.add(repr(tool))
    if has_known_fp:
        return LOW
    if has_proof:
        return CONFIRMED
    if len(matching_tools) >= 2:
        return HIGH
    if match_count == 1:
        return MEDIUM
    return LOW