"""Oracle for PHASE_PARITY2 — submit ⊆ commit AST parity, "bare_except" class.

Drives the REAL submit-time verifier ``ASTVerifier().verify(code)`` in
services/neurosymbolic/ast_verifier.py (``_ASTVisitor.visit_ExceptHandler``,
the ``if node.type is None:`` branch, ~:160-166).

The fix: a bare ``except:`` should be flagged ``bare_except`` at ERROR ONLY
when its body is exactly one ``Pass`` (``len(node.body) == 1 and
isinstance(node.body[0], ast.Pass)``) — matching the COMMIT-time enforcer
harness/ast_enforcer.py ``visit_ExceptHandler`` (:100-104). A bare ``except:``
with a non-Pass body must be downgraded to a ``bare_except`` WARNING (still
reported, non-blocking) so it no longer DENIES at submit while the enforcer
accepts it at commit. This restores the invariant submit ⊆ commit (the live
interceptor harness/interceptors.py:56 blocks only on ERROR).

Same class as the already-landed PARITY-1 fix.

RED on HEAD 8ce100c (verifier ERRORs unconditionally on any bare except):
  - Test A fails: a NON-pass-body bare except yields a bare_except ERROR.
GREEN after the fix: Test A passes (WARNING, not ERROR).
Positive controls (GREEN both before/after):
  - Test B: a pass-body bare except STILL yields a bare_except ERROR.
  - Test C: the enforcer accepts the non-pass-body bare except (parity proof).
"""

import textwrap

from services.neurosymbolic.ast_verifier import ASTVerifier


# Bare `except:` with a NON-pass body (does real work). The enforcer
# (harness/ast_enforcer.py) does NOT flag this; the verifier flags it at ERROR
# on HEAD, which spuriously DENIES legitimate submissions at submit-time.
BARE_EXCEPT_NONPASS = textwrap.dedent(
    """
    import logging


    def risky():
        try:
            do_thing()
        except:
            logging.error("x")
    """
)

# Bare `except:` with a body that is exactly a single `Pass`. The enforcer
# DOES flag this, so it must STAY an ERROR (narrowness guard / positive control).
BARE_EXCEPT_PASS = textwrap.dedent(
    """
    def risky():
        try:
            do_thing()
        except:
            pass
    """
)


def test_A_bare_except_nonpass_body_is_not_a_blocking_error():
    # RED-on-HEAD -> GREEN after fix.
    r = ASTVerifier().verify(BARE_EXCEPT_NONPASS)
    bare_errors = [
        v for v in r.violations
        if v.rule == "bare_except" and v.severity == "ERROR"
    ]
    assert not bare_errors, (
        "a bare `except:` with a non-Pass body must NOT be a blocking ERROR "
        "(the commit-time enforcer accepts it); unexpected bare_except ERRORs: "
        f"{[(v.severity, v.message) for v in r.violations]}"
    )
    assert not r.has_errors(), (
        "submission with a non-Pass-body bare except must not have ANY errors; "
        f"violations: {[(v.rule, v.severity) for v in r.violations]}"
    )


def test_A2_bare_except_nonpass_body_still_emitted_as_warning():
    # NON-VACUITY: the rule must still FIRE, just at WARNING severity
    # (downgrade, not deletion).
    r = ASTVerifier().verify(BARE_EXCEPT_NONPASS)
    warns = [
        v for v in r.violations
        if v.rule == "bare_except" and v.severity == "WARNING"
    ]
    all_bare = [
        (v.severity, v.message) for v in r.violations if v.rule == "bare_except"
    ]
    assert warns, (
        "expected a bare_except violation at WARNING severity for a non-Pass "
        f"body; observed bare_except violations: {all_bare}"
    )


def test_B_bare_except_pass_body_remains_an_error():
    # POSITIVE CONTROL / NARROWNESS GUARD: an exactly-`except: pass` must
    # remain a bare_except ERROR (the enforcer agrees it is an error).
    r = ASTVerifier().verify(BARE_EXCEPT_PASS)
    bare = [
        v for v in r.violations
        if v.rule == "bare_except" and v.severity == "ERROR"
    ]
    assert bare, (
        "an exactly-`except: pass` must remain a bare_except ERROR; "
        f"violations: {[(v.rule, v.severity) for v in r.violations]}"
    )
    assert r.has_errors()


def test_C_enforcer_accepts_nonpass_bare_except_parity():
    # PARITY PROOF (submit ⊆ commit): the commit-time enforcer must NOT raise a
    # bare_except error for the non-Pass-body bare except. If submit now also
    # allows it (Test A), submit ⊆ commit holds for this class.
    # Real public entry: harness.ast_enforcer.validate_code -> list[Violation]
    # (severity is lowercase, e.g. 'error'). visit_ExceptHandler at :100-104.
    from harness.ast_enforcer import validate_code

    violations = validate_code(BARE_EXCEPT_NONPASS)
    bare_errors = [
        v for v in violations
        if v.rule == "bare_except" and str(v.severity).lower() == "error"
    ]
    assert not bare_errors, (
        "commit-time enforcer must NOT flag a non-Pass-body bare except as an "
        f"error (it does not); got: {bare_errors}"
    )
