"""Paired oracle: prove normalize_plan canonicalizes task priorities before validation.

This file is the committed verification oracle for the implementation task that
teaches ``harness.planner.plan_normalizer.normalize_plan`` to coerce
non-canonical task priorities (``P0``/``P1``/``P2``/``P3``, ints ``1``/``2``/``3``,
Capitalized words) into the canonical lowercase vocabulary
``{critical, high, medium, low}`` while leaving unmappable values and
priority-less tasks untouched, preserving purity/idempotence, and making
``harness.planner.plan_validator.validate_plan`` stop emitting the
``invalid_priority_encoding`` violation.

Run: ``python -m pytest tests/harness/test_planner_priority_normalize.py -q``
"""
from __future__ import annotations
import copy
from typing import Any, Dict, List
from harness.planner.plan_normalizer import normalize_plan
from harness.planner.plan_validator import validate_plan

def _single_task_plan(priority: Any) -> Dict[str, Any]:
    """Tiny in-memory plan whose single task carries ``priority``."""
    return {'tasks': [{'task_id': 't1', 'priority': priority}]}

def _norm_priority(plan: Dict[str, Any]) -> Any:
    """Read the (normalized) priority of the first task back out of a plan."""
    return normalize_plan(plan)['tasks'][0]['priority']

def get_valid_plan() -> Dict[str, Any]:
    """A minimally-valid plan reusing the shape from tests/planner/test_plan_validator.py.

    Top-level keys ``source_brief_path`` / ``source_brief_sha256`` / ``tasks``;
    the single task carries every field validate_plan expects so the ONLY thing
    it can legitimately complain about is the (deliberately non-canonical)
    priority swapped in by the END-TO-END regression tests.
    """
    return {'source_brief_path': 'briefs/example.md', 'source_brief_sha256': '0' * 64, 'tasks': [{'task_id': 't1', 'title': 'Example leaf task', 'meta_task_type': 'data_model', 'priority': 'high', 'dependencies': [], 'files_touched': ['harness/example/widget.py'], 'acceptance_criteria': ['Creates harness/example/widget.py.'], 'spec_author': None, 'estimated_complexity': 'low', 'verification_command': 'python -c "import harness.example.widget"', 'spec': {'objective': 'Build the example widget module.', 'functional_requirements': ['Expose a build() function.']}, 'test_spec': {'unit_tests': [{'name': 'test_widget_builds'}], 'minimum_test_count': 1}, 'token_budget_ratio': {'implementation_tokens': 100, 'test_tokens': 50}, 'attribution_metadata': {'proposed_by': 'test'}}]}

def test_p_codes_map_to_canonical() -> None:
    assert _norm_priority(_single_task_plan('P0')) == 'critical'
    assert _norm_priority(_single_task_plan('P1')) == 'high'
    assert _norm_priority(_single_task_plan('P2')) == 'medium'
    assert _norm_priority(_single_task_plan('P3')) == 'low'

def test_int_codes_map_to_canonical() -> None:
    assert _norm_priority(_single_task_plan(1)) == 'critical'
    assert _norm_priority(_single_task_plan(2)) == 'high'
    assert _norm_priority(_single_task_plan(3)) == 'medium'

def test_capitalized_map_to_lowercase() -> None:
    assert _norm_priority(_single_task_plan('Critical')) == 'critical'
    assert _norm_priority(_single_task_plan('High')) == 'high'
    assert _norm_priority(_single_task_plan('Medium')) == 'medium'
    assert _norm_priority(_single_task_plan('Low')) == 'low'

def test_canonical_passthrough_and_idempotent() -> None:
    assert _norm_priority(_single_task_plan('critical')) == 'critical'
    plan = _single_task_plan('P2')
    once = normalize_plan(plan)
    twice = normalize_plan(once)
    assert twice == once
    assert twice['tasks'][0]['priority'] == 'medium'

def test_unmappable_left_unchanged() -> None:
    assert _norm_priority(_single_task_plan('urgent')) == 'urgent'

def test_no_priority_key_untouched() -> None:
    plan = {'tasks': [{'task_id': 't1'}]}
    out = normalize_plan(plan)
    assert 'priority' not in out['tasks'][0]

def test_double_normalize_equals_single() -> None:
    plan = _single_task_plan('P0')
    single = normalize_plan(plan)
    double = normalize_plan(single)
    assert double == single

def test_normalize_plan_does_not_mutate_input() -> None:
    plan = _single_task_plan('P0')
    before = copy.deepcopy(plan)
    normalize_plan(plan)
    assert plan == before
    assert plan['tasks'][0]['priority'] == 'P0'

def _codes(violations: List[Any]) -> List[str]:
    return [getattr(v, 'code', None) for v in violations]

def test_validate_plan_rejects_P2_before_normalize() -> None:
    plan = get_valid_plan()
    plan['tasks'][0]['priority'] = 'P2'
    violations = validate_plan(plan)
    assert 'invalid_priority_encoding' in _codes(violations)

def test_validate_plan_accepts_priority_after_normalize() -> None:
    plan = get_valid_plan()
    plan['tasks'][0]['priority'] = 'P2'
    violations = validate_plan(normalize_plan(plan))
    assert 'invalid_priority_encoding' not in _codes(violations)