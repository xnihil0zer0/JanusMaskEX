"""Adversarial battery for harness.embedded_test_runner (DD6-cat2).

Closes the W64 silent-canary defect row 2 (float ``==`` in embedded tests)
documented in ``brief_hooks_silent_canary_signals.md``. The runner's scrub
policy follows ``brief_hooks_dd6_post_w71_decisions.md`` §3 Decision B:
``PYTHONPATH`` is relaxed to expose pytest's site-packages directory while
all other scrub guarantees match :mod:`harness.sandbox_smoke`.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from harness.embedded_test_runner import (  # noqa: E402
    run_embedded_tests,
    should_run_embedded_tests,
)


def test_ieee754_flake_reproduces_pathology_pattern():
    """Row 2 of the silent-canary table: float == in an embedded test.

    The W64 defect shipped because ``0.1 + 0.2 == 0.3`` evaluates False
    under IEEE-754 yet bypass+validate_code let it through. A real test
    execution catches it deterministically.
    """
    src = "def test_bounded():\n    assert 0.1 + 0.2 == 0.3\n"
    err = run_embedded_tests("ieee754_flake", src)
    assert err is not None
    # The failing assertion text should surface in pytest output.
    assert "embedded tests failed" in err


def test_timeout_infinite_loop():
    src = "def test_hang():\n    import time\n    time.sleep(60)\n"
    err = run_embedded_tests("hang_mod", src, timeout=1.0)
    assert err is not None
    lowered = err.lower()
    assert "timed out" in lowered or "timeout" in lowered


def test_import_error_in_module():
    src = (
        "import nonexistent_pkg_xyz_12345  # noqa: F401\n"
        "\n"
        "def test_noop():\n"
        "    pass\n"
    )
    err = run_embedded_tests("bad_import", src)
    assert err is not None
    # Collect-only phase surfaces the ImportError before tests run.
    assert "embedded tests" in err or "collect" in err


def test_all_tests_pass():
    src = "def test_ok():\n    assert 1 == 1\n"
    t0 = time.monotonic()
    result = run_embedded_tests("green_mod", src)
    elapsed = time.monotonic() - t0
    # Realistic embedded-test run time pinned here for W75 reporting.
    assert elapsed < 10.0, f"one-test run took {elapsed:.2f}s (>10s)"
    assert result is None


def test_gate_skips_module_with_no_tests(monkeypatch):
    """Gate: no top-level test_* / Test* -> no subprocess launched."""
    src = "def foo():\n    return 1\n"
    assert should_run_embedded_tests(src) is False

    import harness.embedded_test_runner as etr

    called = {"n": 0}

    def boom(*a, **kw):  # pragma: no cover - must not execute
        called["n"] += 1
        raise AssertionError("subprocess must not be launched when no tests")

    monkeypatch.setattr(etr.subprocess, "run", boom)
    assert run_embedded_tests("no_tests_mod", src) is None
    assert called["n"] == 0


def test_gate_detects_test_function():
    assert should_run_embedded_tests("def test_x():\n    pass\n") is True


def test_gate_detects_test_class():
    assert should_run_embedded_tests(
        "class TestThing:\n    def test_x(self):\n        pass\n"
    ) is True


def test_gate_returns_false_on_syntax_error():
    assert should_run_embedded_tests("def (:\n") is False
