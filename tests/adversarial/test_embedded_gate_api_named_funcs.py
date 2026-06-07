"""RED oracle: the embedded-test gate must not mis-collect ``test_*``-named
*API functions* as pytest test cases.

NGv2 leaf modules legitimately expose public functions whose names start with
``test_`` because their committed oracles import and call them with real
arguments, e.g.::

    from ngv2.tool_registry import test_tool                # API, not a test
    from ngv2.mff_scorer  import test_file_against_parser   # API, not a test

``should_run_embedded_tests`` previously returned True for *any* top-level
``test_*`` FunctionDef, so the gate ran ``pytest`` over the candidate, which
auto-collected ``test_tool(file_path, compile_check=...)`` as a test and
failed at setup with ``fixture 'file_path' not found`` (a deterministic
collection error unrelated to correctness). This blocked the tool_registry and
mff_scorer builds.

Contract: a top-level ``test_*`` function is a genuine pytest target ONLY if it
is runnable in the conftest-less, single-file embedded context — i.e. every
required (no-default) parameter is a pytest builtin fixture — and it is not
explicitly opted out via ``<name>.__test__ = False``. The W64 silent-canary
protection is preserved: a real embedded canary test (no args, or fixture args)
still triggers the gate.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from harness.embedded_test_runner import (  # noqa: E402
    run_embedded_tests,
    should_run_embedded_tests,
)


# --- API-named functions must NOT trigger the gate --------------------------

def test_api_func_with_required_nonfixture_arg_is_not_a_target():
    # Mirrors ngv2.tool_registry.test_tool — a required positional that is not
    # a pytest fixture makes the function un-runnable as a test.
    src = (
        "def test_tool(file_path, compile_check=None):\n"
        "    return True\n"
    )
    assert should_run_embedded_tests(src) is False


def test_api_func_multiple_required_args_is_not_a_target():
    # Mirrors ngv2.mff_scorer.test_file_against_parser(file_path, fmt, runner).
    src = (
        "def test_file_against_parser(file_path, fmt, runner):\n"
        "    return {'result': 'accept'}\n"
    )
    assert should_run_embedded_tests(src) is False


def test_explicit_dunder_test_false_opt_out():
    src = (
        "def test_tool(file_path):\n"
        "    return True\n"
        "test_tool.__test__ = False\n"
    )
    assert should_run_embedded_tests(src) is False


def test_api_only_module_passes_run_embedded_tests():
    # End-to-end: an API-only module is not gated -> run returns None (no error).
    src = (
        "def test_tool(file_path, compile_check=None):\n"
        "    return True\n"
        "def regular_helper():\n"
        "    return 1\n"
    )
    assert run_embedded_tests("api_only_mod", src) is None


# --- genuine pytest tests MUST still trigger the gate (W64 protection) -------

def test_real_canary_no_args_still_triggers():
    src = "def test_bounded():\n    assert 0.1 + 0.2 == 0.3\n"
    assert should_run_embedded_tests(src) is True


def test_real_test_with_builtin_fixture_still_triggers():
    src = "def test_writes(tmp_path):\n    (tmp_path / 'x').write_text('ok')\n"
    assert should_run_embedded_tests(src) is True


def test_mixed_api_and_canary_keeps_gate_on():
    # API test_tool is excluded, but the real canary keeps the gate active and
    # its failing assertion is still caught.
    src = (
        "def test_tool(file_path, compile_check=None):\n"
        "    return True\n"
        "def test_canary():\n"
        "    assert 1 == 2\n"
    )
    assert should_run_embedded_tests(src) is True
    err = run_embedded_tests("mixed_mod", src)
    assert err is not None
    assert "embedded tests failed" in err


def test_test_class_still_triggers():
    src = "class TestThing:\n    def test_x(self):\n        assert True\n"
    assert should_run_embedded_tests(src) is True
