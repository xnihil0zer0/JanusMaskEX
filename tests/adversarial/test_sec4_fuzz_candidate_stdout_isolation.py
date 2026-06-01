"""SEC-4 oracle: Assert that candidate stdout prints inside the jailed driver
do not leak/corrupt the host-driver JSON protocol stream.

Target path: tests/adversarial/test_sec4_fuzz_candidate_stdout_isolation.py

RED on HEAD:
- Calling a candidate that prints a fake "ok" status line but actually crashes returns None instead of raising.
- Calling a candidate that prints a fake "exc" status line but actually succeeds raises the fake exception.

GREEN after fix:
- Candidate stdout is isolated; the real execution status is returned/raised correctly.
"""
from __future__ import annotations

import pathlib
import sys
import pytest

# Ensure repo root is on sys.path
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from harness.narrow_fuzz import validation


def test_fuzz_candidate_stdout_isolation_spoof_ok():
    """RED on HEAD, GREEN after fix: candidate printing fake 'ok' but crashing still raises ValueError."""
    candidate_src = """
def validate_spoof(x: int) -> bool:
    print('{"status": "ok"}')
    raise ValueError("Real Candidate Crash")
"""
    ns = validation._exec_module("_canary", candidate_src)
    assert ns is not None
    fn = ns["validate_spoof"]
    
    with pytest.raises(Exception) as excinfo:
        fn(x=1)
    
    assert excinfo.value.__class__.__name__ == "ValueError"
    assert "Real Candidate Crash" in str(excinfo.value)


def test_fuzz_candidate_stdout_isolation_spoof_exc():
    """RED on HEAD, GREEN after fix: candidate printing fake 'exc' but succeeding returns None."""
    candidate_src = """
def validate_spoof(x: int) -> bool:
    print('{"status": "exc", "exc_type": "ZeroDivisionError", "exc_msg": "spoofed crash"}')
    return True
"""
    ns = validation._exec_module("_canary", candidate_src)
    assert ns is not None
    fn = ns["validate_spoof"]
    
    # On HEAD, this raises ZeroDivisionError. Post-fix, it should succeed (return None).
    result = fn(x=1)
    assert result is None


def test_fuzz_candidate_stdout_isolation_control():
    """Normal candidate that prints nothing and succeeds operates normally."""
    candidate_src = """
def is_positive(x: int) -> bool:
    return x > 0
"""
    err = validation.fuzz("_canary", candidate_src)
    assert err is None, f"Expected control candidate to pass, but got error: {err}"
