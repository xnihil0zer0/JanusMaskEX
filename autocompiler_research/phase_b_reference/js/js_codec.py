"""JSON-safe value codec for the JS differential runner (Phase B, ac-js-codec).

JS values JSON cannot carry (``undefined``, ``NaN``, ``±Infinity``) cross the
FD-3 boundary as ``{"__sentinel__": tag}`` objects; comparison follows
Object.is semantics (NaN equals NaN, signed zeros differ, undefined != null).
Pure, stdlib-only, total.
"""
from __future__ import annotations

import math


class _Undefined:
    """Singleton standing in for JS ``undefined`` (DISTINCT from ``None``)."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self):
        return 'UNDEFINED'

    def __bool__(self):
        return False


UNDEFINED = _Undefined()

_TAG_TO_VALUE = {
    'undefined': UNDEFINED,
    'NaN': float('nan'),
    'Infinity': float('inf'),
    '-Infinity': float('-inf'),
}


def encode_value(obj):
    """Recursively encode *obj* into a strictly JSON-safe structure."""
    if obj is UNDEFINED:
        return {'__sentinel__': 'undefined'}
    if isinstance(obj, float):
        if math.isnan(obj):
            return {'__sentinel__': 'NaN'}
        if math.isinf(obj):
            return {'__sentinel__': 'Infinity' if obj > 0 else '-Infinity'}
        return obj
    if isinstance(obj, dict):
        return {k: encode_value(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [encode_value(v) for v in obj]
    return obj


def decode_value(obj):
    """Exact inverse of :func:`encode_value` over the sentinel tags."""
    if isinstance(obj, dict):
        if set(obj) == {'__sentinel__'} and obj['__sentinel__'] in _TAG_TO_VALUE:
            return _TAG_TO_VALUE[obj['__sentinel__']]
        return {k: decode_value(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [decode_value(v) for v in obj]
    return obj


def values_equal(a, b) -> bool:
    """Object.is-style deep equality: NaN==NaN, +0!=-0, UNDEFINED!=None."""
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
            return set(a) == set(b) and all(values_equal(a[k], b[k]) for k in a)
        if isinstance(a, list) and isinstance(b, list):
            return len(a) == len(b) and all(values_equal(x, y) for x, y in zip(a, b))
        if type(a) is not type(b):
            return False
        return a == b
    except Exception:
        return False
