"""RED oracle for the daemon epic-kickoff hallucination guard (NGv2 Epic-3).

Bug: ``_check_hallucination`` treats any plan with no ``tasks`` list as an
``empty_plan`` hallucination. An EPIC plan legitimately has NO ``tasks`` — it
carries ``child_slugs`` + ``child_briefs``. So a daemon-driven *epic* plan
kickoff (root -> sub-epic) is mis-flagged ``empty_plan`` and discarded, and no
sub-epic plan ever persists. This blocks the whole multi-level run.

Fix: before the ``tasks`` check (but after the ``wall < min_wall`` guard),
special-case ``plan_kind == 'epic'`` — a non-empty ``child_slugs`` list is a
valid decomposition ``(False, '')``; an empty/missing one is ``(True,
'empty_epic')``. Leaf-plan logic stays unchanged.
"""
from __future__ import annotations

from harness.autowork_daemon import _check_hallucination


def test_epic_plan_with_child_slugs_is_not_hallucinated() -> None:
    plan = {
        'plan_kind': 'epic',
        'epic_slug': 'ngv2_epic3',
        'child_slugs': ['ngv2-intake', 'ngv2-triage'],
        'child_briefs': [{'slug': 'ngv2-intake'}, {'slug': 'ngv2-triage'}],
    }
    halluc, why = _check_hallucination(plan, wall_seconds=30.0)
    assert halluc is False, f'valid epic decomposition flagged as halluc: {why!r}'
    assert why == ''


def test_epic_plan_with_empty_child_slugs_is_hallucinated() -> None:
    plan = {'plan_kind': 'epic', 'child_slugs': []}
    halluc, why = _check_hallucination(plan, wall_seconds=30.0)
    assert halluc is True
    assert why == 'empty_epic'


def test_epic_plan_with_missing_child_slugs_is_hallucinated() -> None:
    plan = {'plan_kind': 'epic'}
    halluc, why = _check_hallucination(plan, wall_seconds=30.0)
    assert halluc is True
    assert why == 'empty_epic'


def test_sub_min_wall_epic_still_flagged_wall() -> None:
    plan = {'plan_kind': 'epic', 'child_slugs': ['a', 'b']}
    halluc, why = _check_hallucination(plan, wall_seconds=2.0)
    assert halluc is True
    assert why == 'wall<min'


def test_leaf_plan_with_tasks_unchanged() -> None:
    plan = {'tasks': [{'task_id': 'T', 'attribution_metadata': {'proposed_by': 'claude', 'reconciled': True}}]}
    halluc, why = _check_hallucination(plan, wall_seconds=30.0)
    assert halluc is False
    assert why == ''


def test_leaf_plan_without_tasks_still_empty_plan() -> None:
    plan = {'tasks': []}
    halluc, why = _check_hallucination(plan, wall_seconds=30.0)
    assert halluc is True
    assert why == 'empty_plan'
