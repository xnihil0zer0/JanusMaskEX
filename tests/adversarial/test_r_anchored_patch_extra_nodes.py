"""Oracle for PHASE_R_ANCHORED_PATCH (REV17 §3 item 7, R-anchored-patch).

Drives the REAL harness.git_integration._apply_symbol_patch directly. RED on
HEAD 862f329 (Test A: HEAD rejects any new_block carrying extra top-level
nodes alongside the target def), GREEN after the applier is upgraded to allow a
bounded set of extra top-level nodes (Import/ImportFrom/FunctionDef/
AsyncFunctionDef/ClassDef) for a 1-part top-level qualname.

Placed at tests/adversarial/test_r_anchored_patch_extra_nodes.py; importable
from repo root.
"""
from __future__ import annotations

import ast

import pytest

import harness.git_integration as gi


# --------------------------------------------------------------------------- #
# Test A — RED on HEAD, GREEN after fix.
# new_block carries an extra module-level import + helper def alongside target.
# HEAD's applier requires exactly one def/class node -> ValueError. After the
# upgrade the extras (import os + def helper) are inserted at col-0 immediately
# before the replaced def target, and the whole result ast.parses.
# --------------------------------------------------------------------------- #
def test_A_extra_import_and_helper_inserted_before_target():
    src = "def target():\n    return 0\n"
    new_block = (
        "import os\n"
        "\n"
        "def helper():\n"
        "    return os.getpid()\n"
        "\n"
        "def target():\n"
        "    return helper()\n"
    )
    out = gi._apply_symbol_patch(src, "target", new_block)
    # Result must be valid Python.
    tree = ast.parse(out)
    # Top-level symbols present: import os, def helper, def target.
    imports = [
        n for n in tree.body
        if isinstance(n, ast.Import) and any(a.name == "os" for a in n.names)
    ]
    assert imports, f"expected a top-level 'import os'; got:\n{out}"
    fn_names = {
        n.name for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "helper" in fn_names, f"expected def helper; got:\n{out}"
    assert "target" in fn_names, f"expected def target; got:\n{out}"
    # The replaced target now calls helper (old body 'return 0' gone).
    assert "helper()" in out
    assert "return 0" not in out
    # Extras come before the target's replacement block.
    assert out.index("def helper") < out.index("def target")
    assert out.index("import os") < out.index("def target")


# --------------------------------------------------------------------------- #
# Test B — positive control, RED-equivalent both before AND after the fix.
# An extra of a DISALLOWED kind (module-level assignment X = 1) alongside the
# target -> ValueError on HEAD (not one def/class) and ValueError after (the
# allowed extra set is bounded to imports + def/class only).
# --------------------------------------------------------------------------- #
def test_B_disallowed_extra_assignment_rejected():
    src = "def target():\n    return 0\n"
    new_block = (
        "X = 1\n"
        "\n"
        "def target():\n"
        "    return X\n"
    )
    with pytest.raises(ValueError):
        gi._apply_symbol_patch(src, "target", new_block)


# --------------------------------------------------------------------------- #
# Test C — positive control / regression guard, GREEN both before AND after.
# A plain single-def new_block (no extras) applies exactly as today: the
# surrounding bytes are preserved and only the named def is replaced.
# --------------------------------------------------------------------------- #
def test_C_plain_single_def_no_extras_regression():
    src = "HEADER = 1\n\ndef target():\n    return 0\n\nFOOTER = 2\n"
    new_block = "def target():\n    return 42\n"
    out = gi._apply_symbol_patch(src, "target", new_block)
    # Byte-exact neighbors preserved (the no-extras path is unchanged).
    assert out == "HEADER = 1\n\ndef target():\n    return 42\n\nFOOTER = 2\n"


# --------------------------------------------------------------------------- #
# Test D — positive control, after fix MUST still ValueError.
# A 2-part nested qualname (Outer.inner) with an extra import -> extras are
# only permitted for a 1-part top-level qualname, so this ValueErrors after the
# fix (it also ValueErrors on HEAD). The point: extras must NOT be silently
# misplaced into a class body.
# --------------------------------------------------------------------------- #
def test_D_nested_qualname_with_extra_rejected():
    src = (
        "class Outer:\n"
        "    def inner(self):\n"
        "        return 0\n"
    )
    new_block = (
        "import os\n"
        "\n"
        "def inner(self):\n"
        "    return os.getpid()\n"
    )
    with pytest.raises(ValueError):
        gi._apply_symbol_patch(src, "Outer.inner", new_block)
