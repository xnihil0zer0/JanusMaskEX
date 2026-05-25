"""Adversarial bar for AW15 (aw15_poll_interval_constant).

These tests are xfail-strict until the AW15 dispatch lands the
top-level `AUTOWORK_POLL_SECONDS = 5.0` constant in `harness/__init__.py`.
On accept, drop the xfail markers (or flip to non-xfail) so they become
regression guards. They assert the same invariants the task's
verification_command checks, but split into discrete pytest cases.
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


def test_autowork_poll_seconds_defined_and_equals_5_0():
    import harness

    importlib.reload(harness)
    assert hasattr(harness, "AUTOWORK_POLL_SECONDS"), (
        "harness.AUTOWORK_POLL_SECONDS missing — AW15 not yet dispatched"
    )
    assert harness.AUTOWORK_POLL_SECONDS == 5.0


def test_autowork_poll_seconds_is_top_level_assign():
    tree = _module_tree()
    node = _top_level_assign_by_name(tree, "AUTOWORK_POLL_SECONDS")
    assert node is not None, (
        "AUTOWORK_POLL_SECONDS not found as a top-level ast.Assign in harness/__init__.py"
    )
    assert isinstance(node, ast.Assign)
    assert len(node.targets) == 1
    assert isinstance(node.targets[0], ast.Name)
    assert node.targets[0].id == "AUTOWORK_POLL_SECONDS"
    assert isinstance(node.value, ast.Constant)
    assert node.value.value == 5.0
    assert isinstance(node.value.value, float)


def test_pre_existing_constants_preserved():
    import harness

    importlib.reload(harness)
    # Pre-existing top-level constants must all remain at their pinned values.
    assert harness.__version__ == "0.1.0"
    assert harness.MAX_PARALLEL_FUZZ == 1
    assert harness.MAX_SYNTHESIS_RETRIES == 3
    # And the new constant must coexist (gates xfail->pass transition).
    assert harness.AUTOWORK_POLL_SECONDS == 5.0

    tree = _module_tree()
    names = _top_level_assign_names(tree)
    assert {"__version__", "MAX_PARALLEL_FUZZ", "MAX_SYNTHESIS_RETRIES", "AUTOWORK_POLL_SECONDS"}.issubset(names)


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
    assert "AUTOWORK_POLL_SECONDS" in names
