"""Tests for harness/ast_enforcer.py — AST validation and normalization."""

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.ast_enforcer import (
    Violation,
    are_structurally_equivalent,
    ast_to_canonical,
    normalize_ast,
    validate_code,
)


# ── Syntax Validation ───────────────────────────────────────────────────

class TestSyntaxValidation:
    def test_valid_function_no_violations(self):
        code = "def foo(x: int) -> int:\n    return x + 1\n"
        violations = validate_code(code)
        errors = [v for v in violations if v.severity == "error"]
        assert len(errors) == 0

    def test_syntax_error(self):
        code = "def foo(:\n    pass\n"
        violations = validate_code(code)
        assert any(v.rule == "syntax" for v in violations)

    def test_empty_string(self):
        violations = validate_code("")
        assert any(v.rule == "syntax" or v.rule == "incomplete_ast" for v in violations)

    def test_no_mergeable_top_level_is_incomplete(self):
        # Post-G13 (commit 7b97427): validator accepts Assign/AnnAssign/ClassDef/
        # ImportFrom as mergeable tops. A pass-only module has zero mergeable
        # nodes, so incomplete_ast must still fire.
        code = "pass\n"
        violations = validate_code(code)
        assert any(v.rule == "incomplete_ast" for v in violations)

    def test_top_level_assign_now_accepted(self):
        # Post-G13: top-level Name assignment is mergeable (data-only edits).
        code = "x = 1\ny = 2\n"
        violations = validate_code(code)
        errors = [v for v in violations if v.rule == "incomplete_ast"]
        assert len(errors) == 0

    def test_class_only_now_accepted(self):
        # Post-G13: ClassDef alone satisfies the mergeable-top requirement.
        code = "class Foo:\n    x = 1\n"
        violations = validate_code(code)
        errors = [v for v in violations if v.rule == "incomplete_ast"]
        assert len(errors) == 0

    def test_async_function_passes(self):
        code = "async def foo():\n    pass\n"
        violations = validate_code(code)
        errors = [v for v in violations if v.rule == "incomplete_ast"]
        assert len(errors) == 0

    def test_multiple_functions(self):
        code = "def foo(): pass\ndef bar(): pass\n"
        violations = validate_code(code)
        errors = [v for v in violations if v.severity == "error"]
        assert len(errors) == 0

    def test_nested_functions(self):
        code = "def foo():\n    def bar():\n        pass\n    return bar\n"
        violations = validate_code(code)
        errors = [v for v in violations if v.severity == "error"]
        assert len(errors) == 0


# ── Non-Determinism ─────────────────────────────────────────────────────

class TestNondeterminism:
    def test_import_random(self):
        code = "import random\ndef foo(): pass\n"
        violations = validate_code(code)
        assert any(v.rule == "nondeterminism" for v in violations)

    def test_from_random_import(self):
        code = "from random import randint\ndef foo(): pass\n"
        violations = validate_code(code)
        assert any(v.rule == "nondeterminism" for v in violations)

    def test_import_uuid(self):
        code = "import uuid\ndef foo(): pass\n"
        violations = validate_code(code)
        assert any(v.rule == "nondeterminism" for v in violations)

    def test_time_time_call(self):
        code = "import time\ndef foo():\n    return time.time()\n"
        violations = validate_code(code)
        assert any(v.rule == "nondeterminism" for v in violations)

    def test_datetime_now_call(self):
        code = "import datetime\ndef foo():\n    return datetime.now()\n"
        violations = validate_code(code)
        assert any(v.rule == "nondeterminism" for v in violations)

    def test_os_urandom_call(self):
        code = "import os\ndef foo():\n    return os.urandom(16)\n"
        violations = validate_code(code)
        assert any(v.rule == "nondeterminism" for v in violations)

    def test_allow_nondeterminism_flag(self):
        code = "import random\ndef foo():\n    return random.randint(1, 10)\n"
        violations = validate_code(code, allow_nondeterminism=True)
        nondet = [v for v in violations if v.rule == "nondeterminism"]
        assert len(nondet) == 0

    def test_deterministic_import_math(self):
        code = "import math\ndef foo(x: float) -> float:\n    return math.sqrt(x)\n"
        violations = validate_code(code)
        nondet = [v for v in violations if v.rule == "nondeterminism"]
        assert len(nondet) == 0

    def test_deterministic_import_collections(self):
        code = "import collections\ndef foo(): pass\n"
        violations = validate_code(code)
        nondet = [v for v in violations if v.rule == "nondeterminism"]
        assert len(nondet) == 0


