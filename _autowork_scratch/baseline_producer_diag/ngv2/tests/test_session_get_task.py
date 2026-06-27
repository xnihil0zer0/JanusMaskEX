"""Mutation-killing tests for ``ngv2.session_get_task.get_task``.

Contract under test (from spec):
    def get_task(session_row: dict) -> dict

* Extracts four required fields -- phase input, target, prior findings and
  parked package -- from a session row and returns them in a canonical task
  dict.
* Fail-closed: dropping ANY single required key must raise (a mutant that
  default-fills the missing key instead of raising must fail these tests).
* Extra keys are ignored; nested values are preserved unmutated.

All session rows are built inline; no database fixtures are used (per non-goal).
"""
import copy
import pytest
from ngv2.session_get_task import get_task
REQUIRED_KEYS = ('phase_input', 'target', 'prior_findings', 'parked_package')

def _valid_row():
    """Build a fresh valid session_row with distinct, nested values.

    Each value is unique so membership checks against the returned dict's
    values are unambiguous, and each is nested so we can verify preservation.
    """
    return {'phase_input': {'phase': 2, 'instructions': ['scan', 'enumerate']}, 'target': {'host': '10.0.0.5', 'ports': [22, 443]}, 'prior_findings': ['weak-creds', {'cve': 'CVE-2024-1234'}], 'parked_package': {'name': 'loader', 'meta': {'version': 1, 'bytes': [0, 1]}}}

def test_all_four_fields_extracted():
    """Positive control: every required field's value survives into the result."""
    row = _valid_row()
    result = get_task(row)
    assert isinstance(result, dict)
    values = list(result.values())
    for key in REQUIRED_KEYS:
        assert row[key] in values, f'value for required field {key!r} missing from returned task'

@pytest.mark.parametrize('missing_key', REQUIRED_KEYS)
def test_missing_each_required_key_raises(missing_key):
    """Fail-closed: dropping any one required key must raise.

    A mutant that default-fills the missing key returns normally and so will
    NOT raise -- failing this test, which is exactly what we want.
    """
    row = _valid_row()
    del row[missing_key]
    with pytest.raises(Exception):
        get_task(row)

def test_empty_dict_raises():
    """Edge case: an empty session row is missing all required keys -> raise."""
    with pytest.raises(Exception):
        get_task({})

@pytest.mark.parametrize('missing_key', REQUIRED_KEYS)
def test_dropping_any_required_key_raises(missing_key):
    """Property: for every required key, omitting it from an otherwise-valid
    row causes a raise (fail-closed across the whole key set)."""
    row = _valid_row()
    row.pop(missing_key)
    with pytest.raises(Exception):
        get_task(row)

def test_valid_row_returns_canonical_task_shape():
    """Integration: a complete valid row yields a dict task carrying all four
    extracted values."""
    row = _valid_row()
    result = get_task(row)
    assert isinstance(result, dict), 'get_task must return a dict task'
    values = list(result.values())
    assert row['phase_input'] in values
    assert row['target'] in values
    assert row['prior_findings'] in values
    assert row['parked_package'] in values

def test_extra_keys_ignored_nested_preserved():
    """Regression: extra keys are ignored and nested values are preserved
    unmutated (compared against an independent deep copy of the inputs)."""
    row = _valid_row()
    row['unrelated_extra'] = {'should': 'be ignored'}
    row['another_extra'] = 12345
    expected = {k: copy.deepcopy(row[k]) for k in REQUIRED_KEYS}
    result = get_task(row)
    assert isinstance(result, dict)
    values = list(result.values())
    for key in REQUIRED_KEYS:
        assert expected[key] in values, f'nested value for {key!r} was not preserved unmutated'
    assert {'should': 'be ignored'} not in values
    assert 12345 not in values