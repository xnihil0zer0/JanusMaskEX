"""Oracle for harness.planner.blind_draft._coerce_meta_task_types.

Pins the observable contract of the already-landed deterministic pre-validation
pass that coerces well-known non-canonical ``meta_task_type`` aliases (e.g.
``implementation``/``impl``) to their canonical taxonomy value (``data_model``)
in place, leaving canonical values and unknown types untouched for the validator
to reject.

Pure unit oracle: tiny in-memory dicts only, no I/O, no network, no clock, no
randomness. Does NOT modify blind_draft.py, the validator, or the taxonomy.
"""
import pytest
from harness.planner.blind_draft import _coerce_meta_task_types, _META_TASK_TYPE_ALIASES
_DATA_MODEL = 'data_model'

def _task(meta_task_type):
    """A minimal task dict carrying a meta_task_type."""
    return {'meta_task_type': meta_task_type}

def _draft(meta_task_type):
    """A minimal draft wrapping a single task with the given meta_task_type."""
    return {'tasks': [_task(meta_task_type)]}

def _make_full_task(meta_task_type, task_id='t1'):
    """A maximally-complete leaf task mirroring the planner draft schema.

    Built so that the ONLY taxonomy concern is the meta_task_type value, giving
    a clean positive control for the ``unknown_meta_task_type`` validator code.
    """
    return {'task_id': task_id, 'title': 'Example task', 'meta_task_type': meta_task_type, 'priority': 'high', 'dependencies': [], 'files_touched': ['harness/example_model.py'], 'acceptance_criteria': ['The example model exists and behaves.'], 'spec_author': None, 'estimated_complexity': 'low', 'verification_command': 'python -m pytest tests/test_example.py -q', 'spec': {'objective': 'Provide an example data model.', 'functional_requirements': ['The model serializes round-trip.'], 'interfaces': 'harness.example_model.ExampleModel', 'edge_cases': ['Empty input is handled.'], 'non_goals': ['No persistence layer.'], 'implementation_notes': 'Keep it tiny and pure.'}, 'test_spec': {'unit_tests': [{'name': 'test_a'}, {'name': 'test_b'}], 'integration_tests': [], 'property_tests': [], 'regression_tests': [], 'minimum_test_count': 2, 'test_data_requirements': 'Tiny in-memory dicts only.'}, 'token_budget_ratio': {'implementation_tokens': 100, 'test_tokens': 200, 'note': 'test-heavy'}, 'attribution_metadata': {'proposed_by': 'agent', 'reconciled': False, 'diff_resolution': ''}}

def test_imports_helper_and_alias_constant():
    assert callable(_coerce_meta_task_types)
    assert isinstance(_META_TASK_TYPE_ALIASES, dict)
    assert _META_TASK_TYPE_ALIASES['implementation'] == _DATA_MODEL
    assert _META_TASK_TYPE_ALIASES['impl'] == _DATA_MODEL

def test_alias_constant_maps_implementation_and_impl_to_data_model():
    assert 'banana' not in _META_TASK_TYPE_ALIASES
    assert _META_TASK_TYPE_ALIASES['implementation'] == _META_TASK_TYPE_ALIASES['impl'] == _DATA_MODEL

def test_implementation_coerces_in_place_to_data_model():
    draft = _draft('implementation')
    task = draft['tasks'][0]
    result = _coerce_meta_task_types(draft)
    assert result is None
    assert task['meta_task_type'] == _DATA_MODEL
    assert draft['tasks'][0] is task

def test_impl_alias_coerces_to_data_model():
    draft = _draft('impl')
    _coerce_meta_task_types(draft)
    assert draft['tasks'][0]['meta_task_type'] == _DATA_MODEL

def test_mixed_case_impl_and_implementation_coerce_case_insensitively():
    for raw in ('Impl', 'IMPLEMENTATION', '  Implementation  ', 'iMpL'):
        draft = _draft(raw)
        _coerce_meta_task_types(draft)
        assert draft['tasks'][0]['meta_task_type'] == _DATA_MODEL, raw

def test_canonical_types_left_unchanged():
    for canonical in ('data_model', 'test_authoring', 'harness_self_fix'):
        draft = _draft(canonical)
        _coerce_meta_task_types(draft)
        assert draft['tasks'][0]['meta_task_type'] == canonical

def test_unknown_type_without_alias_left_unchanged():
    draft = _draft('banana')
    _coerce_meta_task_types(draft)
    assert draft['tasks'][0]['meta_task_type'] == 'banana'

def test_nonstring_meta_task_type_left_untouched():
    draft = {'tasks': [{'meta_task_type': None}]}
    _coerce_meta_task_types(draft)
    assert draft['tasks'][0]['meta_task_type'] is None

def test_none_draft_is_noop_no_raise():
    assert _coerce_meta_task_types(None) is None

def test_missing_tasks_key_is_noop_no_raise():
    draft = {'not_tasks': 123}
    assert _coerce_meta_task_types(draft) is None
    assert draft == {'not_tasks': 123}

def test_tasks_not_a_list_is_noop_no_raise():
    for bad in ('notalist', {'a': 1}, 42):
        draft = {'tasks': bad}
        assert _coerce_meta_task_types(draft) is None
        assert draft['tasks'] == bad

def test_idempotent_apply_twice_equals_once():
    draft_once = _draft('implementation')
    _coerce_meta_task_types(draft_once)
    draft_twice = _draft('implementation')
    _coerce_meta_task_types(draft_twice)
    _coerce_meta_task_types(draft_twice)
    assert draft_twice == draft_once
    assert draft_twice['tasks'][0]['meta_task_type'] == _DATA_MODEL

def test_idempotence_property_over_alias_and_canonical_inputs():
    inputs = ['implementation', 'impl', 'Impl', 'IMPLEMENTATION', 'data_model', 'test_authoring', 'harness_self_fix', 'banana']
    for value in inputs:
        once = _draft(value)
        _coerce_meta_task_types(once)
        twice = _draft(value)
        _coerce_meta_task_types(twice)
        _coerce_meta_task_types(twice)
        assert twice == once, value

def test_non_dict_task_element_skipped_without_raise():
    draft = {'tasks': [None, 'string', 7, _task('implementation')]}
    assert _coerce_meta_task_types(draft) is None
    assert draft['tasks'][0] is None
    assert draft['tasks'][1] == 'string'
    assert draft['tasks'][2] == 7
    assert draft['tasks'][3]['meta_task_type'] == _DATA_MODEL

def test_full_draft_implementation_task_no_unknown_meta_task_type_violation_after_coercion():
    from harness.planner.plan_validator import validate_plan
    draft = {'tasks': [_make_full_task('implementation')]}
    _coerce_meta_task_types(draft)
    assert draft['tasks'][0]['meta_task_type'] == _DATA_MODEL
    violations = validate_plan(draft)
    codes = {getattr(v, 'code', None) for v in violations}
    assert 'unknown_meta_task_type' not in codes