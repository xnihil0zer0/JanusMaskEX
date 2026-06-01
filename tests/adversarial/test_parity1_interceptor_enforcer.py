"""Oracle for PHASE_PARITY1_INTERCEPTOR_ENFORCER.

Drives the downgrade of the `except_exception_pass` rule in
services/neurosymbolic/ast_verifier.py (visit_ExceptHandler, ~line 184-189)
from severity ERROR -> WARNING, so the symbolic AST verifier (and the live
ASTVerificationInterceptor that gates submit_code/Write) agrees with the real
acceptance gate harness/ast_enforcer.py:100-104, whose visit_ExceptHandler only
flags a TRULY-BARE `except:` as an error and does NOT flag a typed
`except Exception: pass` at all.

This is the SAME mechanism as PHASE_HINT_INTERCEPTOR_CONSISTENCY
(subprocess_no_check ERROR->WARNING). See tests/unit/test_hint_interceptor_consistency.py.

RED on HEAD (except_exception_pass is ERROR):
  - test 1 fails: has_errors() is True for `except Exception: pass`.
  - test 2 fails: the violation is emitted at ERROR, not WARNING.
  - test 4 fails: the live interceptor DENIES the submission.
  test 3 (bare-except positive control / narrowness) PASSES on HEAD.
GREEN after the fix: all four pass.

Non-vacuity / narrowness guard: a truly-bare `except:` MUST remain an ERROR
(test 3), and the downgraded rule must still be EMITTED (as a WARNING), not
deleted (test 2).
"""

import textwrap

from services.neurosymbolic.ast_verifier import ASTVerifier


# Typed `except Exception:` whose body is only `pass`.  The enforcer
# (harness/ast_enforcer.py) does NOT flag this; the verifier flags it at ERROR
# on HEAD, which spuriously DENIES legitimate submissions.
EXCEPT_EXCEPTION_PASS = textwrap.dedent(
    """
    def safe():
        try:
            do_thing()
        except Exception:
            pass
    """
)

# Truly-bare `except:` -- the enforcer DOES flag this, so it must STAY an ERROR.
BARE_EXCEPT = textwrap.dedent(
    """
    def risky():
        try:
            do_thing()
        except:
            pass
    """
)


def test_except_exception_pass_is_not_an_error():
    r = ASTVerifier().verify(EXCEPT_EXCEPTION_PASS)
    error_msgs = [v.message for v in r.violations if v.severity == "ERROR"]
    assert not r.has_errors(), (
        "typed `except Exception: pass` must not be an ERROR (enforcer does not "
        f"flag it); unexpected ERROR-severity violations: {error_msgs}"
    )


def test_except_exception_pass_emitted_as_warning():
    # NON-VACUITY: the rule must still fire, just at WARNING severity (downgrade,
    # not deletion).
    r = ASTVerifier().verify(EXCEPT_EXCEPTION_PASS)
    matches = [
        v
        for v in r.violations
        if v.rule == "except_exception_pass" and v.severity == "WARNING"
    ]
    all_eep = [
        (v.severity, v.message) for v in r.violations if v.rule == "except_exception_pass"
    ]
    assert matches, (
        "expected an except_exception_pass violation at WARNING severity; "
        f"observed except_exception_pass violations: {all_eep}"
    )


def test_bare_except_remains_an_error():
    # NARROWNESS GUARD / POSITIVE CONTROL: the fix must not blanket-downgrade
    # the genuinely-bare `except:` that the enforcer agrees is an error.
    r = ASTVerifier().verify(BARE_EXCEPT)
    bare = [v for v in r.violations if v.rule == "bare_except" and v.severity == "ERROR"]
    assert bare, (
        "a truly-bare `except:` must remain an ERROR after the "
        "except_exception_pass downgrade; "
        f"violations: {[(v.rule, v.severity) for v in r.violations]}"
    )


def test_interceptor_allows_except_exception_pass():
    # Ties the fix to the live blocker: the interceptor denies submit_code when
    # verify().has_errors(). After the downgrade it must no longer deny.
    from harness.interceptors import ASTVerificationInterceptor

    result = ASTVerificationInterceptor().pre_tool_use(
        "gemini", "submit_code", {"code": EXCEPT_EXCEPTION_PASS}
    )
    assert result is None or result.get("decision") != "deny", (
        "interceptor must not DENY a typed `except Exception: pass` after the "
        f"downgrade; got: {result}"
    )


def test_interceptor_still_denies_bare_except():
    # POSITIVE CONTROL on the interceptor path: a truly-bare `except:` must still
    # be DENIED, proving the interceptor's deny-on-ERROR mechanism is intact.
    from harness.interceptors import ASTVerificationInterceptor

    result = ASTVerificationInterceptor().pre_tool_use(
        "gemini", "submit_code", {"code": BARE_EXCEPT}
    )
    assert result is not None and result.get("decision") == "deny", (
        "interceptor must still DENY a truly-bare `except:`; "
        f"got: {result}"
    )
