"""Oracle tests for ``harness.git_integration._apply_symbol_patch``.

These tests drive the REAL ``_apply_symbol_patch`` against inline source
fixtures and assert its observable behaviour exactly as implemented:

  * a normal top-level ``def`` patch applies and is BYTE-IDENTICAL to a plain
    slice replacement (the nested-symbol diagnostic must NOT fire on success);
  * a 1-part bare name that also occurs NESTED is applied to the *top-level*
    definition (first match wins) while the nested same-name def is left
    untouched -- the nested diagnostic must not over-fire when a real top-level
    target exists, and merged text is returned;
  * a dotted ``Outer.method`` patch slice-replaces the direct method;
  * a dotted ``Outer.inner`` whose leaf is nested exactly one level deeper is
    applied via the recursive single-nested path;
  * a 1-part leaf nested inside a SINGLE top-level def raises a clear
    ``ValueError`` naming the enclosing scope (NOT the opaque ``KeyError``);
  * a 1-part leaf nested inside TWO distinct top-level functions raises
    ``ValueError`` listing ALL candidate scopes;
  * truly-absent names (1-part, dotted-member, dotted-outer) raise the bare
    ``KeyError`` (negative controls, so the diagnostic does not over-fire);
  * a patched module is genuinely importable (verified via ``importlib`` -- no
    banned builtins ``exec`` / ``eval`` / ``compile`` / ``__import__`` are used).
"""
import importlib.util
import pytest
from harness.git_integration import _apply_symbol_patch
SRC_TOPLEVEL = 'import os\n\n\ndef alpha(x):\n    return x + 1\n\n\ndef beta(y):\n    return y * 2\n'
NEW_BETA = 'def beta(y):\n    return y * 3\n'
SRC_CLASS = 'class Outer:\n    def method(self, x):\n        return x\n\n    def other(self, y):\n        return y\n'
NEW_METHOD = 'def method(self, x):\n    return x + 100\n'
SRC_ONEPART_TOP_AND_NESTED = 'def helper(b):\n    return b + 1\n\n\ndef outer(a):\n    def helper(c):\n        return c + 7\n    return helper(a)\n'
NEW_HELPER_TOP = 'def helper(b):\n    return b + 100\n'
SRC_NESTED_SINGLE = 'def outer(a):\n    def helper(b):\n        return b + 1\n    return helper(a)\n\n\ndef other(c):\n    return c\n'
NEW_HELPER = 'def helper(b):\n    return b + 99\n'
SRC_NESTED_AMBIGUOUS = 'def first(a):\n    def shared(b):\n        return b\n    return shared(a)\n\n\ndef second(c):\n    def shared(d):\n        return d * 2\n    return shared(c)\n'
NEW_SHARED = 'def shared(b):\n    return b + 1\n'
SRC_CLASS_NESTED = 'class Box:\n    def run(self, x):\n        def shared(y):\n            return y + 1\n        return shared(x)\n'
NEW_SHARED_NESTED = 'def shared(y):\n    return y + 5\n'
SRC_TWO_CLASS = 'class First:\n    value = 1\n\n\nclass Second:\n    value = 2\n'
NEW_FIRST = 'class First:\n    value = 99\n'

