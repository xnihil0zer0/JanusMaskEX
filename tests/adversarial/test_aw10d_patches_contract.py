"""Adversarial bar for AW10d (aw10d_patches_contract).

The AW10d-deliverable tests are xfail-strict until the dispatch lands the
``__JANUSMASK_PATCHES__`` partial-edit contract helpers in
``harness/git_integration.py``:

  * ``_parse_patches(code) -> list[dict] | None``  (mirror of ``_parse_manifest``)
  * ``_apply_symbol_patch(source, qualname, new_block) -> str``
  * ``_apply_region_patch(source, sentinel, new_region) -> str``

On accept, DROP the ``AW10D_XFAIL`` decorators (the helpers will then exist and
the strict-xfail will XPASS -> hard-fail, forcing the marker removal), turning
these into permanent regression guards. They assert the same parse + apply
round-trip invariants the task's verification_command checks, split into discrete
pytest cases.

``test_existing_manifest_contract_untouched`` is deliberately NOT decorated: it
guards a PRE-EXISTING invariant (the ``__JANUSMASK_MANIFEST__`` whole-file
contract already ships) and must pass today and forever — AW10d adds the patches
contract in PARALLEL to it, never replacing it.

Rationale: ``harness/orchestrator.py`` (~118 KB) cannot be reproduced whole by
the agents (AST-merge byte budgets) and ``.js`` whole-file replace is unreliable
(one agent echoes verbatim -> no_diff, the other rewrites non-additively). The
patches contract lets an agent emit ONLY the named blocks it changes. Backlog
review rank-1 gap; unblocks the 9+-session-stale G10 orchestrator refactor.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

# AW10d helpers landed via dogfood (commit 8f9921c, session #26); the strict
# xfail markers are dropped — these are now regression guards. AW10D_XFAIL is
# neutralized to an identity decorator so the @AW10D_XFAIL sites run normally.
def AW10D_XFAIL(fn):
    return fn

GI_PATH = pathlib.Path(__file__).resolve().parents[2] / "harness" / "git_integration.py"


def _import_gi():
    import importlib

    import harness.git_integration as gi

    importlib.reload(gi)
    return gi


@AW10D_XFAIL
def test_patches_helpers_defined_at_module_level():
    src = GI_PATH.read_text()
    tree = ast.parse(src)
    fns = {
        n.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {
        "_parse_patches",
        "_apply_symbol_patch",
        "_apply_region_patch",
    }.issubset(fns), f"missing patches helpers: {fns}"


@AW10D_XFAIL
def test_parse_patches_round_trips_symbol_entry():
    gi = _import_gi()
    sub = (
        "__JANUSMASK_PATCHES__ = [\n"
        "    {'file': 'a.py', 'kind': 'symbol', 'name': 'foo',\n"
        "     'code': r'''def foo():\n    return 2\n'''},\n"
        "]\n"
    )
    parsed = gi._parse_patches(sub)
    assert isinstance(parsed, list) and len(parsed) == 1
    e = parsed[0]
    assert e["file"] == "a.py"
    assert e["kind"] == "symbol"
    assert e["name"] == "foo"
    assert "return 2" in e["code"]


@AW10D_XFAIL
def test_parse_patches_round_trips_region_entry():
    gi = _import_gi()
    sub = (
        "__JANUSMASK_PATCHES__ = [\n"
        "    {'file': 'app.js', 'kind': 'region', 'marker': 'BLOCK_A',\n"
        "     'code': r'''const x = 1;\n'''},\n"
        "]\n"
    )
    parsed = gi._parse_patches(sub)
    assert isinstance(parsed, list) and len(parsed) == 1
    e = parsed[0]
    assert e["file"] == "app.js"
    assert e["kind"] == "region"
    assert e["marker"] == "BLOCK_A"


@AW10D_XFAIL
def test_parse_patches_returns_none_on_non_patches_submission():
    gi = _import_gi()
    assert gi._parse_patches("x = 1\n") is None
    # A manifest submission must NOT be mistaken for a patches submission.
    assert gi._parse_patches("__JANUSMASK_MANIFEST__ = {'a.py': 'x = 1'}\n") is None


@AW10D_XFAIL
def test_parse_patches_returns_none_on_unknown_kind():
    gi = _import_gi()
    sub = (
        "__JANUSMASK_PATCHES__ = [\n"
        "    {'file': 'a.py', 'kind': 'wholesale', 'name': 'foo', 'code': 'def foo(): pass'},\n"
        "]\n"
    )
    assert gi._parse_patches(sub) is None


@AW10D_XFAIL
def test_parse_patches_returns_none_on_missing_required_key():
    gi = _import_gi()
    # symbol entry missing 'name'
    sub = (
        "__JANUSMASK_PATCHES__ = [\n"
        "    {'file': 'a.py', 'kind': 'symbol', 'code': 'def foo(): pass'},\n"
        "]\n"
    )
    assert gi._parse_patches(sub) is None


@AW10D_XFAIL
def test_parse_patches_never_raises_on_garbage():
    gi = _import_gi()
    # Syntactically broken source must yield None, never raise.
    assert gi._parse_patches("def (:::") is None


@AW10D_XFAIL
def test_apply_symbol_patch_replaces_only_named_def():
    gi = _import_gi()
    before = "import os\n\ndef foo():\n    return 1\n\ndef bar():\n    return 9\n"
    after = gi._apply_symbol_patch(before, "foo", "def foo():\n    return 2\n")
    assert "return 2" in after
    # Surrounding code untouched.
    assert "import os" in after
    assert "def bar" in after
    assert "return 9" in after
    # Old body gone.
    assert "return 1" not in after


@AW10D_XFAIL
def test_apply_symbol_patch_preserves_byte_exact_neighbors():
    gi = _import_gi()
    before = "HEADER = 1\n\ndef foo():\n    return 1\n\nFOOTER = 2\n"
    after = gi._apply_symbol_patch(before, "foo", "def foo():\n    return 42\n")
    assert after.startswith("HEADER = 1\n")
    assert after.endswith("FOOTER = 2\n")


@AW10D_XFAIL
def test_apply_symbol_patch_raises_keyerror_on_missing_symbol():
    gi = _import_gi()
    before = "def foo():\n    return 1\n"
    with pytest.raises(KeyError):
        gi._apply_symbol_patch(before, "nonexistent", "def nonexistent():\n    pass\n")


@AW10D_XFAIL
def test_apply_region_patch_replaces_between_sentinels():
    gi = _import_gi()
    reg = (
        "# JANUSMASK_REGION:BLOCK_A\n"
        "old line\n"
        "# JANUSMASK_ENDREGION:BLOCK_A\n"
    )
    out = gi._apply_region_patch(reg, "BLOCK_A", "new line\n")
    assert "new line" in out
    assert "old line" not in out


@AW10D_XFAIL
def test_apply_region_patch_preserves_sentinel_lines():
    gi = _import_gi()
    reg = (
        "before\n"
        "# JANUSMASK_REGION:R1\n"
        "x\n"
        "# JANUSMASK_ENDREGION:R1\n"
        "after\n"
    )
    out = gi._apply_region_patch(reg, "R1", "y\n")
    assert "# JANUSMASK_REGION:R1" in out
    assert "# JANUSMASK_ENDREGION:R1" in out
    assert out.startswith("before\n")
    assert out.endswith("after\n")


@AW10D_XFAIL
def test_apply_region_patch_is_language_agnostic_on_js():
    gi = _import_gi()
    js = (
        "function header() {}\n"
        "# JANUSMASK_REGION:CONTROLS\n"
        "var old = 1;\n"
        "# JANUSMASK_ENDREGION:CONTROLS\n"
        "function footer() {}\n"
    )
    out = gi._apply_region_patch(js, "CONTROLS", "var fresh = 2;\n")
    assert "var fresh = 2;" in out
    assert "var old = 1;" not in out
    assert "function header()" in out
    assert "function footer()" in out


@AW10D_XFAIL
def test_apply_region_patch_raises_keyerror_on_missing_sentinel():
    gi = _import_gi()
    with pytest.raises(KeyError):
        gi._apply_region_patch("no sentinels here\n", "ABSENT", "x\n")


def test_existing_manifest_contract_untouched():
    """Pre-existing invariant (NOT an AW10d deliverable, so no xfail).

    Guards that the patches contract is added in PARALLEL to (never replacing)
    the existing ``__JANUSMASK_MANIFEST__`` whole-file contract. Must pass today
    and forever.
    """
    src = GI_PATH.read_text()
    tree = ast.parse(src)
    fns = {
        n.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {"_commit_accepted_output_multi", "_apply_file_to_target"}.issubset(fns)
    assert "commit_accepted_output" in fns
