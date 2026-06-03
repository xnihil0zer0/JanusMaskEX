"""RED oracle for plan item P-UNB1: AnnAssign/Assign PRIMARY targeting in
``_apply_symbol_patch`` (harness/git_integration.py).

On HEAD (fe53a59) the primary-resolution loop only matches FunctionDef /
AsyncFunctionDef / ClassDef nodes (``_is_def`` + ``.name``), so a top-level
``AnnAssign`` ("X: int = 1") or a single-``Name`` ``Assign`` ("X = 1") used as
the PRIMARY partial_edit target is never located and ``KeyError(qualname)`` is
raised at git_integration.py:1081. The NEW-CAPABILITY assertions below therefore
FAIL (RED) on HEAD; the REGRESSION assertions (FunctionDef / ClassDef primary
targeting, and the existing extras-collision guards) PASS both before and after.

This file edits NO production code. It only expresses the gap.
"""
import ast

import pytest

from harness.git_integration import _apply_symbol_patch


# ---------------------------------------------------------------------------
# NEW-CAPABILITY oracles (RED on HEAD -> GREEN after P-UNB1 lands)
# ---------------------------------------------------------------------------

def test_annassign_primary_round_trips_byte_identical():
    """A top-level AnnAssign used as the PRIMARY target round-trips off the
    no-extras path (byte-identical splice). RED on HEAD: KeyError('MAX_RETRIES')."""
    src = (
        "import os\n"
        "\n"
        "MAX_RETRIES: int = 3\n"
        "\n"
        "def helper():\n"
        "    return MAX_RETRIES\n"
    )
    new_block = "MAX_RETRIES: int = 7\n"
    out = _apply_symbol_patch(src, "MAX_RETRIES", new_block)
    expected = (
        "import os\n"
        "\n"
        "MAX_RETRIES: int = 7\n"
        "\n"
        "def helper():\n"
        "    return MAX_RETRIES\n"
    )
    assert out == expected
    # Every byte outside the targeted AnnAssign line is preserved.
    assert "import os\n" in out
    assert "def helper():\n    return MAX_RETRIES\n" in out


def test_single_name_assign_primary_round_trips():
    """A single-Name top-level Assign ("X = ...") used as PRIMARY target works.
    RED on HEAD: KeyError('FLAG')."""
    src = (
        "FLAG = False\n"
        "\n"
        "def use():\n"
        "    return FLAG\n"
    )
    new_block = "FLAG = True\n"
    out = _apply_symbol_patch(src, "FLAG", new_block)
    expected = (
        "FLAG = True\n"
        "\n"
        "def use():\n"
        "    return FLAG\n"
    )
    assert out == expected


def test_annassign_primary_uniqueness_missing_name_rejected():
    """The len(primaries)==1 uniqueness guard must admit AnnAssign and REJECT a
    name that is not a top-level assign/def in source. On HEAD this raises
    KeyError already (no AnnAssign primary path), so the test only pins that a
    missing name is rejected; after P-UNB1 it must STILL be rejected (KeyError /
    ValueError) rather than silently succeeding."""
    src = "PRESENT: int = 1\n"
    with pytest.raises((KeyError, ValueError)):
        _apply_symbol_patch(src, "ABSENT", "ABSENT: int = 2\n")


def test_annassign_primary_non_unique_name_rejected():
    """If the assigned name is bound by more than one top-level statement, the
    primary target is ambiguous and must be rejected (not silently pick one).
    Pinned as RED/GREEN-stable: must raise (KeyError on HEAD, KeyError/ValueError
    after)."""
    src = (
        "DUP: int = 1\n"
        "DUP = 2\n"
    )
    with pytest.raises((KeyError, ValueError)):
        _apply_symbol_patch(src, "DUP", "DUP: int = 99\n")


# ---------------------------------------------------------------------------
# REGRESSION oracles (GREEN before AND after P-UNB1)
# ---------------------------------------------------------------------------

def test_functiondef_primary_still_works():
    """Existing FunctionDef primary targeting is byte-identical, unaffected."""
    src = (
        "MAX_RETRIES: int = 3\n"
        "\n"
        "def foo():\n"
        "    return 1\n"
        "\n"
        "def bar():\n"
        "    return 2\n"
    )
    out = _apply_symbol_patch(src, "foo", "def foo():\n    return 99\n")
    expected = (
        "MAX_RETRIES: int = 3\n"
        "\n"
        "def foo():\n"
        "    return 99\n"
        "\n"
        "def bar():\n"
        "    return 2\n"
    )
    assert out == expected


def test_classdef_primary_still_works():
    """Existing ClassDef primary targeting is unaffected."""
    src = (
        "class A:\n"
        "    x = 1\n"
        "\n"
        "Y: int = 5\n"
    )
    out = _apply_symbol_patch(src, "A", "class A:\n    x = 2\n")
    expected = (
        "class A:\n"
        "    x = 2\n"
        "\n"
        "Y: int = 5\n"
    )
    assert out == expected


def test_decorated_functiondef_primary_still_works():
    """Decorator extension on a FunctionDef primary stays intact (regression)."""
    src = (
        "@staticmethod\n"
        "def g():\n"
        "    return 0\n"
    )
    out = _apply_symbol_patch(src, "g", "@staticmethod\ndef g():\n    return 1\n")
    assert out == "@staticmethod\ndef g():\n    return 1\n"


def test_drift_guard_only_tracks_named_nodes():
    """Intent confirmation (ii)/(iii): the whole-file drift-guard at
    git_integration.py:735-749 keys on getattr(n,'name',None), so AnnAssign /
    single-Name Assign nodes carry no '.name' and are INVISIBLE to it. This
    mirrors that guard's logic to document the intended behavior: an AnnAssign
    edit does not register as a 'changed existing top-level symbol'."""
    code = "X: int = 1\nY = 2\ndef f():\n    return X\n"
    named = {n.name for n in ast.parse(code).body if getattr(n, "name", None) is not None}
    # Only the FunctionDef has a .name; the AnnAssign/Assign do not.
    assert named == {"f"}
