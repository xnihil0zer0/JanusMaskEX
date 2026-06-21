"""Oracle tests for harness.git_integration._apply_symbol_patch nested-symbol behaviour.

Drives the REAL ``_apply_symbol_patch`` against inline source fixtures:

  * a normal top-level def patch still applies and is byte-identical (the
    nested-diagnostic branch must NOT fire);
  * a dotted ``Outer.inner`` method patch returns the source with the nested
    def replaced (unambiguous nested scope);
  * a 1-part leaf that is nested inside a single top-level function raises a
    clear ``ValueError`` naming the enclosing scope (NOT the opaque ``KeyError``);
  * a leaf nested inside TWO distinct top-level functions raises ``ValueError``
    listing ALL candidate scopes;
  * a truly-absent name still raises the bare ``KeyError`` (negative control,
    so the diagnostic does not over-fire).

No banned builtins (exec / eval / compile / __import__) are used.
"""
import pytest
from harness.git_integration import _apply_symbol_patch
SRC_TOPLEVEL = 'import os\n\n\ndef alpha(x):\n    return x + 1\n\n\ndef beta(y):\n    return y * 2\n'
NEW_BETA = 'def beta(y):\n    return y * 3\n'
SRC_CLASS = 'class Outer:\n    def method(self, x):\n        return x\n\n    def other(self, y):\n        return y\n'
NEW_METHOD = 'def method(self, x):\n    return x + 100\n'
SRC_NESTED_SINGLE = 'def outer(a):\n    def helper(b):\n        return b + 1\n    return helper(a)\n\n\ndef other(c):\n    return c\n'
NEW_HELPER = 'def helper(b):\n    return b + 99\n'
SRC_NESTED_AMBIGUOUS = 'def first(a):\n    def shared(b):\n        return b\n    return shared(a)\n\n\ndef second(c):\n    def shared(d):\n        return d * 2\n    return shared(c)\n'
NEW_SHARED = 'def shared(b):\n    return b + 1\n'

def test_wiring_reachability():
    """The real symbol is importable, callable, and exercises the happy path."""
    assert callable(_apply_symbol_patch)
    src = 'def f():\n    return 1\n'
    out = _apply_symbol_patch(src, 'f', 'def f():\n    return 2\n')
    assert isinstance(out, str)
    assert 'return 2' in out
    assert 'return 1' not in out

def test_red_to_green_core():
    """A 1-part leaf nested inside a single top-level def -> ValueError (not KeyError).

    On the broken/unmodified code this surfaces as a bare KeyError ('nested
    symbol error'); the correct implementation raises a clear ValueError that
    names the enclosing top-level scope.
    """
    with pytest.raises(ValueError) as exc:
        _apply_symbol_patch(SRC_NESTED_SINGLE, 'helper', NEW_HELPER)
    msg = str(exc.value)
    assert 'helper' in msg
    assert 'outer' in msg
    assert 'nested' in msg.lower()
    assert not isinstance(exc.value, KeyError)

def test_toplevel_symbol_patch_still_byte_identical():
    """A normal top-level def patch applies and is byte-identical to today.

    The nested-diagnostic branch must NOT fire on the success path.
    """
    result = _apply_symbol_patch(SRC_TOPLEVEL, 'beta', NEW_BETA)
    expected = SRC_TOPLEVEL.replace('    return y * 2\n', '    return y * 3\n')
    assert result == expected
    assert 'def alpha(x):\n    return x + 1\n' in result
    assert 'import os\n' in result

def test_ambiguous_nested_name_raises_valueerror():
    """A leaf nested inside TWO distinct top-level functions -> ValueError listing all.

    Not applied, and NOT a KeyError.
    """
    with pytest.raises(ValueError) as exc:
        _apply_symbol_patch(SRC_NESTED_AMBIGUOUS, 'shared', NEW_SHARED)
    msg = str(exc.value)
    assert 'shared' in msg
    assert 'first' in msg
    assert 'second' in msg
    assert not isinstance(exc.value, KeyError)

def test_apply_symbol_patch_dotted_method_replaced():
    """A dotted Outer.inner patch returns the source with the nested def replaced.

    The unambiguous-nested-scope success path (functional requirement 1).
    """
    result = _apply_symbol_patch(SRC_CLASS, 'Outer.method', NEW_METHOD)
    expected = SRC_CLASS.replace('        return x\n', '        return x + 100\n')
    assert result == expected
    assert '        return x + 100\n' in result
    assert '    def other(self, y):\n        return y\n' in result

def test_apply_symbol_patch_absent_name_raises_keyerror():
    """A name that is NEITHER top-level NOR nested anywhere -> bare KeyError.

    Negative control: the nested-symbol diagnostic must not over-fire and
    swallow the truly-absent case.
    """
    with pytest.raises(KeyError) as exc:
        _apply_symbol_patch(SRC_TOPLEVEL, 'does_not_exist', 'def does_not_exist():\n    pass\n')
    assert 'does_not_exist' in str(exc.value)