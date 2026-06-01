import textwrap
from harness.orchestrator import _validate_submission

def test_validator_sig_nonmatching_patch_not_return_type_checked():
    # Build task dict with partial_edit: True and constraints/function_signature
    task = {
        "meta_task_type": "harness_self_fix",
        "partial_edit": True,
        "constraints": {
            "function_signature": "def foo(x: int) -> int:"
        }
    }
    
    # Build code string with TWO symbol patches:
    # 1) name='foo', matching signature, correct return type
    # 2) name='bar', different symbol, valid but no return type (no foo defined in it)
    code = textwrap.dedent(
        """
        __JANUSMASK_PATCHES__ = [
            {
                'file': 'harness/orchestrator.py',
                'kind': 'symbol',
                'name': 'foo',
                'code': 'def foo(x: int) -> int:\\n    return x\\n'
            },
            {
                'file': 'harness/orchestrator.py',
                'kind': 'symbol',
                'name': 'bar',
                'code': 'def bar(y):\\n    return y\\n'
            }
        ]
        """
    ).strip()
    
    ok, violations = _validate_submission(code, 'claude', task)
    assert ok is True, f"Expected validation to pass, but got violations: {violations}"


def test_validator_sig_real_violation_still_caught():
    # Build task dict with partial_edit: True and constraints/function_signature
    task = {
        "meta_task_type": "harness_self_fix",
        "partial_edit": True,
        "constraints": {
            "function_signature": "def foo(x: int) -> int:"
        }
    }
    
    # Build code string with TWO symbol patches, but matching 'foo' has wrong return annotation in body:
    # returns str instead of int
    code = textwrap.dedent(
        """
        __JANUSMASK_PATCHES__ = [
            {
                'file': 'harness/orchestrator.py',
                'kind': 'symbol',
                'name': 'foo',
                'code': 'def foo(x: int) -> str:\\n    return "x"\\n'
            },
            {
                'file': 'harness/orchestrator.py',
                'kind': 'symbol',
                'name': 'bar',
                'code': 'def bar(y):\\n    return y\\n'
            }
        ]
        """
    ).strip()
    
    ok, violations = _validate_submission(code, 'claude', task)
    assert ok is False, "Expected validation to fail due to matching symbol return mismatch"
    # Ensure there is a return_type_mismatch violation
    assert any(v.rule == 'return_type_mismatch' for v in violations), f"Expected return_type_mismatch violation, got: {violations}"
