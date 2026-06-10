"""Post-decode schema validation + truncation repair (Phase B, ac-decode-validator).

JM has no in-process model SDK (every model call is a CLI subprocess consumed
as NDJSON), so "constrained decoding" is realized AFTER the fact: validate the
emitted submission text against the reasoning-field-first payload schema and
repair token-limit truncation instead of discarding the draft. Pure,
stdlib-only, total over any ``str`` input.
"""
from __future__ import annotations

import json
from typing import Any

_RESULT_KEYS = ('ok', 'payload', 'repaired', 'dropped_edits', 'reason')


def _result(ok: bool, payload=None, repaired: bool=False, dropped: int=0, reason: str='') -> dict:
    return {'ok': ok, 'payload': payload, 'repaired': repaired,
            'dropped_edits': dropped, 'reason': reason}


def _strip_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith('```'):
        first_nl = text.find('\n')
        if first_nl != -1:
            text = text[first_nl + 1:]
        if text.rstrip().endswith('```'):
            text = text.rstrip()[:-3]
    return text.strip()


def _complete_edit(entry: Any) -> bool:
    return (isinstance(entry, dict)
            and isinstance(entry.get('file'), str) and entry['file']
            and isinstance(entry.get('code'), str))


def _repair_truncated(text: str) -> Any:
    """Best-effort recovery of a truncated JSON object: retry parsing ever
    shorter prefixes with the open string/bracket tail closed."""
    for cut in range(len(text), 0, -1):
        prefix = text[:cut]
        in_str = False
        escape = False
        stack = []
        for ch in prefix:
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = in_str
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch in '{[':
                stack.append(ch)
            elif ch in '}]':
                if stack:
                    stack.pop()
        candidate = prefix.rstrip()
        if in_str:
            candidate += '"'
        candidate = candidate.rstrip()
        if candidate.endswith((',', ':')):
            candidate = candidate[:-1]
        for opener in reversed(stack):
            candidate += ']' if opener == '[' else '}'
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return None


def _validate(payload: Any, repaired: bool) -> dict:
    if not isinstance(payload, dict):
        return _result(False, reason='payload is not a JSON object')
    reasoning = payload.get('reasoning')
    if not isinstance(reasoning, str):
        return _result(False, reason='missing or non-string reasoning field')
    edits = payload.get('edits')
    if not isinstance(edits, list):
        return _result(False, reason='missing or non-list edits field')
    kept = [e for e in edits if _complete_edit(e)]
    dropped = len(edits) - len(kept)
    return _result(True, {'reasoning': reasoning, 'edits': kept},
                   repaired=repaired, dropped=dropped)


def decode_submission(raw: str) -> dict:
    """Total post-decode validator: parse (repairing truncation), enforce the
    reasoning-first schema, drop incomplete edits. NEVER raises."""
    try:
        if not isinstance(raw, str) or not raw.strip():
            return _result(False, reason='empty submission')
        text = _strip_fence(raw)
        repaired = False
        try:
            payload = json.loads(text)
        except Exception:
            payload = _repair_truncated(text)
            if payload is None:
                return _result(False, reason='unparseable submission (not JSON, repair failed)')
            repaired = True
        out = _validate(payload, repaired)
        if out['ok'] and repaired and out['dropped_edits'] == 0:
            # A repaired document lost at least its torn tail; reflect that the
            # recovery was lossy even when every surviving edit is complete.
            out['dropped_edits'] = 1
        return out
    except Exception as exc:  # totality backstop
        return _result(False, reason=f'internal decode error: {exc}')
