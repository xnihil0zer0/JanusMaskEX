"""Adversarial bar for AW18 (aw18_min_wall_constant).

These tests are xfail-strict until the AW18 dispatch lands the
top-level `PLANNER_MIN_WALL_SECONDS = 10.0` constant in `harness/__init__.py`.
On accept, drop the xfail markers (or flip to non-xfail) so they become
regression guards. They assert the same invariants the task's
verification_command checks, but split into discrete pytest cases.

The constant is the named harness-level cap for the Gemini hallucination
guard documented in the operator-memory
`feedback_planner_gemini_hallucination.md` rule (sub-10s Gemini drafts are
hallucinated). The existing band-aid defaults live at
`harness/autowork_daemon.py:330` (`_check_hallucination` `min_wall=10.0`)
and `harness/planner/blind_draft.py:41` (`collect_agent_draft`
`min_response_seconds=10.0`); AW18 introduces the named constant only and
defers the consumer-side rewire to a P4 follow-up.
"""

from __future__ import annotations

import ast
import importlib
import pathlib

import pytest

HARNESS_INIT_PATH = pathlib.Path(__file__).resolve().parents[2] / "harness" / "__init__.py"


def _module_tree() -> ast.Module:
    src = HARNESS_INIT_PATH.read_text()
    return ast.parse(src)


def _top_level_assign_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _top_level_assign_by_name(tree: ast.Module, name: str) -> ast.Assign | None:
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return node
    return None


def test_planner_min_wall_seconds_defined_and_equals_10_0():
    import harness

    importlib.reload(harness)
    assert hasattr(harness, "PLANNER_MIN_WALL_SECONDS"), (
        "harness.PLANNER_MIN_WALL_SECONDS missing — AW18 not yet dispatched"
    )
    assert harness.PLANNER_MIN_WALL_SECONDS == 10.0


def test_planner_min_wall_seconds_is_top_level_assign_float_literal():
    """The value must be a bare float literal (10.0), not an int, not a BinOp.

    Discriminator: ast.Constant with value 10.0 AND isinstance(value, float)
    AND not isinstance(value, int). Python's `float` is NOT a subclass of
    `int` (unlike `bool`, which IS a subclass of `int`), so this combination
    rules out a worker emitting `10` (int — would pass numeric equality but
    fail the float check), `5.0 * 2` (BinOp), or `1e1` (also a float
    literal whose ast.Constant value would still satisfy the gates, but
    the canonical literal form is `10.0` and the numeric == check accepts
    any float equal to 10.0).
    """
    tree = _module_tree()
    node = _top_level_assign_by_name(tree, "PLANNER_MIN_WALL_SECONDS")
    assert node is not None, (
        "PLANNER_MIN_WALL_SECONDS not found as a top-level ast.Assign in harness/__init__.py"
    )
    assert isinstance(node, ast.Assign)
    assert len(node.targets) == 1
    assert isinstance(node.targets[0], ast.Name)
    assert node.targets[0].id == "PLANNER_MIN_WALL_SECONDS"
    assert isinstance(node.value, ast.Constant), (
        "PLANNER_MIN_WALL_SECONDS RHS must be an ast.Constant (not a BinOp like 5.0*2)"
    )
    assert node.value.value == 10.0
    assert isinstance(node.value.value, float), (
        "PLANNER_MIN_WALL_SECONDS must be a float literal (10.0), not an int (10)"
    )
    assert not isinstance(node.value.value, int), (
        "PLANNER_MIN_WALL_SECONDS must be float, not int "
        "(int literal 10 would pass `== 10.0` numeric equality but is the wrong type)"
    )


def test_pre_existing_constants_preserved():
    import harness

    importlib.reload(harness)
    # Pre-existing top-level constants must all remain at their pinned values.
    assert harness.__version__ == "0.1.0"
    assert harness.MAX_PARALLEL_FUZZ == 1
    assert harness.MAX_SYNTHESIS_RETRIES == 3
    # And the new constant must coexist (gates xfail->pass transition).
    assert harness.PLANNER_MIN_WALL_SECONDS == 10.0
    # Float-not-int live-module check as well (verification_command parity).
    assert isinstance(harness.PLANNER_MIN_WALL_SECONDS, float)
    assert not isinstance(harness.PLANNER_MIN_WALL_SECONDS, int)

    tree = _module_tree()
    names = _top_level_assign_names(tree)
    assert {
        "__version__",
        "MAX_PARALLEL_FUZZ",
        "MAX_SYNTHESIS_RETRIES",
        "PLANNER_MIN_WALL_SECONDS",
    }.issubset(names)


def test_no_new_imports_functions_classes_or_dunder_all():
    tree = _module_tree()
    forbidden_node_types = (
        ast.Import,
        ast.ImportFrom,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
    )
    forbidden_nodes = [n for n in ast.iter_child_nodes(tree) if isinstance(n, forbidden_node_types)]
    assert forbidden_nodes == [], (
        f"harness/__init__.py must not introduce imports/functions/classes; found: {forbidden_nodes!r}"
    )
    names = _top_level_assign_names(tree)
    assert "__all__" not in names, "harness/__init__.py must not introduce __all__"

    # Bare-string expression `'JanusMask harness package.'` must still be present.
    exprs = [
        n
        for n in ast.iter_child_nodes(tree)
        if isinstance(n, ast.Expr)
        and isinstance(n.value, ast.Constant)
        and isinstance(n.value.value, str)
    ]
    assert any(
        n.value.value == "JanusMask harness package." for n in exprs
    ), "bare-string 'JanusMask harness package.' must remain at module top level"

    # The new constant must be present so this case only flips after dispatch.
    assert "PLANNER_MIN_WALL_SECONDS" in names
