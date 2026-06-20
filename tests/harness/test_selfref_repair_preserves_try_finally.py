"""RED oracle: repair_selfref_assertions must not corrupt try/finally (or any
node with a legitimately-empty orelse/finalbody) into illegal syntax.

ROOT-CAUSE CONTEXT
------------------
``harness/test_author.SelfRefAssertionRepairer.visit`` pads ANY empty
``body``/``orelse``/``finalbody`` list with ``ast.Pass()``. But a ``Try``
node's ``orelse`` (the ``else:`` clause) and ``finalbody`` are LEGALLY empty
when absent; injecting ``Pass()`` produces an illegal ``try: ... else: pass
finally: ...`` (an ``else`` without ``except``) -> ``SyntaxError: expected
'except' or 'finally' block``. Same hazard for ``For``/``While`` ``orelse``.

This corrupts ANY authored oracle that contains a ``try/finally`` fixture and
also a self-referential assertion the repairer strips -- the repaired source
no longer parses, so the worker's auto-commit fails (witnessed:
claudecap-parallel-isolation-oracle, repaired source had a bogus ``else: pass``
inserted into a ``@contextmanager`` ``try: yield / finally:`` fixture).

CONTRACT (the fix this oracle pins)
-----------------------------------
``repair_selfref_assertions`` must ALWAYS return parseable source. It must not
inject ``Pass()`` into a legitimately-empty ``orelse``/``finalbody`` (or any
field whose emptiness is valid Python). Self-ref assertions are still stripped;
unrelated ``try/finally`` structure is preserved verbatim.

RED on HEAD: the repaired output raises SyntaxError on the try/finally case.
"""
from __future__ import annotations
import ast

from harness.test_author import repair_selfref_assertions


def _assert_parses(code: str, label: str) -> str:
    out = repair_selfref_assertions(code)
    try:
        ast.parse(out)
    except SyntaxError as e:
        raise AssertionError(
            f'{label}: repaired source is not parseable: {e.msg} (line {e.lineno})\n--- repaired ---\n{out}'
        )
    return out


def test_try_finally_with_self_ref_stays_parseable():
    """A @contextmanager try/finally fixture alongside a stripped self-ref
    assertion must remain valid Python (no bogus else: pass)."""
    code = (
        "import contextlib\n"
        "@contextlib.contextmanager\n"
        "def fix():\n"
        "    try:\n"
        "        yield\n"
        "    finally:\n"
        "        pass\n"
        "\n"
        "def test_x():\n"
        "    assert 1 == 1\n"
        "    src = open(__file__).read()\n"
        "    assert 'X' not in src\n"
    )
    out = _assert_parses(code, 'try/finally')
    # self-ref scan stripped, try/finally preserved
    assert 'not in src' not in out
    assert 'else:' not in out  # no bogus else clause injected into the Try
    assert 'finally:' in out


def test_for_else_not_injected():
    """An empty-orelse For loop alongside a stripped self-ref assertion must not
    gain a bogus `else:` clause."""
    code = (
        "def test_y():\n"
        "    for i in range(3):\n"
        "        pass\n"
        "    src = open(__file__).read()\n"
        "    assert 'Z' not in src\n"
    )
    out = _assert_parses(code, 'for/else')
    assert 'not in src' not in out
    assert 'else:' not in out


def test_plain_stripped_assertion_still_works():
    """REGRESSION: the original strip behavior is unchanged for a simple body --
    hasattr checks preserved, source scan removed, output parseable."""
    code = (
        "def test_z():\n"
        "    import harness.autowork_daemon as ad\n"
        "    assert not hasattr(ad, '__JANUSMASK_PATCHES__')\n"
        "    src = open(__file__).read()\n"
        "    assert '__JANUSMASK_PATCHES__' not in src\n"
    )
    out = _assert_parses(code, 'plain')
    assert "hasattr(ad, '__JANUSMASK_PATCHES__')" in out
    assert 'not in src' not in out


def test_no_patch_or_manifest_sentinels_in_module():
    """Anti-cheat: this is an oracle test, not a patch bundle."""
    import harness.test_author as ta
    assert not hasattr(ta, '__JANUSMASK_PATCHES__')
    assert not hasattr(ta, '__JANUSMASK_MANIFEST__')
