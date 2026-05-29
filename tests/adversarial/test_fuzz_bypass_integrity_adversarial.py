"""Adversarial battery for fuzz / BYPASS agreement-integrity boundaries.

Plan: adversarial_test_plans/02_apply_commit_validation_fuzzing.md §E (E1, E2).
Targets diff_fuzzer.fuzz_from_task fail-closed behavior and the BYPASS gate
functions (run_embedded_tests / smoke_import) that REPLACE the differential
fuzz for BYPASS_FUZZER_TYPES.

HARD: this suite does NOT narrow the BYPASS_FUZZER_TYPES bypass nor weaken the
dual-agent agreement invariant. It only pins that:
  INV-5 a fuzz-infra failure can NEVER surface as equivalent=True, and
  the bypass means "differential fuzz replaced by gates", NOT "no verification".
"""
from __future__ import annotations

import pytest

from harness.diff_fuzzer import (
    FuzzResult,
    build_input_strategy,
    differential_fuzz,
    fuzz_from_task,
)
from harness.embedded_test_runner import run_embedded_tests
from harness.sandbox_smoke import smoke_import


_CFG = {"fuzzing": {"function_level_inputs": 8, "seed": 1},
        "batch_execution": {"enabled": False}}


# --------------------------------------------------------------------------- #
# E2 — fuzz_from_task fail-closed: infra failure never == equivalent True
#       (the dual-agent-agreement integrity boundary) — HIGH priority.
# --------------------------------------------------------------------------- #
class TestE2FuzzFailClosed:
    def test_strategy_build_failure_is_non_equivalent(self):
        """build_input_strategy raising (function not present) -> differential_fuzz
        must return equivalent=False with the documented error. This is the
        agreement-integrity boundary (INV-5): a fuzz-infra failure can NEVER
        surface as equivalent=True."""
        res = differential_fuzz("x = 1\n", "x = 1\n", "missing_fn", _CFG)
        assert isinstance(res, FuzzResult)
        assert res.equivalent is False, (
            "fuzz-infra failure surfaced as equivalent=True — agreement integrity broken")
        assert res.error and "Failed to build input strategy" in res.error

    def test_unknown_annotation_does_NOT_falsely_equate(self):
        """GAP (documented): _strategy_for_annotation catches ALL exceptions
        and falls back to int (diff_fuzzer.py:247-249), and unannotated params
        default to 'int' — so build_input_strategy effectively NEVER raises for
        a function that exists. An unresolvable annotation 'NoSuchType' does NOT
        trip the fail-closed path; it silently fuzzes with an int strategy.

        Here both sides are IDENTICAL, so equivalent=True is correct — but the
        point is the strategy-build fail-closed branch (the documented
        agreement-integrity guard) is unreachable for any well-formed function:
        a genuinely un-fuzzable type is silently coerced to int rather than
        rejected. Severity is bounded because divergence still fuzzes; pin it."""
        code = "def f(x: NoSuchType) -> int:\n    return 1\n"
        # build_input_strategy does not raise on the unknown annotation:
        strat = build_input_strategy(code, "f")
        assert strat is not None
        task = {"constraints": {"function_signature": "def f(x):"}}
        res = fuzz_from_task(code, code, task, _CFG)
        assert res.equivalent is True  # identical code; int fallback fuzzed fine

    def test_function_absent_both_sides_non_bypass_is_non_equivalent_or_skip(self):
        """When the target function is absent from both sides and the task is
        NOT in the bypass set, fuzz_from_task must NOT auto-pass as a genuine
        equivalence: it either skips (skipped_reason) or fails — never a
        silent matching equivalence with real inputs."""
        code = "x = 1\n"  # no function at all
        task = {"constraints": {"function_signature": "def missing(a):"}}
        res = fuzz_from_task(code, code, task, _CFG)
        # No function name resolvable -> documented skip (skipped_reason set),
        # which the orchestrator treats distinctly from a fuzzed agreement.
        assert isinstance(res, FuzzResult)
        if res.equivalent:
            assert res.skipped_reason, (
                "equivalent=True with NO skipped_reason would be agreement-by-omission")

    def test_genuine_divergence_is_non_equivalent(self):
        """Control: two genuinely different impls of the same signature fuzz to
        equivalent=False (the divergence path actually runs)."""
        code_a = "def g(x: int) -> int:\n    return x + 1\n"
        code_b = "def g(x: int) -> int:\n    return x + 2\n"
        task = {"constraints": {"function_signature": "def g(x: int):"}}
        res = fuzz_from_task(code_a, code_b, task, _CFG)
        assert res.equivalent is False


# --------------------------------------------------------------------------- #
# E1 — BYPASS path still runs verification gates (not "no verification")
# --------------------------------------------------------------------------- #
class TestE1BypassGatesStillVerify:
    def test_embedded_tests_failing_assertion_returns_error(self):
        """run_embedded_tests must surface a failing embedded test as an error
        string — the bypass gate is a real verification, not a rubber stamp."""
        src = "def test_bad():\n    assert 0.1 + 0.2 == 0.3\n"
        err = run_embedded_tests("cand_fail", src, timeout=30.0)
        assert err is not None, "failing embedded test slipped through the gate"
        assert "embedded tests" in err

    def test_embedded_tests_passing_returns_none(self):
        src = "def test_ok():\n    assert 1 + 1 == 2\n"
        err = run_embedded_tests("cand_ok", src, timeout=30.0)
        assert err is None, f"clean embedded test wrongly flagged: {err!r}"

    def test_embedded_tests_no_tests_returns_none(self):
        # module with no test_* targets -> gate is inert (None)
        assert run_embedded_tests("notests", "x = 1\n", timeout=30.0) is None

    def test_smoke_import_failure_returns_error(self):
        """smoke_import must report an import-time failure (another bypass
        gate that genuinely verifies)."""
        src = "raise RuntimeError('boom at import')\n"
        err = smoke_import("smk_fail", src, timeout=10.0)
        assert err is not None and "sandbox import failed" in err

    def test_smoke_import_clean_returns_none(self):
        assert smoke_import("smk_ok", "y = 2\n", timeout=10.0) is None
