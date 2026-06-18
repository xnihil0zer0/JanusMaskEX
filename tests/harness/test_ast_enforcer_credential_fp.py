"""RED oracle for the hardcoded-credential false-positive narrowing.

Drives the public ``validate_code`` entrypoint on inline code strings and
asserts the DESIRED post-fix behaviour of the hardcoded-credential rule:

  * benign field-name / provenance / dict-key string constants are NOT
    flagged (even when the variable name contains the ``key`` segment), while
  * real hardcoded secrets ARE still flagged with rule ``'security'`` and
    severity ``'error'``.

The oracle is RED on HEAD (benign ``..._KEY`` constants are flagged today
because the rule gates only on the variable *name*, not the string *value*)
and GREEN once the two visitor methods narrow on the value. It touches no
source and is fully hermetic: inline code strings only, no network, no live
``state/`` directory, no shared global state.
"""
from __future__ import annotations
import textwrap
from harness.ast_enforcer import validate_code
_CRED_PREFIX = 'Hardcoded credential detected'
_BAN_SUBSTRING = 'is banned for security reasons'

def _credential_findings(src: str):
    """Return only the hardcoded-credential 'security' violations for *src*.

    Filters by rule == 'security' AND message prefix so that other 'security'
    findings (e.g. the eval/exec ban) never leak into the credential
    assertions.
    """
    return [v for v in validate_code(src) if v.rule == 'security' and v.message.startswith(_CRED_PREFIX)]

def test_benign_field_name_constants_not_flagged() -> None:
    """Plain-assign benign field-name/provenance/key constants are CLEAN."""
    benign_cases = ['JM_PROVENANCE_KEY = "jm_provenance"', 'STATUS_KEY = "status"', 'PRIMARY_KEY = "id"']
    for src in benign_cases:
        findings = _credential_findings(src)
        assert findings == [], f'benign constant should not be flagged as a credential: {src!r} -> {findings!r}'

def test_benign_annotated_assignment_not_flagged() -> None:
    """Annotated benign assignment (visit_AnnAssign) is CLEAN like plain assign."""
    src = 'FIELD_KEY: str = "jm_field_name"'
    findings = _credential_findings(src)
    assert findings == [], f'benign annotated constant should not be flagged: {src!r} -> {findings!r}'

def test_real_secrets_still_flagged_security_error() -> None:
    """Real hardcoded secrets STILL produce a 'security' / 'error' finding."""
    secret_cases = ['PASSWORD = "hunter2pass"', 'API_KEY = "sk-AbC123XyZ789secret"', 'AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"']
    for src in secret_cases:
        findings = _credential_findings(src)
        assert findings, f'real secret should be flagged as a credential: {src!r}'
        for v in findings:
            assert v.rule == 'security', f"expected rule 'security' for {src!r}, got {v.rule!r}"
            assert v.severity == 'error', f"expected severity 'error' for {src!r}, got {v.severity!r}"
            assert v.message.startswith(_CRED_PREFIX)

def test_real_secret_annotated_assignment_flagged() -> None:
    """Annotated secret assignment (visit_AnnAssign) STILL errors."""
    src = 'TOKEN: str = "AbC123XyZ789tok"'
    findings = _credential_findings(src)
    assert findings, f'annotated secret should be flagged: {src!r}'
    assert all((v.severity == 'error' for v in findings))
    assert all((v.rule == 'security' for v in findings))

def test_secret_value_with_special_char_flagged() -> None:
    """A value that clears the gate via a non-identifier char ('/') is flagged."""
    src = textwrap.dedent('\n        AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"\n        ')
    findings = _credential_findings(src)
    assert findings, f"secret with '/' should be flagged: {src!r}"
    assert findings[0].severity == 'error'

def test_filtered_credential_findings_helper_behavior() -> None:
    """The credential filter discriminates benign from secret on the same name."""
    benign = _credential_findings('API_KEY = "status"')
    secret = _credential_findings('API_KEY = "sk-AbC123XyZ789secret"')
    assert benign == [], f'benign value under a key-like name must be clean: {benign!r}'
    assert secret, 'secret value under a key-like name must be flagged'
    assert all((v.rule == 'security' and v.message.startswith(_CRED_PREFIX) for v in secret))

def test_eval_ban_unweakened_is_banned_for_security_reasons() -> None:
    """Regression: the eval ban is unweakened by the credential narrowing."""
    findings = [v for v in validate_code('eval(x)') if v.rule == 'security' and _BAN_SUBSTRING in v.message]
    assert findings, "eval(x) must still produce a 'security' ban violation"
    assert findings[0].severity == 'error'
    assert _BAN_SUBSTRING in findings[0].message

def test_empty_and_short_benign_values_not_flagged() -> None:
    """Regression: empty-string and very-short benign values are not flagged."""
    for src in ('KEY = ""', 'KEY = "id"'):
        findings = _credential_findings(src)
        assert findings == [], f'empty/short benign value should not be flagged: {src!r} -> {findings!r}'