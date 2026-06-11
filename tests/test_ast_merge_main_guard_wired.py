"""RED oracle: ``_ast_merge`` must treat the module-level
``if __name__ == "__main__":`` guard as a MERGEABLE keyed unit.

THE BUG (blocked the NGv2 cfix-mcp-main fix): ``_ast_merge(output_code,
target_code)`` in ``harness/git_integration.py`` merges top-level nodes
keyed by the nested ``_node_key`` (def/class wholesale-replace;
import/assign/AnnAssign keyed). A module-level ``if __name__ ==
"__main__":`` guard is an ``ast.If`` for which ``_node_key`` returns
None, and the candidate-side collection loop EXPLICITLY drops it
(``if _is_main_guard(node): continue``). So on a whole-file submission
to an EXISTING .py file the candidate's ``__main__`` block is silently
DISCARDED and the target's OLD ``__main__`` survives. Consequence: a
module's ``__main__`` block cannot be edited through the pipeline at
all (not symbol-patchable -- it is unnamed; not merged -- dropped; no
region sentinels).

THE CONTRACT this oracle pins (candidate-wins, omitted=>preserved --
identical to the def/class symbol semantics):
  * candidate WITH a ``__main__`` guard + target WITH one  => the
    candidate's guard REPLACES the target's WHOLESALE (old body gone);
  * candidate WITHOUT a guard + target WITH one            => the
    target's guard is preserved VERBATIM (omitted => preserved);
  * candidate WITH a guard + target WITHOUT one            => the
    candidate's guard is ADDED;
  * the reversed comparison form (``"__main__" == __name__``) is
    recognized the same as the canonical form;
  * inputs with NO ``__main__`` guard anywhere merge exactly as before
    (regression pin).

RED today: the replace / reversed-form / add cases fail because the
candidate's guard is dropped. The preserve and no-guard-regression
cases pass today and must keep passing after the fix.
"""
from __future__ import annotations

import ast

import pytest

from harness.git_integration import _ast_merge


def _is_module_main_guard(node) -> bool:
    """True for a top-level ``if __name__ == "__main__":`` (either
    operand order) -- mirror of the merge's structural match."""
    if not isinstance(node, ast.If):
        return False
    t = node.test
    if not isinstance(t, ast.Compare):
        return False
    if len(t.ops) != 1 or len(t.comparators) != 1:
        return False
    if not isinstance(t.ops[0], ast.Eq):
        return False
    sides = (t.left, t.comparators[0])
    has_name = any(isinstance(s, ast.Name) and s.id == "__name__" for s in sides)
    has_const = any(
        isinstance(s, ast.Constant) and s.value == "__main__" for s in sides
    )
    return has_name and has_const


def _main_guards(src: str) -> list:
    return [n for n in ast.parse(src).body if _is_module_main_guard(n)]


def _sole_guard_body_src(src: str) -> str:
    """Unparsed body of the module's single ``__main__`` guard; asserts
    exactly one guard exists (zero guards => loud failure, which is the
    RED signal for the add case)."""
    guards = _main_guards(src)
    assert len(guards) == 1, (
        "expected exactly one module __main__ guard, found %d in:\n%s"
        % (len(guards), src)
    )
    return "\n".join(ast.unparse(stmt) for stmt in guards[0].body)


# ---------------------------------------------------------------------------
# 1. REPLACE: candidate's __main__ guard wholesale-replaces the target's.
#    (The exact NGv2 cfix-mcp-main shape: new guard body must WIN.)
# ---------------------------------------------------------------------------

def test_candidate_main_guard_replaces_targets():
    target = (
        "def main():\n"
        "    return 1\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    x = 1\n"
        "    main()\n"
    )
    candidate = (
        'if __name__ == "__main__":\n'
        "    x = 2\n"
    )
    merged = _ast_merge(candidate, target)
    body = _sole_guard_body_src(merged)
    assert "x = 2" in body, "candidate guard body missing -- guard was dropped"
    assert "x = 1" not in body, "target's OLD guard body survived the merge"
    assert "main()" not in body, (
        "wholesale replace expected: no remnant of the old guard body"
    )
    # the unrelated symbol the candidate omitted is preserved
    names = [n.name for n in ast.parse(merged).body if isinstance(n, ast.FunctionDef)]
    assert names == ["main"]


# ---------------------------------------------------------------------------
# 2. REPLACE, reversed comparison form: '__main__' == __name__ in the
#    candidate is the same guard.
# ---------------------------------------------------------------------------

def test_reversed_form_candidate_guard_replaces_canonical_target_guard():
    target = (
        'if __name__ == "__main__":\n'
        "    x = 1\n"
    )
    candidate = (
        "if '__main__' == __name__:\n"
        "    x = 2\n"
    )
    merged = _ast_merge(candidate, target)
    body = _sole_guard_body_src(merged)
    assert "x = 2" in body
    assert "x = 1" not in body


# ---------------------------------------------------------------------------
# 3. PRESERVE: candidate without a guard leaves the target's guard
#    verbatim (omitted => preserved, same as symbols).
# ---------------------------------------------------------------------------

def test_candidate_without_guard_preserves_targets_guard_verbatim():
    target = (
        "def f():\n"
        "    return 1\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    print(f())\n"
    )
    candidate = (
        "def g():\n"
        "    return 2\n"
    )
    merged = _ast_merge(candidate, target)
    merged_guards = _main_guards(merged)
    assert len(merged_guards) == 1
    want = ast.dump(
        _main_guards(target)[0], annotate_fields=True, include_attributes=False
    )
    got = ast.dump(merged_guards[0], annotate_fields=True, include_attributes=False)
    assert got == want, "target's guard must survive untouched when candidate omits it"
    # existing insertion semantics: the new symbol lands BEFORE the guard
    tree = ast.parse(merged)
    assert _is_module_main_guard(tree.body[-1])
    names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert names == ["f", "g"]


# ---------------------------------------------------------------------------
# 4. ADD: target without a guard gains the candidate's guard.
# ---------------------------------------------------------------------------

def test_target_without_guard_gains_candidates_guard():
    target = (
        "def h():\n"
        "    return 3\n"
    )
    candidate = (
        "def h():\n"
        "    return 4\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    print(h())\n"
    )
    merged = _ast_merge(candidate, target)
    body = _sole_guard_body_src(merged)
    assert "print(h())" in body
    # the keyed def replacement still happened alongside
    tree = ast.parse(merged)
    h = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "h")
    assert "return 4" in ast.unparse(h)


# ---------------------------------------------------------------------------
# 5. REGRESSION PIN: a normal def merge with NO guard in either input is
#    byte-for-byte unaffected by the guard keying (added function appends,
#    omitted function preserved, no guard materializes).
# ---------------------------------------------------------------------------

def test_plain_def_merge_with_no_guard_anywhere_is_unchanged():
    target = (
        "def foo():\n"
        "    return 1\n"
    )
    candidate = (
        "def bar():\n"
        "    return 2\n"
    )
    merged = _ast_merge(candidate, target)
    tree = ast.parse(merged)
    names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert names == ["foo", "bar"]
    assert not _main_guards(merged)
    assert ast.dump(tree) == ast.dump(
        ast.parse("def foo():\n    return 1\n\ndef bar():\n    return 2")
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-x", "-q"]))
