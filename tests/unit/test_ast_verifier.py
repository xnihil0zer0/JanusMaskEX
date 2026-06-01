import pytest
from services.neurosymbolic.ast_verifier import ASTVerifier


def test_syntax_validation():
    v = ASTVerifier()
    # Good syntax
    assert v.verify("x = 1").valid
    # Bad syntax
    assert not v.verify("def foo(").valid


def test_bare_except():
    v = ASTVerifier()
    # Bare except: block still an ERROR (interceptor/enforcer agree)
    assert not v.verify("try:\n    pass\nexcept:\n    pass").valid
    # except Exception: pass is now VALID (downgraded to WARNING for interceptor parity)
    res = v.verify("try:\n    pass\nexcept Exception:\n    pass")
    assert res.valid
    assert any(
        violation.rule == "except_exception_pass" and violation.severity == "WARNING"
        for violation in res.violations
    )
    # except with logging/handling should pass
    assert v.verify("try:\n    pass\nexcept Exception as e:\n    print(e)").valid


def test_non_determinism():
    v = ASTVerifier()
    # unseeded random
    res = v.verify("import random\nrandom.random()")
    assert any(violation.rule == "unseeded_random" for violation in res.violations)

    # seeded random should pass unseeded check
    res_seeded = v.verify("import random\nrandom.seed(42)\nrandom.random()")
    assert not any(violation.rule == "unseeded_random" for violation in res_seeded.violations)

    # time.time
    res_time = v.verify("import time\ntime.time()")
    assert any(violation.rule == "non_determinism" for violation in res_time.violations)

    # uuid.uuid4
    res_uuid = v.verify("import uuid\nuuid.uuid4()")
    assert any(violation.rule == "non_determinism" for violation in res_uuid.violations)


def test_recursion_depth():
    v = ASTVerifier()
    # Recursive function calls
    res = v.verify("def foo():\n    foo()")
    assert any(violation.rule == "recursion" for violation in res.violations)

    # Normal function call does not trigger
    res_normal = v.verify("def bar():\n    pass\ndef foo():\n    bar()")
    assert not any(violation.rule == "recursion" for violation in res_normal.violations)


def test_dangerous_shell():
    v = ASTVerifier()
    # Dangerous shell keywords inside strings
    res = v.verify("cmd = 'rm -rf /'")
    assert any(violation.rule == "dangerous_shell" for violation in res.violations)


def test_credential_leak():
    v = ASTVerifier()
    # OpenAI sk- token
    res = v.verify("key = 'sk-abcdefghijklmnopqrstuvwxyz012345'")
    assert not res.valid
    assert any(violation.rule == "credential_leak" for violation in res.violations)


def test_devnull_comment():
    v = ASTVerifier()
    # Commented devnull is fine
    assert v.verify("cmd = 'ls 2>/dev/null'  # expected error suppression").valid
    # Uncommented devnull is warned
    res = v.verify("cmd = 'ls 2>/dev/null'")
    assert any(violation.rule == "devnull_no_comment" for violation in res.violations)
