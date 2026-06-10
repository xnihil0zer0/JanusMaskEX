"""JSON-safe value codec for the JS differential runner (Phase B).

JS values that JSON cannot carry (``undefined``, ``NaN``, ``Infinity``,
``-Infinity``) cross the FD-3 boundary as ``{"__sentinel__": "<tag>"}``
objects, and the Python side compares results with Object.is-style semantics.
Pure, stdlib-only, no spawn.

Exposes:

- ``UNDEFINED`` -- a module-level singleton DISTINCT from ``None`` (JS
  ``undefined`` != ``null``).
- ``encode_value(obj)`` -- recursive: UNDEFINED => {'__sentinel__': 'undefined'},
  nan => 'NaN', +inf => 'Infinity', -inf => '-Infinity'; None/bool/int/str
  pass through; lists/tuples => lists; dicts recurse. The result is ALWAYS
  json.dumps-able with ``allow_nan=False``.
- ``decode_value(obj)`` -- exact inverse over the sentinel tags, recursing
  through lists/dicts; unknown tags decode to the dict shape-unchanged (never
  raise).
- ``values_equal(a, b) -> bool`` -- Object.is semantics: NaN equals NaN,
  ``0.0`` and ``-0.0`` are DIFFERENT, UNDEFINED equals only UNDEFINED (never
  None), deep equality through lists/dicts, total (never raises).
"""
from __future__ import annotations
import math
from typing import Any

class _Undefined:
    """Singleton standing in for JS ``undefined`` (distinct from ``None``)."""
    _instance: '_Undefined | None' = None

    def __new__(cls) -> '_Undefined':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return 'UNDEFINED'

    def __bool__(self) -> bool:
        return False
UNDEFINED = _Undefined()
_TAG_TO_VALUE = {'undefined': UNDEFINED, 'NaN': float('nan'), 'Infinity': float('inf'), '-Infinity': float('-inf')}

def encode_value(obj: Any) -> Any:
    """Recursively encode ``obj`` into a strictly JSON-safe structure."""
    if obj is UNDEFINED:
        return {'__sentinel__': 'undefined'}
    if isinstance(obj, float):
        if math.isnan(obj):
            return {'__sentinel__': 'NaN'}
        if obj == float('inf'):
            return {'__sentinel__': 'Infinity'}
        if obj == float('-inf'):
            return {'__sentinel__': '-Infinity'}
        return obj
    if isinstance(obj, dict):
        return {k: encode_value(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [encode_value(v) for v in obj]
    return obj

def decode_value(obj: Any) -> Any:
    """Exact inverse of :func:`encode_value` over the four sentinel tags."""
    if isinstance(obj, dict):
        if set(obj) == {'__sentinel__'} and obj['__sentinel__'] in _TAG_TO_VALUE:
            return _TAG_TO_VALUE[obj['__sentinel__']]
        return {k: decode_value(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [decode_value(v) for v in obj]
    return obj

def values_equal(a: Any, b: Any) -> bool:
    """Object.is-style deep equality; total (any exception yields ``False``)."""
    try:
        if a is UNDEFINED or b is UNDEFINED:
            return a is b
        if isinstance(a, float) and isinstance(b, float):
            if math.isnan(a) and math.isnan(b):
                return True
            if a == 0.0 and b == 0.0:
                return math.copysign(1.0, a) == math.copysign(1.0, b)
            return a == b
        if isinstance(a, dict) and isinstance(b, dict):
            if set(a) != set(b):
                return False
            return all((values_equal(a[k], b[k]) for k in a))
        if isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                return False
            return all((values_equal(x, y) for x, y in zip(a, b)))
        if isinstance(a, dict) or isinstance(b, dict):
            return False
        if isinstance(a, list) or isinstance(b, list):
            return False
        return bool(a == b) and type(a) is type(b)
    except Exception:
        return False