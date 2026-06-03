"""MD_PARAMS behavioral oracle (REV25 §3 / MD-PARAMS = M-D2).

`extract_class_interface._param_strategies` does `func.args.args[1:]` (drops the
first arg of EVERY method) and ignores `posonlyargs`/`kwonlyargs`.

On HEAD:
  * a @staticmethod's first REAL parameter is wrongly dropped (the `self`-drop
    slice is applied even though a staticmethod has no `self`);
  * positional-only and keyword-only parameters are silently omitted from the
    strategy mapping entirely.

The fix: skip the `[1:]` slice for @staticmethod and enumerate
posonlyargs/kwonlyargs. These assertions are RED on HEAD for exactly those two
reasons and GREEN after the fix.
"""
from harness.diff_fuzzer import extract_class_interface

CODE = """
class Widget:
    def __init__(self, start: int):
        self.value = start

    @staticmethod
    def combine(left: int, right: int) -> int:
        return left + right

    def shift(self, a: int, /, b: int, *, c: int) -> int:
        return self.value + a + b + c
"""


def test_staticmethod_first_param_not_dropped():
    iface = extract_class_interface(CODE, "Widget")
    assert iface is not None
    combine = iface["methods"]["combine"]
    # Both staticmethod params must be present; HEAD drops 'left' via the [1:] slice.
    assert "left" in combine, "staticmethod first param wrongly dropped (the [1:] self-slice)"
    assert "right" in combine


def test_positional_only_and_kwonly_enumerated():
    iface = extract_class_interface(CODE, "Widget")
    shift = iface["methods"]["shift"]
    # 'a' is positional-only, 'c' is keyword-only; HEAD enumerates neither.
    assert "a" in shift, "positional-only param 'a' not enumerated"
    assert "b" in shift
    assert "c" in shift, "keyword-only param 'c' not enumerated"
    # 'self' must still be dropped for a normal instance method.
    assert "self" not in shift
