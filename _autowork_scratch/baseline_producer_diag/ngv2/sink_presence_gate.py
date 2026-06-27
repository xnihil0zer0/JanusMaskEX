"""ngv2/sink_presence_gate.py -- pure deterministic sink-presence gate.

Verifies that the cited vulnerable construct STILL EXISTS as LIVE code in the
target source (not merely inside a comment / string-literal / docstring) before
a NobleGreed "confirmed" verdict is allowed.

The primary function is PURE and deterministic: it operates ONLY on its two
string arguments -- no filesystem, network, clock, randomness, subprocess, MCP,
third-party import, or import of any sibling ngv2 leaf. Identical inputs always
produce byte-identical output, so the function is differential-fuzzable.

Importing ``verify_sink_present`` from this live module is the wiring contract
consumed by the NobleGreed verdict path: that path consults ``may_confirm`` and
refuses a "confirmed" verdict whenever it is False.
"""
from typing import Dict, List, Tuple, Union
_CODE = 'code'
_COMMENT = 'comment'
_STRING = 'string'
_STATUS_PRESENT = 'present'
_STATUS_PATCHED = 'patched_or_moved'

def _classify(source: str) -> List[str]:
    """Return a per-character region label list for ``source``.

    A lightweight string-level scan -- no real parser. It tracks ``#`` line
    comments and single/double/triple quoted string-literals (with backslash
    escapes). Everything else is live code. Opening and closing delimiters are
    labelled as part of their region.
    """
    labels: List[str] = []
    n = len(source)
    i = 0
    state = _CODE
    delim = ''
    triple = False
    while i < n:
        ch = source[i]
        if state == _CODE:
            if ch == '#':
                state = _COMMENT
                labels.append(_COMMENT)
                i += 1
            elif ch == '"' or ch == "'":
                if source[i:i + 3] == ch * 3:
                    delim = ch * 3
                    triple = True
                    state = _STRING
                    labels.extend([_STRING, _STRING, _STRING])
                    i += 3
                else:
                    delim = ch
                    triple = False
                    state = _STRING
                    labels.append(_STRING)
                    i += 1
            else:
                labels.append(_CODE)
                i += 1
        elif state == _COMMENT:
            labels.append(_COMMENT)
            if ch == '\n':
                state = _CODE
            i += 1
        elif ch == '\\':
            labels.append(_STRING)
            if i + 1 < n:
                labels.append(_STRING)
                i += 2
            else:
                i += 1
        elif triple and source[i:i + 3] == delim:
            labels.extend([_STRING, _STRING, _STRING])
            i += 3
            state = _CODE
            delim = ''
        elif not triple and ch == delim:
            labels.append(_STRING)
            i += 1
            state = _CODE
            delim = ''
        elif not triple and ch == '\n':
            labels.append(_STRING)
            state = _CODE
            delim = ''
            i += 1
        else:
            labels.append(_STRING)
            i += 1
    return labels

def _normalize(source: str, labels: List[str]) -> Tuple[str, List[str]]:
    """Drop insignificant whitespace, keeping a parallel region-label list."""
    chars: List[str] = []
    kept: List[str] = []
    for idx, ch in enumerate(source):
        if ch.isspace():
            continue
        chars.append(ch)
        kept.append(labels[idx])
    return (''.join(chars), kept)

def _strip_ws(text: str) -> str:
    return ''.join((ch for ch in text if not ch.isspace()))

def verify_sink_present(target_source: str, expected_signature: str) -> Dict[str, Union[bool, str]]:
    """Decide whether ``expected_signature`` occurs as LIVE code in ``target_source``.

    Returns a fixed-shape dict::

        {present: bool,
         status: 'present' | 'patched_or_moved',
         in_comment_only: bool,
         may_confirm: bool}

    Invariants: ``status == 'present'`` iff ``present`` (else ``'patched_or_moved'``)
    and ``may_confirm == present``. A signature whose every occurrence sits wholly
    inside a comment / string-literal / docstring is NOT live. Insignificant
    whitespace and indentation are normalized away before matching.
    """
    labels = _classify(target_source)
    norm_source, norm_labels = _normalize(target_source, labels)
    norm_sig = _strip_ws(expected_signature)
    found_live = False
    found_non_live = False
    if norm_sig:
        length = len(norm_sig)
        start = 0
        while True:
            idx = norm_source.find(norm_sig, start)
            if idx == -1:
                break
            span = set(norm_labels[idx:idx + length])
            if span <= {_COMMENT} or span <= {_STRING}:
                found_non_live = True
            else:
                found_live = True
            start = idx + 1
    if found_live:
        present = True
        in_comment_only = False
    elif found_non_live:
        present = False
        in_comment_only = True
    else:
        present = False
        in_comment_only = False
    status = _STATUS_PRESENT if present else _STATUS_PATCHED
    return {'present': present, 'status': status, 'in_comment_only': in_comment_only, 'may_confirm': present}