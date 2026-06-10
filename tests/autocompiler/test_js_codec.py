"""RED oracle — authoritative contract for autocompiler/js/js_codec.py (leaf ac-js-codec).

Contract: the JSON-safe value codec for the JS differential runner. JS values
that JSON cannot carry (``undefined``, ``NaN``, ``Infinity``, ``-Infinity``)
cross the FD-3 boundary as ``{"__sentinel__": "<tag>"}`` objects, and the
Python side compares results with Object.is-style semantics. Pure, stdlib-only,
no spawn. Exposes:

- ``UNDEFINED`` — a module-level singleton DISTINCT from ``None`` (JS
  ``undefined`` != ``null``).
- ``encode_value(obj)`` — recursive: UNDEFINED => {'__sentinel__':'undefined'},
  nan => 'NaN', +inf => 'Infinity', -inf => '-Infinity'; None/bool/int/str
  pass through; lists/dicts recurse. The result is ALWAYS json.dumps-able with
  ``allow_nan=False``.
- ``decode_value(obj)`` — exact inverse over the sentinel tags, recursing
  through lists/dicts; unknown tags decode to the dict unchanged-shape (never
  raise).
- ``values_equal(a, b) -> bool`` — Object.is semantics: NaN equals NaN,
  ``0.0`` and ``-0.0`` are DIFFERENT, UNDEFINED equals only UNDEFINED (never
  None), deep equality through lists/dicts.
"""
import json
import math

import pytest

from autocompiler.js.js_codec import UNDEFINED, decode_value, encode_value, values_equal


def test_undefined_is_a_distinct_singleton():
    assert UNDEFINED is not None
    assert (UNDEFINED == None) is False  # noqa: E711 — pinning JS undefined != null


def test_encode_specials_to_sentinels():
    assert encode_value(UNDEFINED) == {'__sentinel__': 'undefined'}
    assert encode_value(float('nan')) == {'__sentinel__': 'NaN'}
    assert encode_value(float('inf')) == {'__sentinel__': 'Infinity'}
    assert encode_value(float('-inf')) == {'__sentinel__': '-Infinity'}
    assert encode_value(None) is None


def test_encoded_output_is_strict_json_safe():
    payload = encode_value([float('nan'), {'a': UNDEFINED, 'b': [float('inf'), None, 1.5]}])
    json.dumps(payload, allow_nan=False)  # must not raise


def test_round_trip_nested_structures():
    original = [float('nan'), {'u': UNDEFINED, 'n': None, 'xs': [float('-inf'), 'txt', 3]}]
    back = decode_value(encode_value(original))
    assert math.isnan(back[0])
    assert back[1]['u'] is UNDEFINED
    assert back[1]['n'] is None
    assert back[1]['xs'][0] == float('-inf')
    assert back[1]['xs'][1:] == ['txt', 3]


def test_decode_plain_values_pass_through():
    assert decode_value({'k': [1, 'a', True, None]}) == {'k': [1, 'a', True, None]}


def test_values_equal_object_is_semantics():
    assert values_equal(float('nan'), float('nan')) is True
    assert values_equal(0.0, -0.0) is False        # edge case: signed zero
    assert values_equal(-0.0, -0.0) is True
    assert values_equal(UNDEFINED, UNDEFINED) is True
    assert values_equal(UNDEFINED, None) is False  # edge case: undefined != null
    assert values_equal(1, 2) is False
    assert values_equal('x', 'x') is True


def test_values_equal_deep():
    a = [float('nan'), {'u': UNDEFINED, 'v': [1, 2]}]
    b = [float('nan'), {'u': UNDEFINED, 'v': [1, 2]}]
    assert values_equal(a, b) is True
    assert values_equal(a, [float('nan'), {'u': None, 'v': [1, 2]}]) is False
    assert values_equal([1], [1, 2]) is False


def test_codec_is_total_over_garbage():
    # Property: encode/decode never raise on odd-but-JSONish shapes.
    for obj in ({}, [], '', 0, False, {'__sentinel__': 'not-a-real-tag'}, [[[]]]):
        decode_value(obj)
        json.dumps(encode_value(obj), allow_nan=False)
