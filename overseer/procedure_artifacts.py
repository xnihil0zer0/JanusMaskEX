"""overseer/procedure_artifacts.py -- parse procedure artifact/attestation markers.

The overseer agent emits structured markers in its turn text so the procedure
FSM's backed gates can auto-verify:

    __PROCEDURE_ARTIFACT__ {"oracle_path": "tests/overseer/test_x.py"}
    __PROCEDURE_ATTEST__ {"phase": "SCOPE"}

This module extracts those markers and merges them into the conversation record
(rec['procedure_artifacts'] / rec['procedure_attested']). Stdlib only; no I/O.
"""
from __future__ import annotations
import json
from typing import Dict, List
_ARTIFACT = '__PROCEDURE_ARTIFACT__'
_ATTEST = '__PROCEDURE_ATTEST__'
_DECODER = json.JSONDecoder()

def _scan(text: str, marker: str) -> List[dict]:
    """Yield each JSON object following an occurrence of marker in text."""
    out: List[dict] = []
    pos = 0
    while True:
        i = text.find(marker, pos)
        if i == -1:
            break
        j = text.find('{', i)
        if j == -1:
            break
        try:
            obj, end = _DECODER.raw_decode(text[j:])
        except ValueError:
            pos = i + len(marker)
            continue
        if isinstance(obj, dict):
            out.append(obj)
        pos = j + end
    return out

def merge_artifacts(existing: Dict, new: Dict) -> Dict:
    """Merge new into existing without mutating either: keys ending in '_paths'
    union (de-duped, order-preserving) list values; all other keys later-wins."""
    out = dict(existing or {})
    for k, v in (new or {}).items():
        if k.endswith('_paths') and isinstance(v, list):
            cur = list(out.get(k, []))
            for item in v:
                if item not in cur:
                    cur.append(item)
            out[k] = cur
        else:
            out[k] = v
    return out

def parse_artifacts(text: str) -> Dict:
    """Return the merged artifacts declared by all markers in text."""
    merged: Dict = {}
    for obj in _scan(text or '', _ARTIFACT):
        merged = merge_artifacts(merged, obj)
    return merged

def parse_attestations(text: str) -> List[str]:
    """Return the ordered, de-duped list of phase names attested in text."""
    phases: List[str] = []
    for obj in _scan(text or '', _ATTEST):
        ph = obj.get('phase')
        if isinstance(ph, str) and ph and (ph not in phases):
            phases.append(ph)
    return phases

def apply_to_record(rec: Dict, text: str) -> Dict:
    """Merge markers found in text into rec in place; return rec."""
    arts = parse_artifacts(text)
    if arts:
        rec['procedure_artifacts'] = merge_artifacts(rec.get('procedure_artifacts') or {}, arts)
    att = parse_attestations(text)
    if att:
        cur = dict(rec.get('procedure_attested') or {})
        for ph in att:
            cur[ph] = True
        rec['procedure_attested'] = cur
    return rec