# ── Bare Except ─────────────────────────────────────────────────────────

class TestBareExcept:
    def test_bare_except_pass(self):
        code = "def foo():\n    try:\n        pass\n    except:\n        pass\n"
        violations = validate_code(code)
        assert any(v.rule == "bare_except" for v in violations)

    def test_bare_except_with_body(self):
        code = "def foo():\n    try:\n        pass\n    except:\n        x = 1\n"
        violations = validate_code(code)
        bare = [v for v in violations if v.rule == "bare_except"]
        assert len(bare) == 0

    def test_typed_except_pass(self):
        code = "def foo():\n    try:\n        pass\n    except Exception:\n        pass\n"
        violations = validate_code(code)
        bare = [v for v in violations if v.rule == "bare_except"]
        assert len(bare) == 0

    def test_bare_except_correct_line(self):
        code = "def foo():\n    x = 1\n    try:\n        pass\n    except:\n        pass\n"
        violations = validate_code(code)
        bare = [v for v in violations if v.rule == "bare_except"]
        assert len(bare) == 1
        assert bare[0].line == 5


# ── os.system ───────────────────────────────────────────────────────────

class TestOsSystem:
    def test_os_system_detected(self):
        code = "import os\ndef foo():\n    os.system('ls')\n"
        violations = validate_code(code)
        assert any(v.rule == "os_system" for v in violations)

    def test_os_path_not_flagged(self):
        code = "import os\ndef foo():\n    return os.path.join('a', 'b')\n"
        violations = validate_code(code)
        os_sys = [v for v in violations if v.rule == "os_system"]
        assert len(os_sys) == 0

    def test_bare_system_not_flagged(self):
        code = "def foo():\n    system('ls')\n"
        violations = validate_code(code)
        os_sys = [v for v in violations if v.rule == "os_system"]
        assert len(os_sys) == 0


# ── Subprocess ──────────────────────────────────────────────────────────

class TestSubprocess:
    def test_run_without_check(self):
        code = "import subprocess\ndef foo():\n    subprocess.run(['ls'])\n"
        violations = validate_code(code)
        assert any(v.rule == "subprocess_no_check" for v in violations)

    def test_run_with_check(self):
        code = "import subprocess\ndef foo():\n    subprocess.run(['ls'], check=True)\n"
        violations = validate_code(code)
        sub = [v for v in violations if v.rule == "subprocess_no_check"]
        assert len(sub) == 0

    def test_call_without_check(self):
        code = "import subprocess\ndef foo():\n    subprocess.call(['ls'])\n"
        violations = validate_code(code)
        assert any(v.rule == "subprocess_no_check" for v in violations)


# ── Side Effects ────────────────────────────────────────────────────────

class TestSideEffects:
    def test_print_warning(self):
        code = "def foo():\n    print('hello')\n"
        violations = validate_code(code)
        assert any(v.rule == "side_effect" for v in violations)

    def test_open_warning(self):
        code = "def foo():\n    open('file.txt')\n"
        violations = validate_code(code)
        assert any(v.rule == "side_effect" for v in violations)

    def test_stdout_write_warning(self):
        code = "import sys\ndef foo():\n    sys.stdout.write('x')\n"
        violations = validate_code(code)
        assert any(v.rule == "side_effect" for v in violations)


