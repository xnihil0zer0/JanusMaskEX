"""Behavioral RED oracle for the MD-IMPORT + MD-COMPARATOR seam fix (REV25 §3, A4).

`harness.orchestrator.stateful_differential_fuzz` is, on current HEAD, a silent
no-op: it imports `execute_stateful_trace` from `harness.diff_fuzzer` (where the
symbol does NOT exist -- it lives in `harness.sandbox`), the `ImportError` is
swallowed at the top of the function, and it returns `equivalent=True` for EVERY
input. So a known-divergent stateful class pair is wrongly reported equivalent.

This oracle drives the real entrypoint end-to-end (the §0.1 P-I/P-IV behavioral
pattern, modelled after tests/test_diff_fuzzer.py::TestDifferentialFuzz) and
asserts:
  * a divergent pair  -> equivalent is False, populated FuzzFailure
  * an equivalent pair -> equivalent is True

On HEAD it is RED for the RIGHT reason: the divergent assertion fails because the
function silently returns equivalent=True (NOT an import/signature error -- the
ImportError is caught internally and degraded to a skip).

After the atomic MD-IMPORT (import from harness.sandbox) + MD-COMPARATOR
(step-dict comparator replacing the ExecutionResult-shaped `outputs_match` call)
fix lands, it is GREEN.

Hermetic, fast (small explicit max_examples), no network.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from harness.orchestrator import stateful_differential_fuzz

pytest.importorskip("hypothesis")


# A6: harness/config.yaml has NO fuzzing.stateful block, so the budget falls
# back to a hardcoded 100. Pass an explicit config to stay small & deterministic.
_CONFIG = {
    "fuzzing": {"stateful": {"max_examples": 25}, "max_examples": 25},
    "synthesis": {"fuzz_max_examples": 25},
}

# Stateful class whose `inc()` accumulates state and whose `get()`/`inc()` return
# the running total -- the divergence (step by 1 vs 2) shows up in `value_repr`.
# A stable `__repr__` keeps the constructor (step-0) repr deterministic.
_COUNTER_BY_1 = (
    "class Counter:\n"
    "    def __init__(self, start=0):\n"
    "        self.n = start\n"
    "    def inc(self):\n"
    "        self.n += 1\n"
    "        return self.n\n"
    "    def get(self):\n"
    "        return self.n\n"
    "    def __repr__(self):\n"
    "        return 'Counter(%d)' % self.n\n"
)

_COUNTER_BY_2 = (
    "class Counter:\n"
    "    def __init__(self, start=0):\n"
    "        self.n = start\n"
    "    def inc(self):\n"
    "        self.n += 2\n"          # <-- the only behavioral difference
    "        return self.n\n"
    "    def get(self):\n"
    "        return self.n\n"
    "    def __repr__(self):\n"
    "        return 'Counter(%d)' % self.n\n"
)


def test_divergent_stateful_pair_detected():
    """RED on HEAD: silent import-skip reports equivalent=True for a pair that
    visibly diverges (inc by 1 vs inc by 2)."""
    result = stateful_differential_fuzz(
        _COUNTER_BY_1, _COUNTER_BY_2, "Counter", _CONFIG, "gateA_div"
    )
    # The core RED assertion: the fuzzer must NOT silently call this equivalent.
    assert result.equivalent is False, (
        "divergent stateful pair reported equivalent=True "
        "(skipped_reason=%r, error=%r) -- stateful_differential_fuzz is a "
        "silent no-op (broken import / no comparator)"
        % (getattr(result, "skipped_reason", None), getattr(result, "error", None))
    )
    assert result.failures, "divergence found but no FuzzFailure recorded"
    # action_sequence is setattr-injected today (getattr per A4 until MD-SERIALIZE
    # promotes it to a real field).
    assert getattr(result.failures[0], "action_sequence", None) is not None, (
        "FuzzFailure lacks an action_sequence for the divergent step"
    )


def test_equivalent_stateful_pair_not_flagged():
    """The comparator fix must NOT produce a false-divergence storm: an
    identical class pair stays equivalent=True (guards against the import-only,
    no-comparator regression)."""
    result = stateful_differential_fuzz(
        _COUNTER_BY_1, _COUNTER_BY_1, "Counter", _CONFIG, "gateA_eq"
    )
    assert result.equivalent is True, (
        "identical stateful pair wrongly reported divergent "
        "(failures=%r, error=%r) -- comparator false-positive storm"
        % (result.failures, getattr(result, "error", None))
    )
    assert not result.failures, "identical pair produced spurious failures"
