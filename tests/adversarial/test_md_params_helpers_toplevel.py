"""MD-PARAMS de-hand-land structural oracle (REV27 §3 step 3).

The MD-PARAMS helpers ``_is_staticmethod`` and ``_param_strategies`` were
hand-landed (d190289) as NESTED functions inside ``extract_class_interface``
because the partial_edit symbol applier cannot address nested functions (only
top-level FunctionDef/ClassDef). De-hand-landing promotes them to module level
so they become pipeline-maintainable, while preserving behavior (the existing
``test_md_params.py`` behavioral oracle must stay GREEN).

This oracle asserts the promotion: both helpers must be importable as
module-level attributes of ``harness.diff_fuzzer``, and ``extract_class_interface``
must still extract a parameter-strategy interface correctly after the refactor.

RED before the de-hand-land (helpers are nested -> not module attributes);
GREEN after the pipeline promotes them to top level.
"""
from __future__ import annotations

import inspect

import harness.diff_fuzzer as df


def test_is_staticmethod_is_module_level():
    fn = getattr(df, "_is_staticmethod", None)
    assert fn is not None and inspect.isfunction(fn), (
        "_is_staticmethod must be a module-level function of harness.diff_fuzzer "
        "(promoted from nested to top-level for pipeline-addressability)"
    )
    # Module-level => its __qualname__ has no enclosing-function dotted prefix.
    assert "." not in fn.__qualname__, (
        "_is_staticmethod must be top-level, not nested (qualname=%r)" % (fn.__qualname__,)
    )


def test_param_strategies_is_module_level():
    fn = getattr(df, "_param_strategies", None)
    assert fn is not None and inspect.isfunction(fn), (
        "_param_strategies must be a module-level function of harness.diff_fuzzer"
    )
    assert "." not in fn.__qualname__, (
        "_param_strategies must be top-level, not nested (qualname=%r)" % (fn.__qualname__,)
    )


def test_extract_class_interface_still_extracts_params_after_promotion():
    """Behavior preserved: a simple class still yields per-method param strategies,
    and a @staticmethod is detected (no implicit self stripped)."""
    code = (
        "class Acc:\n"
        "    def __init__(self, base):\n"
        "        self.v = base\n"
        "    def add(self, x):\n"
        "        self.v += x\n"
        "    @staticmethod\n"
        "    def combine(a, b):\n"
        "        return a + b\n"
    )
    iface = df.extract_class_interface(code, "Acc")
    assert iface is not None
    assert "add" in iface["methods"]
    # The @staticmethod 'combine' must expose BOTH params (no self stripped).
    combine = iface["methods"]["combine"]
    assert set(combine.keys()) == {"a", "b"}, combine