# ── Unbounded Recursion ─────────────────────────────────────────────────

class TestUnboundedRecursion:
    def test_no_base_case(self):
        # The heuristic checks if a recursive call appears before any if/return guard.
        # In `def f(n): f(n)`, the call is the first statement with no prior guard.
        code = "def f(n):\n    f(n)\n    return n\n"
        violations = validate_code(code)
        assert any(v.rule == "unbounded_recursion" for v in violations)

    def test_with_base_case(self):
        code = "def f(n):\n    if n == 0:\n        return 1\n    return n * f(n - 1)\n"
        violations = validate_code(code)
        unbounded = [v for v in violations if v.rule == "unbounded_recursion"]
        assert len(unbounded) == 0

    def test_non_recursive(self):
        code = "def f(x: int) -> int:\n    return x * 2\n"
        violations = validate_code(code)
        unbounded = [v for v in violations if v.rule == "unbounded_recursion"]
        assert len(unbounded) == 0


class TestSecurityRules:
    def test_eval_banned(self):
        code = "def foo():\n    return eval('1 + 1')\n"
        violations = validate_code(code)
        assert any(v.rule == "security" and "eval" in v.message for v in violations)

    def test_exec_banned(self):
        code = "def foo():\n    exec('x = 1')\n"
        violations = validate_code(code)
        assert any(v.rule == "security" and "exec" in v.message for v in violations)

    def test_import_banned(self):
        code = "def foo():\n    __import__('os')\n"
        violations = validate_code(code)
        assert any(v.rule == "security" and "__import__" in v.message for v in violations)

    def test_hardcoded_credentials_assign(self):
        code = "def foo():\n    my_password = 'supersecret'\n"
        violations = validate_code(code)
        assert any(v.rule == "security" and "Hardcoded credential" in v.message for v in violations)

    def test_hardcoded_credentials_annassign(self):
        code = "def foo():\n    api_key: str = '12345'\n"
        violations = validate_code(code)
        assert any(v.rule == "security" and "Hardcoded credential" in v.message for v in violations)

# ── Normalization ───────────────────────────────────────────────────────

class TestNormalization:
    def test_docstrings_removed(self):
        code = 'def foo():\n    """Docstring."""\n    return 1\n'
        tree = normalize_ast(code)
        canonical = ast_to_canonical(tree)
        assert '"""' not in canonical
        assert "Docstring" not in canonical

    def test_docstring_only_body_becomes_pass(self):
        code = 'def foo():\n    """Only a docstring."""\n'
        tree = normalize_ast(code)
        # Should not raise and should produce valid code
        canonical = ast_to_canonical(tree)
        assert "pass" in canonical

    def test_imports_sorted(self):
        code = "import os\nimport abc\ndef foo(): pass\n"
        tree = normalize_ast(code)
        canonical = ast_to_canonical(tree)
        abc_pos = canonical.index("abc")
        os_pos = canonical.index("os")
        assert abc_pos < os_pos

    def test_redundant_pass_removed(self):
        code = "def foo():\n    x = 1\n    pass\n    return x\n"
        tree = normalize_ast(code)
        canonical = ast_to_canonical(tree)
        assert "pass" not in canonical

    def test_sole_pass_preserved(self):
        code = "def foo():\n    pass\n"
        tree = normalize_ast(code)
        canonical = ast_to_canonical(tree)
        assert "pass" in canonical

    def test_variable_normalizer_renames_locals(self):
        code = "def foo(x: int) -> int:\n    result = x + 1\n    temp = result * 2\n    return temp\n"
        tree = normalize_ast(code)
        canonical = ast_to_canonical(tree)
        assert "v0" in canonical
        assert "v1" in canonical
        # Parameters NOT renamed
        assert "x" in canonical

    def test_params_not_renamed(self):
        code = "def foo(a: int, b: int) -> int:\n    return a + b\n"
        tree = normalize_ast(code)
        canonical = ast_to_canonical(tree)
        assert "a" in canonical and "b" in canonical

    def test_function_name_not_renamed(self):
        code = "def my_special_func():\n    pass\n"
        tree = normalize_ast(code)
        canonical = ast_to_canonical(tree)
        assert "my_special_func" in canonical

    def test_imported_names_not_renamed(self):
        code = "import os\ndef foo():\n    return os.getcwd()\n"
        tree = normalize_ast(code)
        canonical = ast_to_canonical(tree)
        assert "os" in canonical

    def test_round_trip(self):
        code = "def foo(x: int) -> int:\n    y = x + 1\n    return y\n"
        tree = normalize_ast(code)
        canonical = ast_to_canonical(tree)
        # Should be valid parseable Python
        ast.parse(canonical)


