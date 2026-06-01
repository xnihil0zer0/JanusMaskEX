"""Oracle for PHASE_PARITY3_CREDENTIAL_LEAK.

Drives the downgrade of the `credential_leak` rule in
services/neurosymbolic/ast_verifier.py (visit_Constant, ~line 198-211)
from severity ERROR -> WARNING, so that the symbolic AST verifier
(and the live ASTVerificationInterceptor that gates submit_code/Write)
allows credential/API key patterns in string literals as a warning rather than blocking.

RED on HEAD (credential_leak is ERROR): tests 1, 2 and 4 fail (test 1 because
has_errors() is True, test 2 because the violation is emitted at ERROR not WARNING,
test 4 because the interceptor DENIES). Test 3 (os_system narrowness) PASSES on HEAD.
GREEN after the fix: all four pass.

Narrowness is guarded: os.system() must REMAIN an ERROR (test 3), and the
downgraded rule must still be emitted as a WARNING, not deleted (test 2).
"""

import textwrap

from services.neurosymbolic.ast_verifier import ASTVerifier


CREDENTIAL_CODE = textwrap.dedent(
    """
    def some_function():
        EXAMPLE = "sk-abcdefghijklmnopqrstuvwxyz0123456789"
        return EXAMPLE
    """
)

OS_SYSTEM_CODE = textwrap.dedent(
    """
    import os

    def run_ls():
        return os.system("ls")
    """
)


def test_credential_leak_is_not_an_error():
    r = ASTVerifier().verify(CREDENTIAL_CODE)
    error_msgs = [v.message for v in r.violations if v.severity == "ERROR"]
    assert not r.has_errors(), (
        "credential_leak must not be an ERROR; "
        f"unexpected ERROR-severity violations: {error_msgs}"
    )


def test_credential_leak_emitted_as_warning():
    # NON-VACUITY: the rule must still fire, just at WARNING severity (downgrade,
    # not deletion).
    r = ASTVerifier().verify(CREDENTIAL_CODE)
    matches = [
        v
        for v in r.violations
        if v.rule == "credential_leak" and v.severity == "WARNING"
    ]
    all_cred = [
        (v.severity, v.message) for v in r.violations if v.rule == "credential_leak"
    ]
    assert matches, (
        "expected a credential_leak violation at WARNING severity; "
        f"observed credential_leak violations: {all_cred}"
    )


def test_os_system_remains_an_error():
    # NARROWNESS GUARD: the fix must not blanket-downgrade other ERROR rules.
    r = ASTVerifier().verify(OS_SYSTEM_CODE)
    assert r.has_errors(), (
        "os.system() must remain an ERROR after the credential_leak downgrade; "
        f"violations: {[(v.rule, v.severity) for v in r.violations]}"
    )


def test_interceptor_allows_credential_leak():
    # Ties the fix to the live blocker: the interceptor denies submit_code when
    # verify().has_errors(). After the downgrade it must no longer deny.
    from harness.interceptors import ASTVerificationInterceptor

    result = ASTVerificationInterceptor().pre_tool_use(
        "gemini", "submit_code", {"code": CREDENTIAL_CODE}
    )
    assert result is None or result.get("decision") != "deny", (
        "interceptor must not DENY a credential leak after the "
        f"downgrade; got: {result}"
    )
