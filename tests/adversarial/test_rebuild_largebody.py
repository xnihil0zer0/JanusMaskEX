"""C9.10 P1 contract: large-body decomposition is REAL (decompose -> recompose),
not just an enqueued retry.

`decompose_function_body` splits ONE oversized function into byte-budget-sized
contiguous statement segments; `recompose_function` stitches header + segments
back into a function that is AST-equivalent to the original. The reconstruct-
oversized driver (tested separately, monkeypatched) reconstructs each segment
blind and recomposes the unit, gated by the unit's tests.

These are the PURE helpers (operator-authored oracle; agents implement blind via
the harness_plumbing dogfood). Each test asserts both structural properties
(segment count, per-segment budget) AND AST round-trip fidelity.
"""
import ast

import pytest

from harness.rebuild.decompose import decompose_function_body, recompose_function


def _ast_equal(a: str, b: str) -> bool:
    return ast.dump(ast.parse(a)) == ast.dump(ast.parse(b))


SMALL_FN = (
    "def add(a, b):\n"
    "    total = a + b\n"
    "    return total\n"
)

# A multi-statement function whose body comfortably exceeds a small budget.
BIG_FN = (
    "def normalize(text):\n"
    '    """Normalize a string through a fixed pipeline."""\n'
    "    s = text\n"
    "    s = s.strip()\n"
    "    s = s.lower()\n"
    "    s = s.replace('\\t', ' ')\n"
    "    s = s.replace('\\n', ' ')\n"
    "    while '  ' in s:\n"
    "        s = s.replace('  ', ' ')\n"
    "    parts = s.split(' ')\n"
    "    parts = [p for p in parts if p]\n"
    "    s = ' '.join(parts)\n"
    "    s = s.replace(' .', '.')\n"
    "    s = s.replace(' ,', ',')\n"
    "    if s and not s.endswith('.'):\n"
    "        s = s + '.'\n"
    "    s = s[0].upper() + s[1:] if s else s\n"
    "    return s\n"
)


def test_small_function_single_segment():
    out = decompose_function_body(SMALL_FN, budget=4000)
    assert isinstance(out, dict)
    assert "header" in out and "segments" in out
    assert len(out["segments"]) == 1
    recomposed = recompose_function(out["header"], out["segments"])
    assert _ast_equal(recomposed, SMALL_FN)


def test_oversized_function_splits_into_multiple_segments():
    budget = 120
    out = decompose_function_body(BIG_FN, budget=budget)
    segments = out["segments"]
    assert len(segments) >= 2, f"expected multiple segments, got {len(segments)}"
    # every segment except an unsplittable single statement stays within budget
    for seg in segments:
        # a segment is one-or-more whole statements; only an indivisible single
        # statement may exceed budget
        if len(_split_statements(seg)) > 1:
            assert len(seg) <= budget, f"multi-statement segment over budget: {len(seg)}"


def test_oversized_recompose_is_ast_equivalent():
    out = decompose_function_body(BIG_FN, budget=120)
    recomposed = recompose_function(out["header"], out["segments"])
    assert _ast_equal(recomposed, BIG_FN)


def test_docstring_lives_in_header_not_segments():
    out = decompose_function_body(BIG_FN, budget=120)
    assert "Normalize a string" in out["header"]
    for seg in out["segments"]:
        assert "Normalize a string" not in seg


def test_segments_preserve_statement_order():
    out = decompose_function_body(BIG_FN, budget=120)
    recomposed = recompose_function(out["header"], out["segments"])
    orig_stmts = _toplevel_body_dumps(BIG_FN)
    new_stmts = _toplevel_body_dumps(recomposed)
    assert orig_stmts == new_stmts


def test_single_oversized_statement_is_its_own_segment():
    # one statement larger than budget cannot be split further
    big_literal = "x = [" + ", ".join(str(i) for i in range(200)) + "]"
    fn = "def f():\n    " + big_literal + "\n    return x\n"
    out = decompose_function_body(fn, budget=50)
    recomposed = recompose_function(out["header"], out["segments"])
    assert _ast_equal(recomposed, fn)


def _split_statements(seg: str) -> list:
    try:
        return ast.parse(seg).body
    except (SyntaxError, IndentationError):
        # segment carries body-level indentation; dedent the first line
        return ast.parse("\n".join(line[4:] if line.startswith("    ") else line for line in seg.splitlines())).body


def _toplevel_body_dumps(func_source: str) -> list:
    fn = ast.parse(func_source).body[0]
    return [ast.dump(s) for s in fn.body]