# ── Structural Equivalence ──────────────────────────────────────────────

class TestStructuralEquivalence:
    def test_identical_code(self):
        code = "def foo(x: int) -> int:\n    return x + 1\n"
        assert are_structurally_equivalent(code, code) is True

    def test_different_variable_names(self):
        code_a = "def foo(x: int) -> int:\n    result = x + 1\n    return result\n"
        code_b = "def foo(x: int) -> int:\n    answer = x + 1\n    return answer\n"
        assert are_structurally_equivalent(code_a, code_b) is True

    def test_different_comments(self):
        code_a = "# Comment A\ndef foo(x: int) -> int:\n    return x + 1\n"
        code_b = "# Comment B\ndef foo(x: int) -> int:\n    return x + 1\n"
        assert are_structurally_equivalent(code_a, code_b) is True

    def test_different_import_order(self):
        code_a = "import os\nimport abc\ndef foo(): pass\n"
        code_b = "import abc\nimport os\ndef foo(): pass\n"
        assert are_structurally_equivalent(code_a, code_b) is True

    def test_functionally_different(self):
        code_a = "def foo(x: int) -> int:\n    return x + 1\n"
        code_b = "def foo(x: int) -> int:\n    return x + 2\n"
        assert are_structurally_equivalent(code_a, code_b) is False

    def test_one_syntax_error(self):
        code_a = "def foo(x): return x\n"
        code_b = "def foo(x return x\n"
        assert are_structurally_equivalent(code_a, code_b) is False

    def test_different_docstrings_equivalent(self):
        code_a = 'def foo(x: int) -> int:\n    """Doc A."""\n    return x\n'
        code_b = 'def foo(x: int) -> int:\n    """Doc B."""\n    return x\n'
        assert are_structurally_equivalent(code_a, code_b) is True


# ── Additional Tests (A-09, A-10, A-20, A-21, A-23, A-26, A-30, A-34,
#    A-38, A-41, A-43, A-47, A-55, A-63) ────────────────────────────────

class TestSyntaxValidationExtra:
    """A-09, A-10: Additional syntax validation tests."""

    def test_pattern_matching_syntax(self):
        """A-09: Python 3.10+ pattern matching syntax parses without syntax error."""
        code = (
            "def classify(value):\n"
            "    match value:\n"
            "        case 0:\n"
            "            return 'zero'\n"
            "        case int(n) if n > 0:\n"
            "            return 'positive'\n"
            "        case _:\n"
            "            return 'other'\n"
        )
        violations = validate_code(code)
        syntax_errors = [v for v in violations if v.rule == "syntax"]
        assert len(syntax_errors) == 0

    def test_encoding_declaration(self):
        """A-10: Code with encoding declaration should not cause violations."""
        code = (
            "# -*- coding: utf-8 -*-\n"
            "def foo(x: int) -> int:\n"
            "    return x + 1\n"
        )
        violations = validate_code(code)
        errors = [v for v in violations if v.severity == "error"]
        assert len(errors) == 0


