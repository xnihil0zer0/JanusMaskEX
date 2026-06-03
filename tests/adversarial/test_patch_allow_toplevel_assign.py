"""Pytest oracle for PATCH_ALLOW_TOPLEVEL_ASSIGN.

Calls harness.git_integration._apply_symbol_patch directly to verify that:
1. ast.Assign and ast.AnnAssign are allowed as extra top-level nodes for a 1-part qualname.
2. Collision checks extend to existing module-level Assign/AnnAssign target names.
3. Extra Assign targets are validated across tuple/list unpacking, raising ValueError for non-Names.
4. Extra AnnAssign targets must be a single Name, raising ValueError otherwise.
5. All other constraints (like 2-part qualname restriction, error messages) are preserved.
"""

from __future__ import annotations

import ast
import pytest

import harness.git_integration as gi


def test_positive_assign_and_annassign():
    """POSITIVE (RED on HEAD): new_block contains Assign and AnnAssign extra nodes.

    On HEAD, this raises ValueError 'disallowed extra top-level node kind: Assign'.
    After the fix, this succeeds and returns a spliced source code where both FOO
    and BAR appear at the module top level and the primary body is replaced correctly.
    """
    src = (
        "# Existing code\n"
        "EXISTING_CONST = 100\n"
        "\n"
        "def target():\n"
        "    return 0\n"
    )
    new_block = (
        "FOO = 123\n"
        "BAR: int = 5\n"
        "def target():\n"
        "    return 1\n"
    )

    # Calling directly
    out = gi._apply_symbol_patch(src, "target", new_block)

    # Assert with ast.parse on output
    tree = ast.parse(out)
    
    # Check that FOO and BAR appear at the module top level
    assign_names = set()
    ann_assign_names = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assign_names.add(t.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                ann_assign_names.add(node.target.id)

    assert "FOO" in assign_names, f"Expected 'FOO' in top-level Assigns, got:\n{out}"
    assert "BAR" in ann_assign_names, f"Expected 'BAR' in top-level AnnAssigns, got:\n{out}"
    
    # Assert primary body is preserved/modified
    assert "return 1" in out
    assert "return 0" not in out


def test_negative_a_collision_with_existing_assign():
    """NEGATIVE a (must STILL raise after fix): extra Assign target name collides with existing Assign.

    After the fix, the collision set is extended to include existing module-level Assign targets.
    """
    src = (
        "EXISTING_VAR = 42\n"
        "\n"
        "def target():\n"
        "    return 0\n"
    )
    new_block = (
        "EXISTING_VAR = 99\n"
        "def target():\n"
        "    return 1\n"
    )
    with pytest.raises(ValueError) as excinfo:
        gi._apply_symbol_patch(src, "target", new_block)
    assert "collides with an existing top-level symbol" in str(excinfo.value)


def test_negative_a_collision_with_existing_def():
    """NEGATIVE a (must STILL raise after fix): extra AnnAssign target name collides with existing def.
    """
    src = (
        "def existing_func():\n"
        "    pass\n"
        "\n"
        "def target():\n"
        "    return 0\n"
    )
    new_block = (
        "existing_func: int = 5\n"
        "def target():\n"
        "    return 1\n"
    )
    with pytest.raises(ValueError) as excinfo:
        gi._apply_symbol_patch(src, "target", new_block)
    assert "collides with an existing top-level symbol" in str(excinfo.value)


def test_negative_a_collision_unpacking():
    """NEGATIVE a (must STILL raise after fix): extra unpacking Assign target name collides with existing def.
    """
    src = (
        "def existing_func():\n"
        "    pass\n"
        "\n"
        "def target():\n"
        "    return 0\n"
    )
    new_block = (
        "A, existing_func = 1, 2\n"
        "def target():\n"
        "    return 1\n"
    )
    with pytest.raises(ValueError) as excinfo:
        gi._apply_symbol_patch(src, "target", new_block)
    assert "collides with an existing top-level symbol" in str(excinfo.value)


def test_negative_b_2part_qualname_with_extra():
    """NEGATIVE b (must STILL raise after fix): 2-part qualname Outer.inner with any extra -> ValueError.
    """
    src = (
        "class Outer:\n"
        "    def inner(self):\n"
        "        return 0\n"
    )
    new_block = (
        "FOO = 123\n"
        "def inner(self):\n"
        "    return 1\n"
    )
    with pytest.raises(ValueError) as excinfo:
        gi._apply_symbol_patch(src, "Outer.inner", new_block)
    # The message should state extras are only permitted for 1-part qualname
    assert "extra top-level nodes are only permitted for a 1-part top-level qualname" in str(excinfo.value)


def test_negative_c_non_name_assign_target():
    """NEGATIVE c (must STILL raise after fix): extra Assign with non-Name target `obj.attr = 1` -> ValueError.
    """
    src = (
        "def target():\n"
        "    return 0\n"
    )
    new_block = (
        "obj.attr = 1\n"
        "def target():\n"
        "    return 1\n"
    )
    with pytest.raises(ValueError):
        gi._apply_symbol_patch(src, "target", new_block)


def test_negative_c_non_name_annassign_target():
    """NEGATIVE c (must STILL raise after fix): extra AnnAssign with non-Name target -> ValueError.
    """
    src = (
        "def target():\n"
        "    return 0\n"
    )
    new_block = (
        "obj.attr: int = 1\n"
        "def target():\n"
        "    return 1\n"
    )
    with pytest.raises(ValueError):
        gi._apply_symbol_patch(src, "target", new_block)


def test_regression_extra_import_and_def():
    """REGRESSION (GREEN before AND after): extra new Import + extra new def (no Assign) still apply.
    """
    src = (
        "def target():\n"
        "    return 0\n"
    )
    new_block = (
        "import math\n"
        "def helper():\n"
        "    return math.pi\n"
        "\n"
        "def target():\n"
        "    return helper()\n"
    )
    out = gi._apply_symbol_patch(src, "target", new_block)
    
    # Assert with ast.parse on output
    tree = ast.parse(out)
    fn_names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "helper" in fn_names
    assert "target" in fn_names
    assert "import math" in out
