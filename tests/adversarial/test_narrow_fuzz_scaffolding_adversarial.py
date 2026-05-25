"""W77b.1 scaffolding contract: ``harness/narrow_fuzz/`` import surface.

These tests pin the design contract before per-type modules land:

1. The package imports cleanly (no circular deps).
2. ``run_narrow_fuzz`` returns ``None`` for any unregistered
   ``meta_task_type`` — preserving bypass semantics per brief §G3.
3. The W77b.1 stub registry returns ``None`` for ``"validation"``
   (entry maps to ``None``, not yet wired to ``validation.fuzz``).
4. Calling ``run_narrow_fuzz`` does not raise on empty/large/non-Python
   ``module_src`` strings — dispatch must be source-agnostic when no
   per-type module is registered.
"""
from __future__ import annotations

import pathlib
import sys


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))


def test_narrow_fuzz_import_is_clean():
    import importlib

    pkg = importlib.import_module("harness.narrow_fuzz.__init__")
    assert callable(pkg.run_narrow_fuzz)
    from harness.narrow_fuzz._registry import REGISTRY

    assert isinstance(REGISTRY, dict)


def test_unregistered_meta_task_type_returns_none():
    from harness.narrow_fuzz import run_narrow_fuzz

    result = run_narrow_fuzz("totally_made_up_type", "_mod", "x = 1")
    assert result is None


def test_validation_registry_entry_present():
    """Registry pins ``validation`` to a callable post-W77b.2 (or None pre-W77b.2)."""
    from harness.narrow_fuzz._registry import REGISTRY

    assert "validation" in REGISTRY
    entry = REGISTRY["validation"]
    assert entry is None or callable(entry)


def test_validation_dispatch_returns_none_on_no_validators():
    """Dispatching a candidate with no validator-shaped functions returns None."""
    from harness.narrow_fuzz import run_narrow_fuzz

    assert run_narrow_fuzz("validation", "_mod", "x = 1") is None


def test_dispatch_does_not_evaluate_source_when_unregistered():
    """Source-agnostic dispatch: malformed Python must not raise on skip."""
    from harness.narrow_fuzz import run_narrow_fuzz

    assert run_narrow_fuzz("nope", "_mod", "this is not python (((") is None
    assert run_narrow_fuzz("nope", "_mod", "") is None


def test_timeout_kwarg_is_keyword_only():
    """The brief mandates ``timeout`` is keyword-only on the public API."""
    import inspect

    from harness.narrow_fuzz import run_narrow_fuzz

    sig = inspect.signature(run_narrow_fuzz)
    timeout_param = sig.parameters["timeout"]
    assert timeout_param.kind == inspect.Parameter.KEYWORD_ONLY
    assert timeout_param.default == 5.0