class TestNondeterminismExtra:
    """A-20, A-21: Additional nondeterminism tests."""

    def test_import_random_inside_function_body(self):
        """A-20: `import random` inside function body is still detected."""
        code = (
            "def foo():\n"
            "    import random\n"
            "    return random.randint(1, 10)\n"
        )
        violations = validate_code(code)
        assert any(v.rule == "nondeterminism" for v in violations)

    def test_from_random_import_choice(self):
        """A-21: `from random import choice` — top-level module is random."""
        code = (
            "from random import choice\n"
            "def foo(items):\n"
            "    return choice(items)\n"
        )
        violations = validate_code(code)
        assert any(v.rule == "nondeterminism" for v in violations)


class TestBareExceptExtra:
    """A-23, A-26: Additional bare except tests."""

    def test_bare_except_with_assignment_no_violation(self):
        """A-23: `except: x = 1` — body is not just pass, no bare_except violation."""
        code = (
            "def foo():\n"
            "    try:\n"
            "        pass\n"
            "    except:\n"
            "        x = 1\n"
        )
        violations = validate_code(code)
        bare = [v for v in violations if v.rule == "bare_except"]
        assert len(bare) == 0

    def test_multiple_bare_except_pass_blocks(self):
        """A-26: Multiple `except: pass` blocks produce multiple violations."""
        code = (
            "def foo():\n"
            "    try:\n"
            "        pass\n"
            "    except:\n"
            "        pass\n"
            "    try:\n"
            "        pass\n"
            "    except:\n"
            "        pass\n"
        )
        violations = validate_code(code)
        bare = [v for v in violations if v.rule == "bare_except"]
        assert len(bare) == 2


class TestOsSystemExtra:
    """A-30: Different module name should not trigger os_system."""

    def test_different_module_name_system(self):
        """A-30: `my_os.system('ls')` — not os.system, no violation."""
        code = (
            "def foo():\n"
            "    my_os.system('ls')\n"
        )
        violations = validate_code(code)
        os_sys = [v for v in violations if v.rule == "os_system"]
        assert len(os_sys) == 0


class TestSubprocessExtra:
    """A-34: subprocess.Popen not covered by check rule."""

    def test_subprocess_popen_no_violation(self):
        """A-34: `subprocess.Popen(['ls'])` — not run/call, no subprocess_no_check."""
        code = (
            "import subprocess\n"
            "def foo():\n"
            "    subprocess.Popen(['ls'])\n"
        )
        violations = validate_code(code)
        sub = [v for v in violations if v.rule == "subprocess_no_check"]
        assert len(sub) == 0


class TestSideEffectsExtra:
    """A-38: logging.info is not in the side-effect check list."""

    def test_logging_info_no_side_effect(self):
        """A-38: `logging.info('x')` — not in _SIDE_EFFECT_NAMES or _SIDE_EFFECT_ATTRS."""
        code = (
            "import logging\n"
            "def foo():\n"
            "    logging.info('x')\n"
        )
        violations = validate_code(code)
        side = [v for v in violations if v.rule == "side_effect"]
        assert len(side) == 0


