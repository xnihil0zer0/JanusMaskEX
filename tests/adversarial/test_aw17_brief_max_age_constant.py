"""Adversarial bar for AW17 (aw17_brief_max_age_constant).

These tests are xfail-strict until the AW17 dispatch lands the
top-level `BRIEF_MAX_AGE_SECONDS = 604800` constant in `harness/__init__.py`.
On accept, drop the xfail markers (or flip to non-xfail) so they become
regression guards. They assert the same invariants the task's
verification_command checks, but split into discrete pytest cases.

The constant is the named harness-level cap for the unstaged "stale-brief
filter" P4 item (session-22 backlog review §brief_max_age_seconds entries:
Janusmask-backlog-review-subreport-01.md:48,58,82 and
Janusmask-backlog-review-report.md:142). The hard-coded
`DEFAULT_BRIEF_MAX_AGE_SEC = 604800` at `harness/autowork_daemon.py:646` is the
eventual consumer-side rewire target; AW17 lands the named constant only.
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


def test_brief_max_age_seconds_defined_and_equals_604800():
    import harness

    importlib.reload(harness)
    assert hasattr(harness, "BRIEF_MAX_AGE_SECONDS"), (
        "harness.BRIEF_MAX_AGE_SECONDS missing — AW17 not yet dispatched"
    )
    assert harness.BRIEF_MAX_AGE_SECONDS == 604800


def test_brief_max_age_seconds_is_top_level_assign_int_literal():
    """The value must be a bare int literal (604800), not a float, not a BinOp.

    Discriminator: ast.Constant with value 604800 AND isinstance(value, int) AND
    not isinstance(value, bool). This rules out a worker emitting `604800.0`,
    `6.048e5`, `604_800` (still int but flagged for strict-shape brevity here
    we accept the canonical literal only via the numeric == check), or
    `60 * 60 * 24 * 7` (BinOp).
    """
    tree = _module_tree()
    node = _top_level_assign_by_name(tree, "BRIEF_MAX_AGE_SECONDS")
    assert node is not None, (
        "BRIEF_MAX_AGE_SECONDS not found as a top-level ast.Assign in harness/__init__.py"
    )
    assert isinstance(node, ast.Assign)
    assert len(node.targets) == 1
    assert isinstance(node.targets[0], ast.Name)
    assert node.targets[0].id == "BRIEF_MAX_AGE_SECONDS"
    assert isinstance(node.value, ast.Constant), (
        "BRIEF_MAX_AGE_SECONDS RHS must be an ast.Constant (not a BinOp like 60*60*24*7)"
    )
    assert node.value.value == 604800
    assert isinstance(node.value.value, int), (
        "BRIEF_MAX_AGE_SECONDS must be an int literal (604800), not a float (604800.0)"
    )
    assert not isinstance(node.value.value, bool), (
        "BRIEF_MAX_AGE_SECONDS must be int, not bool (Python bool is a subclass of int)"
    )


def test_pre_existing_constants_preserved():
    import harness

    importlib.reload(harness)
    # Pre-existing top-level constants must all remain at their pinned values.
    assert harness.__version__ == "0.1.0"
    assert harness.MAX_PARALLEL_FUZZ == 1
    assert harness.MAX_SYNTHESIS_RETRIES == 3
    # And the new constant must coexist (gates xfail->pass transition).
    assert harness.BRIEF_MAX_AGE_SECONDS == 604800
    # Int-not-float live-module check as well (verification_command parity).
    assert isinstance(harness.BRIEF_MAX_AGE_SECONDS, int)
    assert not isinstance(harness.BRIEF_MAX_AGE_SECONDS, bool)

    tree = _module_tree()
    names = _top_level_assign_names(tree)
    assert {
        "__version__",
        "MAX_PARALLEL_FUZZ",
        "MAX_SYNTHESIS_RETRIES",
        "BRIEF_MAX_AGE_SECONDS",
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
    assert "BRIEF_MAX_AGE_SECONDS" in names
