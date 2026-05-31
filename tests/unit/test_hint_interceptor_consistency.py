"""Oracle for PHASE_HINT_INTERCEPTOR_CONSISTENCY.

Drives the downgrade of the `subprocess_no_check` rule in
services/neurosymbolic/ast_verifier.py from severity ERROR -> WARNING so that
the symbolic AST verifier (and the live ASTVerificationInterceptor that gates
submit_code/Write) agrees with the real acceptance gate
harness/ast_enforcer.py:125, which already emits subprocess_no_check as a
'warning'.

RED on HEAD (subprocess_no_check is ERROR): tests 1, 2 and 4 fail (test 1 because
has_errors() is True, test 2 because the violation is emitted at ERROR not WARNING,
test 4 because the interceptor DENIES). Test 3 (os_system narrowness) PASSES on HEAD.
GREEN after the fix (subprocess_no_check is WARNING): all four pass.

Narrowness is guarded: os.system() must REMAIN an ERROR (test 3), and the
downgraded rule must still be emitted as a WARNING, not deleted (test 2).
"""

import textwrap

from services.neurosymbolic.ast_verifier import ASTVerifier


SUBPROCESS_RUN_NO_CHECK = textwrap.dedent(
    """
    import subprocess

    def run_ls():
        return subprocess.run(["ls"])
    """
)

OS_SYSTEM_CODE = textwrap.dedent(
    """
    import os

    def run_ls():
        return os.system("ls")
    """
)


def test_subprocess_run_without_check_is_not_an_error():
    r = ASTVerifier().verify(SUBPROCESS_RUN_NO_CHECK)
    error_msgs = [v.message for v in r.violations if v.severity == "ERROR"]
    assert not r.has_errors(), (
        "subprocess.run() without check=True must not be an ERROR; "
        f"unexpected ERROR-severity violations: {error_msgs}"
    )


def test_subprocess_no_check_emitted_as_warning():
    # NON-VACUITY: the rule must still fire, just at WARNING severity (downgrade,
    # not deletion).
    r = ASTVerifier().verify(SUBPROCESS_RUN_NO_CHECK)
    matches = [
        v
        for v in r.violations
        if v.rule == "subprocess_no_check" and v.severity == "WARNING"
    ]
    all_subproc = [
        (v.severity, v.message) for v in r.violations if v.rule == "subprocess_no_check"
    ]
    assert matches, (
        "expected a subprocess_no_check violation at WARNING severity; "
        f"observed subprocess_no_check violations: {all_subproc}"
    )


def test_os_system_remains_an_error():
    # NARROWNESS GUARD: the fix must not blanket-downgrade other ERROR rules.
    r = ASTVerifier().verify(OS_SYSTEM_CODE)
    assert r.has_errors(), (
        "os.system() must remain an ERROR after the subprocess_no_check downgrade; "
        f"violations: {[(v.rule, v.severity) for v in r.violations]}"
    )


def test_interceptor_allows_subprocess_run_without_check():
    # Ties the fix to the live blocker: the interceptor denies submit_code when
    # verify().has_errors(). After the downgrade it must no longer deny.
    from harness.interceptors import ASTVerificationInterceptor

    result = ASTVerificationInterceptor().pre_tool_use(
        "gemini", "submit_code", {"code": SUBPROCESS_RUN_NO_CHECK}
    )
    assert result is None or result.get("decision") != "deny", (
        "interceptor must not DENY a subprocess.run() without check=True after the "
        f"downgrade; got: {result}"
    )