class TestRecursionExtra:
    """A-41, A-43: Additional recursion detection tests."""

    def test_ast_enforcer_recursion_guard_heuristic(self):
        """Verify recursion detection allows safe patterns and blocks unsafe."""
        # Unsafe recursion (blocked)
        bad_code = "def f(n):\n    return f(n)\n"
        bad_violations = validate_code(bad_code)
        assert any(v.rule == "unbounded_recursion" for v in bad_violations)

        # Safe recursion via for-loop (allowed)
        safe_for_code = "def f(node):\n    for child in node:\n        f(child)\n"
        safe_for_violations = validate_code(safe_for_code)
        assert not any(v.rule == "unbounded_recursion" for v in safe_for_violations)

        # Safe recursion via while-loop (allowed)
        safe_while_code = "def f(q):\n    while q:\n        f(q.pop())\n"
        safe_while_violations = validate_code(safe_while_code)
        assert not any(v.rule == "unbounded_recursion" for v in safe_while_violations)

    def test_ternary_recursion_guard(self):
        """A-41: `def f(n): return f(n) if n else 0` — heuristic-dependent.
        The ternary is a Return statement, so it acts as a guard.
        The recursive call is inside the return, and return appears first,
        so this should NOT trigger unbounded_recursion."""
        code = "def f(n):\n    return f(n) if n else 0\n"
        violations = validate_code(code)
        # The return stmt is seen before the recursive call within it,
        # so seen_guard is True. No unbounded_recursion warning expected.
        unbounded = [v for v in violations if v.rule == "unbounded_recursion"]
        assert len(unbounded) == 0

    def test_mutual_recursion_no_violation(self):
        """A-43: Mutual recursion (f calls g, g calls f) — the heuristic only
        checks self-recursion by name, so no violation should be reported."""
        code = (
            "def f(n):\n"
            "    return g(n - 1)\n"
            "def g(n):\n"
            "    return f(n - 1)\n"
        )
        violations = validate_code(code)
        unbounded = [v for v in violations if v.rule == "unbounded_recursion"]
        assert len(unbounded) == 0


class TestNormalizationExtra:
    """A-47, A-55: Additional normalization tests."""

    def test_ast_enforcer_redundant_pass_remover(self):
        """Verify correct pass removal respecting block scopes."""
        code = (
            "def foo():\n"
            "    pass\n"
            "    print(1)\n"
            "    if 1:\n"
            "        pass\n"
            "        print(2)\n"
            "    else:\n"
            "        pass\n"
            "    while True:\n"
            "        pass\n"
        )
        tree = normalize_ast(code)
        canonical = ast_to_canonical(tree)
        assert "print(2)" in canonical
        assert "pass" in canonical
        
        lines = canonical.splitlines()
        pass_lines = [line.strip() for line in lines if line.strip() == "pass"]
        assert len(pass_lines) == 2

    def test_non_contiguous_import_groups_sorted_independently(self):
        """A-47: Non-contiguous import groups sorted independently."""
        code = (
            "import os\n"
            "import abc\n"
            "x = 1\n"
            "import sys\n"
            "import json\n"
            "def foo(): pass\n"
        )
        tree = normalize_ast(code)
        canonical = ast_to_canonical(tree)
        # First group: abc, os (sorted)
        # Then x = 1
        # Second group: json, sys (sorted)
        abc_pos = canonical.index("abc")
        os_pos = canonical.index("os")
        json_pos = canonical.index("json")
        sys_pos = canonical.index("sys")
        assert abc_pos < os_pos, "First import group should be sorted"
        assert json_pos < sys_pos, "Second import group should be sorted"

    def test_nested_function_locals_renamed_independently(self):
        """A-55: Nested function locals get their own v0, v1, ... series."""
        code = (
            "def outer(x):\n"
            "    a = x + 1\n"
            "    def inner(y):\n"
            "        b = y + 2\n"
            "        return b\n"
            "    return inner(a)\n"
        )
        tree = normalize_ast(code)
        canonical = ast_to_canonical(tree)
        # Both outer and inner should have their locals renamed to v0.
        # 'a' in outer -> v0, 'b' in inner -> v0
        # The canonical should contain v0 referenced in both contexts.
        assert "v0" in canonical
        # Parameters x and y should NOT be renamed
        assert "x" in canonical
        assert "y" in canonical


class TestStructuralEquivalenceExtra:
    """A-63: Both have syntax errors."""

    def test_both_syntax_errors_returns_false(self):
        """A-63: Both code samples have syntax errors — returns False."""
        code_a = "def foo(:\n    pass\n"
        code_b = "def bar(:\n    pass\n"
        assert are_structurally_equivalent(code_a, code_b) is False
