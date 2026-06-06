"""Hermetic coverage tests closing surviving-mutant gaps m26-m30 on
harness.hooks.rpc.submit_code.

Each test pins, for one mutant, the exact default-argument value or unmutated
literal it changes, so applying the mutant makes the corresponding assertion
fail. All submit_code symbols are reached through the module object so the
full-module non-vacuity stub breaks every test.

Pure-function unit assertions: no filesystem, network, or environment access.
"""
from harness.hooks.rpc import submit_code as rpc_submit_code
from harness.ast_enforcer import Violation
UUID_CODE = 'import uuid\n\ndef make_id():\n    return uuid.uuid4().hex\n'

def _error(i: int) -> Violation:
    """Construct a distinct error-severity Violation with non-empty fields."""
    return Violation(rule=f'rule_{i}', severity='error', line=i, message=f'error message {i}')

def _warning(i: int) -> Violation:
    """Construct a distinct warning-severity Violation with non-empty fields."""
    return Violation(rule=f'warn_rule_{i}', severity='warning', line=100 + i, message=f'warning message {i}')

def test_validate_default_flags_nondeterminism_m26() -> None:
    violations = rpc_submit_code.validate(UUID_CODE)
    errors = [v for v in violations if getattr(v, 'severity', '') == 'error']
    assert len(errors) >= 1, f'validate(UUID_CODE) with default allow_nondeterminism should return at least one error-severity violation; got {violations!r}'

def test_ast_validation_error_overflow_suffix_present_m27() -> None:
    errors = [_error(i) for i in range(8)]
    err = rpc_submit_code.AstValidationError(errors)
    msg = str(err)
    assert '(+' in msg, f"expected overflow suffix '(+' in rendered message: {msg!r}"

def test_ast_validation_error_preview_capped_at_5_m28() -> None:
    errors = [_error(i) for i in range(8)]
    err = rpc_submit_code.AstValidationError(errors)
    msg = str(err)
    assert msg.count('@L') == 5, f"expected exactly 5 '@L' line-markers in preview, got {msg.count('@L')} in {msg!r}"

def test_warnings_from_violations_keeps_only_warnings_m29() -> None:
    mixed = [_warning(0), _error(0), _warning(1), _error(1), _error(2)]
    result = rpc_submit_code.warnings_from_violations(mixed)
    assert len(result) == 2, f'expected 2 warning entries, got {result!r}'
    returned_rules = {d['rule'] for d in result}
    assert returned_rules == {'warn_rule_0', 'warn_rule_1'}, returned_rules

def test_rejected_payload_default_max_show_truncates_at_50_m30() -> None:
    errors = [_error(i) for i in range(60)]
    result = rpc_submit_code.rejected_payload(errors)
    assert len(result['violations']) == 50, f'expected 50 truncated violations, got {len(result['violations'])}'
    assert 'Showing first 50 violations' in result['message'], f'expected truncation marker in message: {result['message']!r}'

def test_warnings_filter_excludes_all_error_severity_entries() -> None:
    mixed = [_error(i) for i in range(4)] + [_warning(i) for i in range(3)]
    result = rpc_submit_code.warnings_from_violations(mixed)
    assert len(result) == 3, f'expected 3 warning entries, got {result!r}'
    error_rules = {f'rule_{i}' for i in range(4)}
    for d in result:
        assert d['rule'] not in error_rules, f'error-severity entry leaked into warnings: {d!r}'

def test_preview_cap_boundary_exactly_five_markers_with_overflow() -> None:
    errors = [_error(i) for i in range(8)]
    msg = str(rpc_submit_code.AstValidationError(errors))
    assert msg.count('@L') == 5, msg
    assert '(+3 more)' in msg, f"expected '(+3 more)' suffix in {msg!r}"

def test_rejected_payload_truncation_boundary_fifty_of_sixty() -> None:
    errors = [_error(i) for i in range(60)]
    result = rpc_submit_code.rejected_payload(errors)
    assert result['status'] == 'rejected'
    assert result['ast_valid'] is False
    assert len(result['violations']) == 50
    assert 'Showing first 50 violations' in result['message']