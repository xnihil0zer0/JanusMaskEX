"""Oracle for B4 ENFORCE_FILE_SIZE_POLICY (warn-only module-size advisory).

Contract under test (currently RED — validate_code has no size rule yet):

  * A source exceeding 1500 lines yields a ``module_too_large`` violation
    with ``severity == 'warning'`` (NEVER ``'error'``).
  * That warning does NOT push any violation into the error partition
    (``severity == 'error'``) that orchestrator._validate_submission uses
    to reject a submission — i.e. an otherwise-clean oversized file has
    zero error-severity violations.
  * A normal small file yields NO ``module_too_large`` violation.
  * The pre-existing validate_code rules still fire (control: the
    ``eval()`` security rule must still produce an error-severity
    violation).

These assertions deliberately fail against the current code because the
size advisory does not exist; the only present violations on a large clean
file are none, so ``module_too_large`` is absent. Commit this oracle BEFORE
the B4 worker run (M2).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from harness.ast_enforcer import validate_code


def _clean_function_lines(n_lines: int) -> str:
    """Build a syntactically-clean, rule-clean module of ~``n_lines`` lines.

    A single function with ``n_lines`` trivial ``x = <i>`` statements. No
    nondeterminism, no banned calls, no side effects, so the ONLY violation
    that should appear (post-B4) is the size advisory.
    """
    body = "\n".join(f"    x{i} = {i}" for i in range(n_lines))
    return f"def big():\n{body}\n    return 0\n"


def _size_violations(violations):
    return [v for v in violations if v.rule == "module_too_large"]


def _errors(violations):
    return [v for v in violations if v.severity == "error"]


def test_oversized_module_yields_warning_not_error():
    # ~1604 lines (def + 1600 body + return + trailing) -> well over 1500.
    src = _clean_function_lines(1600)
    assert src.count("\n") + 1 > 1500
    violations = validate_code(src)
    size_v = _size_violations(violations)
    assert len(size_v) == 1, f"expected one module_too_large violation, got {size_v}"
    assert size_v[0].severity == "warning", (
        f"size violation must be 'warning', got {size_v[0].severity!r}"
    )
    assert size_v[0].severity != "error"


def test_oversized_module_does_not_cause_error_partition():
    # An oversized but otherwise rule-clean module must yield ZERO
    # error-severity violations (so _validate_submission never rejects on
    # size alone).
    src = _clean_function_lines(1600)
    violations = validate_code(src)
    assert _errors(violations) == [], (
        f"oversized clean module must produce no error-severity violations, "
        f"got {[ (v.rule, v.severity) for v in _errors(violations)]}"
    )
    # ...and it must still carry the warning advisory.
    assert len(_size_violations(violations)) == 1


def test_small_module_has_no_size_violation():
    src = "def f() -> int:\n    return 1\n"
    assert src.count("\n") + 1 <= 1500
    violations = validate_code(src)
    assert _size_violations(violations) == [], (
        f"small module must not yield module_too_large, got {_size_violations(violations)}"
    )


def test_existing_rule_still_fires_control():
    # Control: the pre-existing eval() security rule must still produce an
    # error-severity violation after B4. Guards against the change
    # accidentally weakening existing validation.
    src = "def f(s):\n    return eval(s)\n"
    violations = validate_code(src)
    sec = [v for v in violations if v.rule == "security" and v.severity == "error"]
    assert sec, f"expected the eval() security rule to still fire, got {violations}"
    # ...and a small file with a banned call still has no size advisory.
    assert _size_violations(violations) == []
