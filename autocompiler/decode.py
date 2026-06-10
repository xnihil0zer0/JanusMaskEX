"""Autocompiler post-decode schema validator + truncation repair.

JM has NO in-process model SDK, so "constrained decoding" is realized as
POST-DECODE validation: the emitted submission text is checked against the
reasoning-field-first payload schema and token-limit truncation is repaired
instead of discarding the draft.

The module exposes ``decode_submission(raw: str) -> dict`` which is TOTAL:
it never raises for any ``str`` input and always returns a dict with EXACTLY
the keys ``ok``, ``payload``, ``repaired``, ``dropped_edits``, ``reason``.
"""
from __future__ import annotations
import json
from typing import Any, Dict, List, Optional, Tuple
_RESULT_KEYS = ('ok', 'payload', 'repaired', 'dropped_edits', 'reason')

def _result(ok: bool, payload: Optional[Dict[str, Any]]=None, repaired: bool=False, dropped_edits: int=0, reason: str='') -> Dict[str, Any]:
    """Construct a result with the invariant key set."""
    return {'ok': ok, 'payload': payload, 'repaired': repaired, 'dropped_edits': dropped_edits, 'reason': reason}

def _strip_fence(text: str) -> str:
    """Strip a leading ```json (or bare ```) fence and a trailing ``` fence."""
    stripped = text.strip()
    if not stripped.startswith('```'):
        return stripped
    lines = stripped.splitlines()
    lines = lines[1:]
    if lines and lines[-1].strip().startswith('```'):
        lines = lines[:-1]
    return '\n'.join(lines).strip()

def _complete_edit(edit: Any) -> bool:
    """An edit is complete iff it is a dict with non-empty str file and str code."""
    return isinstance(edit, dict) and isinstance(edit.get('file'), str) and (edit.get('file') != '') and isinstance(edit.get('code'), str)

def _repair_truncated(text: str) -> Optional[Any]:
    """Repair a torn document by closing strings/brackets over shrinking prefixes.

    Iterate prefixes ``text[:cut]`` from the full length down to 1; for each,
    track ``in_string``/``escape`` and a bracket stack while scanning, close an
    open string with a trailing quote, strip a trailing ',' or ':', append the
    matching closers for the remaining stack in reverse, and return the first
    prefix that ``json.loads`` accepts. Return ``None`` if none parse.
    """
    closers = {'{': '}', '[': ']'}
    for cut in range(len(text), 0, -1):
        prefix = text[:cut]
        in_string = False
        escape = False
        stack: List[str] = []
        for ch in prefix:
            if escape:
                escape = False
                continue
            if in_string:
                if ch == '\\':
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch in '{[':
                stack.append(ch)
            elif ch == '}':
                if stack and stack[-1] == '{':
                    stack.pop()
            elif ch == ']':
                if stack and stack[-1] == '[':
                    stack.pop()
        repaired = prefix
        if in_string:
            repaired += '"'
        repaired = repaired.rstrip()
        if repaired and repaired[-1] in ',:':
            repaired = repaired[:-1].rstrip()
        for opener in reversed(stack):
            repaired += closers[opener]
        try:
            return json.loads(repaired)
        except (json.JSONDecodeError, ValueError):
            continue
    return None

def _validate(payload: Any) -> Tuple[bool, Optional[Dict[str, Any]], int, str]:
    """Enforce the reasoning-first schema; filter to complete edits.

    Returns ``(ok, payload, dropped_edits, reason)``.
    """
    if not isinstance(payload, dict):
        return (False, None, 0, 'payload is not a JSON object')
    reasoning = payload.get('reasoning')
    if not isinstance(reasoning, str):
        return (False, None, 0, 'missing or non-string reasoning field')
    edits = payload.get('edits')
    if not isinstance(edits, list):
        return (False, None, 0, 'missing or non-list edits field')
    kept = [e for e in edits if _complete_edit(e)]
    dropped = len(edits) - len(kept)
    return (True, {'reasoning': reasoning, 'edits': kept}, dropped, '')

def decode_submission(raw: str) -> Dict[str, Any]:
    """Validate and repair an emitted submission, total over any str input."""
    try:
        if not isinstance(raw, str) or not raw.strip():
            return _result(False, reason='empty submission')
        text = _strip_fence(raw)
        repaired = False
        try:
            parsed: Any = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            parsed = _repair_truncated(text)
            if parsed is None:
                return _result(False, reason='unparseable submission (not JSON, repair failed)')
            repaired = True
        ok, payload, dropped, reason = _validate(parsed)
        if not ok:
            return _result(False, reason=reason)
        if repaired and dropped == 0:
            dropped = 1
        return _result(True, payload=payload, repaired=repaired, dropped_edits=dropped)
    except Exception as exc:
        return _result(False, reason='internal decode error: {}'.format(exc))