def _import_source(src: str, mod_name: str, tmp_path) -> object:
    """Load *src* as a module via importlib (no exec/eval/compile/__import__)."""
    file_path = tmp_path / f'{mod_name}.py'
    file_path.write_text(src, encoding='utf-8')
    spec = importlib.util.spec_from_file_location(mod_name, str(file_path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_wiring_reachability():
    """The real symbol is importable, callable, and exercises the happy path."""
    assert callable(_apply_symbol_patch)
    src = 'def f():\n    return 1\n'
    out = _apply_symbol_patch(src, 'f', 'def f():\n    return 2\n')
    assert isinstance(out, str)
    assert 'return 2' in out
    assert 'return 1' not in out

def test_onepart_nested_bare_name_applied():
    """A 1-part bare name is applied and returns the merged text.

    ``helper`` exists both at top level and nested inside ``outer``. Patching
    the bare ``helper`` must apply to the TOP-LEVEL definition (first match
    wins) and leave the nested same-name def untouched -- the nested-symbol
    diagnostic must NOT fire / shadow a genuine top-level target.
    """
    result = _apply_symbol_patch(SRC_ONEPART_TOP_AND_NESTED, 'helper', NEW_HELPER_TOP)
    expected = SRC_ONEPART_TOP_AND_NESTED.replace('def helper(b):\n    return b + 1\n', 'def helper(b):\n    return b + 100\n')
    assert result == expected
    assert 'def helper(b):\n    return b + 100\n' in result
    assert 'def helper(b):\n    return b + 1\n' not in result
    assert '    def helper(c):\n        return c + 7\n' in result
    assert 'def outer(a):' in result

def test_toplevel_symbol_patch_still_byte_identical():
    """A normal top-level def patch applies and is byte-identical to a slice swap.

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
    assert 'nested' in msg.lower()
    assert not isinstance(exc.value, KeyError)

def test_apply_symbol_patch_single_nested_name_raises_valueerror():
    """A 1-part leaf nested inside a SINGLE top-level def -> ValueError naming it.

    On broken code this would surface as a bare KeyError; the correct
    implementation raises a clear ValueError naming the enclosing scope.
    """
    with pytest.raises(ValueError) as exc:
        _apply_symbol_patch(SRC_NESTED_SINGLE, 'helper', NEW_HELPER)
    msg = str(exc.value)
    assert 'helper' in msg
    assert 'outer' in msg
    assert 'nested' in msg.lower()
    assert not isinstance(exc.value, KeyError)

def test_apply_symbol_patch_dotted_method_replaced():
    """A dotted ``Outer.method`` patch slice-replaces the direct method."""
    result = _apply_symbol_patch(SRC_CLASS, 'Outer.method', NEW_METHOD)
    expected = SRC_CLASS.replace('        return x\n', '        return x + 100\n')
    assert result == expected
    assert '        return x + 100\n' in result
    assert '    def other(self, y):\n        return y\n' in result

def test_apply_symbol_patch_dotted_nested_recursion_applied():
    """A dotted ``Box.shared`` whose leaf is nested one level deeper is applied.

    Exercises the single-nested recursive apply path: ``shared`` lives inside
    ``Box.run`` and is patched in place, every other byte preserved.
    """
    result = _apply_symbol_patch(SRC_CLASS_NESTED, 'Box.shared', NEW_SHARED_NESTED)
    expected = SRC_CLASS_NESTED.replace('            return y + 1\n', '            return y + 5\n')
    assert result == expected
    assert '            return y + 5\n' in result
    assert '            return y + 1\n' not in result
    assert '    def run(self, x):\n' in result

def test_apply_symbol_patch_toplevel_class_replaced():
    """A 1-part top-level class is slice-replaced; sibling class survives."""
    result = _apply_symbol_patch(SRC_TWO_CLASS, 'First', NEW_FIRST)
    expected = SRC_TWO_CLASS.replace('class First:\n    value = 1\n', 'class First:\n    value = 99\n')
    assert result == expected
    assert '    value = 99\n' in result
    assert '    value = 1\n' not in result
    assert 'class Second:\n    value = 2\n' in result

def test_apply_symbol_patch_absent_name_raises_keyerror():
    """A name that is NEITHER top-level NOR nested anywhere -> bare KeyError.

    Negative control: the nested-symbol diagnostic must not over-fire and
    swallow the truly-absent case.
    """
    with pytest.raises(KeyError) as exc:
        _apply_symbol_patch(SRC_TOPLEVEL, 'does_not_exist', 'def does_not_exist():\n    pass\n')
    assert 'does_not_exist' in str(exc.value)

def test_apply_symbol_patch_dotted_absent_member_raises_keyerror():
    """A dotted leaf absent from an existing class (and not nested) -> KeyError."""
    with pytest.raises(KeyError) as exc:
        _apply_symbol_patch(SRC_CLASS, 'Outer.missing', 'def missing(self):\n    return 0\n')
    assert 'Outer.missing' in str(exc.value)

def test_apply_symbol_patch_dotted_outer_absent_raises_keyerror():
    """A dotted qualname whose top-level scope does not exist -> KeyError."""
    with pytest.raises(KeyError) as exc:
        _apply_symbol_patch(SRC_CLASS, 'Ghost.method', 'def method(self):\n    return 0\n')
    assert 'Ghost.method' in str(exc.value)

def test_apply_symbol_patch_importable_after_patch(tmp_path):
    """The patched source is real, importable Python with the new behaviour.

    Uses ``importlib`` (no banned builtins) to load the merged text and
    exercise the patched function's runtime behaviour.
    """
    result = _apply_symbol_patch(SRC_TOPLEVEL, 'beta', NEW_BETA)
    module = _import_source(result, 'patched_toplevel_mod', tmp_path)
    assert hasattr(module, 'os')
    assert module.alpha(4) == 5
    assert module.beta(7) == 21