"""Paired oracle: prove ``_coerce_task_priorities`` canonicalizes raw blind-draft
task priorities IN PLACE before the collection-gate validator.

This is the committed verification oracle for the implementation task that adds a
new top-level helper ``harness.planner.blind_draft._coerce_task_priorities`` —
a deterministic, in-place, I/O-free pre-validation pass (mirroring the existing
``_coerce_meta_task_types``) that maps non-canonical P-style task priorities
(``P0``/``P1``/``P2``/``P3``, case-insensitive and whitespace-trimmed) to the
canonical lowercase vocabulary ``{critical, high, medium, low}`` on the RAW agent
draft, while leaving already-canonical values, unmappable values, priority-less
tasks, non-dict task entries and non-list ``draft['tasks']`` untouched.

The load-bearing wiring assertion proves that
``harness.planner.plan_validator.validate_plan`` emits ``invalid_priority_encoding``
for a ``P1`` task BEFORE coercion but no longer emits it AFTER coercion — i.e. the
helper removes exactly the violation that was parking briefs at the blind-draft
collection gate.

Run: ``python -m pytest tests/harness/test_planner_canonical_priority_normalize.py -q``
"""
from __future__ import annotations
import copy
from typing import Any, Dict, List
from harness.planner.blind_draft import _coerce_task_priorities
from harness.planner.plan_validator import validate_plan

def _one_task_draft(priority: Any) -> Dict[str, Any]:
    """A tiny in-memory draft whose single task carries ``priority``."""
    return {'tasks': [{'task_id': 'o', 'priority': priority}]}

def _coerced_priority(priority: Any) -> Any:
    """Coerce a single-task draft in place and read the resulting priority back.

    Exercises the REAL in-place mutation contract: the helper returns ``None``
    and the value is read out of the mutated draft, not from a return value.
    """
    draft = _one_task_draft(priority)
    _coerce_task_priorities(draft)
    return draft['tasks'][0]['priority']

def get_valid_plan() -> Dict[str, Any]:
    """A minimally but fully VALID leaf plan (validate_plan returns no violations).

    Mirrors the field shape of the prior oracle's ``get_valid_plan`` but uses a
    pure-edit ``docs_writing`` task touching a non-sensitive path so the ONLY
    thing ``validate_plan`` can complain about is a deliberately non-canonical
    priority swapped in by the wiring regression test.
    """
    return {'source_brief_path': 'briefs/example.md', 'source_brief_sha256': '0' * 64, 'tasks': [{'task_id': 't1', 'title': 'Example documentation task', 'meta_task_type': 'docs_writing', 'priority': 'high', 'dependencies': [], 'files_touched': ['docs/example_widget.md'], 'acceptance_criteria': ['Documents the example widget.'], 'spec_author': None, 'estimated_complexity': 'low', 'verification_command': 'python -c "print(1)"', 'spec': {'objective': 'Document the example widget.', 'functional_requirements': ['Describe the build() function.'], 'interfaces': 'N/A', 'edge_cases': [], 'non_goals': ['No integration coverage in scope.'], 'implementation_notes': 'Mirror the existing docs style.'}, 'test_spec': {'unit_tests': [{'name': 'test_doc_renders'}], 'integration_tests': [], 'property_tests': [], 'regression_tests': [], 'minimum_test_count': 2, 'test_data_requirements': 'None.'}, 'token_budget_ratio': {'implementation_tokens': 100, 'test_tokens': 200, 'note': 'Docs-heavy.'}, 'attribution_metadata': {'proposed_by': 'test', 'reconciled': False, 'diff_resolution': ''}}]}

def _codes(violations: List[Any]) -> List[str]:
    return [getattr(v, 'code', None) for v in violations]

def test_coerce_task_priorities_p0() -> None:
    draft = _one_task_draft('P0')
    _coerce_task_priorities(draft)
    assert draft['tasks'][0]['priority'] == 'critical'

def test_coerce_task_priorities_p1() -> None:
    draft = _one_task_draft('P1')
    _coerce_task_priorities(draft)
    assert draft['tasks'][0]['priority'] == 'high'

def test_coerce_task_priorities_p2() -> None:
    draft = _one_task_draft('P2')
    _coerce_task_priorities(draft)
    assert draft['tasks'][0]['priority'] == 'medium'

def test_coerce_task_priorities_p3() -> None:
    draft = _one_task_draft('P3')
    _coerce_task_priorities(draft)
    assert draft['tasks'][0]['priority'] == 'low'

def test_coerce_task_priorities_case_whitespace() -> None:
    assert _coerced_priority('p1') == 'high'
    assert _coerced_priority(' P1 ') == 'high'
    assert _coerced_priority('  p0  ') == 'critical'
    assert _coerced_priority('P3 ') == 'low'

def test_coerce_task_priorities_canonical_passthrough() -> None:
    assert _coerced_priority('high') == 'high'
    assert _coerced_priority('critical') == 'critical'
    assert _coerced_priority('medium') == 'medium'
    assert _coerced_priority('low') == 'low'

def test_coerce_task_priorities_idempotent() -> None:
    draft = _one_task_draft('P2')
    _coerce_task_priorities(draft)
    assert draft['tasks'][0]['priority'] == 'medium'
    snapshot = copy.deepcopy(draft)
    _coerce_task_priorities(draft)
    assert draft == snapshot
    assert draft['tasks'][0]['priority'] == 'medium'

def test_coerce_task_priorities_unmappable_untouched() -> None:
    assert _coerced_priority('urgent') == 'urgent'
    assert _coerced_priority(7) == 7

def test_coerce_task_priorities_no_priority_key() -> None:
    draft = {'tasks': [{'task_id': 'o'}]}
    _coerce_task_priorities(draft)
    assert 'priority' not in draft['tasks'][0]

def test_coerce_task_priorities_non_dict_task_skipped() -> None:
    draft = {'tasks': ['not-a-dict', 42, None, {'task_id': 'o', 'priority': 'P1'}]}
    _coerce_task_priorities(draft)
    assert draft['tasks'][0] == 'not-a-dict'
    assert draft['tasks'][3]['priority'] == 'high'

def test_coerce_task_priorities_non_list_tasks_noop() -> None:
    _coerce_task_priorities({'tasks': 'not-a-list'})
    _coerce_task_priorities({'tasks': 123})
    _coerce_task_priorities({})
    _coerce_task_priorities(None)
    _coerce_task_priorities([{'task_id': 'o', 'priority': 'P1'}])
    bad = {'tasks': 'P1'}
    _coerce_task_priorities(bad)
    assert bad == {'tasks': 'P1'}

def test_coerce_task_priorities_in_place_returns_none() -> None:
    draft = _one_task_draft('P1')
    result = _coerce_task_priorities(draft)
    assert result is None
    assert draft['tasks'][0]['priority'] == 'high'

def test_coerce_task_priorities_wiring_assertion() -> None:
    draft = get_valid_plan()
    draft['tasks'][0]['priority'] = 'P1'
    before = _codes(validate_plan(draft))
    assert 'invalid_priority_encoding' in before
    _coerce_task_priorities(draft)
    assert draft['tasks'][0]['priority'] == 'high'
    after = _codes(validate_plan(draft))
    assert 'invalid_priority_encoding' not in after
    assert validate_plan(draft) == []