"""Operator behavioural pins for the clean-room rebuild of rebuild/decompose.py.

``decompose_function_body`` / ``recompose_function`` are oracle-USABLE (fully
typed) but their merged==original fuzz is VACUOUS: the meaningful domain is
*valid Python function source* + a matching header/segments pair, which random
fuzz strings never produce (they ``SyntaxError`` on both bodies, so the oracle is
trivially satisfied). These per-unit-named pins (derived from + verified against
the real original) gate the reconstruction. C9.17c LAW.
"""

import ast

from harness.rebuild.decompose import decompose_function_body, recompose_function

_SRC = (
    "def f(x):\n"
    '    """doc"""\n'
    "    a = x + 1\n"
    "    b = a * 2\n"
    "    return b\n"
)


def test_decompose_function_body_keeps_docstring_in_header():
    out = decompose_function_body(_SRC, 10000)
    assert out["header"] == 'def f(x):\n    """doc"""'
    # Budget large enough -> all real statements in one contiguous segment.
    assert out["segments"] == ["    a = x + 1\n    b = a * 2\n    return b"]


def test_decompose_function_body_splits_to_budget():
    out = decompose_function_body(_SRC, 20)
    assert out["segments"] == [
        "    a = x + 1",
        "    b = a * 2",
        "    return b",
    ]


def test_decompose_function_body_raises_without_function():
    try:
        decompose_function_body("x = 1\n", 100)
    except ValueError:
        return
    raise AssertionError("expected ValueError when no function definition")


def test_recompose_function_skips_empty_segments():
    assert recompose_function("h", ["", "a", ""]) == "h\na"


def test_recompose_function_round_trips_decompose():
    out = decompose_function_body(_SRC, 10000)
    rebuilt = recompose_function(out["header"], out["segments"])
    assert ast.dump(ast.parse(rebuilt)) == ast.dump(ast.parse(_SRC))
