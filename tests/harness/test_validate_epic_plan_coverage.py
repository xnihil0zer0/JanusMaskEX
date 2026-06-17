"""RED oracle: coverage_check.uncovered -> advisory coverage_gap_warning in
harness.planner.plan_validator.validate_epic_plan, with regression guards.

Hermetic, in-memory only. RED on HEAD (coverage_gap_warning never emitted),
GREEN after the sibling implementation. Asserts on violation .code/.severity,
never on exact message strings.
"""
from harness.planner import plan_validator

def _well_formed_brief(slug):
    return {'slug': slug, 'title': slug + ' title', 'scope': 'scope for ' + slug, 'non_goals': [], 'inputs': [], 'deliverables': '- deliver ' + slug}

def _epic_plan(child_slugs, brief_slugs=None, **extra):
    if brief_slugs is None:
        brief_slugs = list(child_slugs)
    plan = {'plan_kind': 'epic', 'epic_slug': 'epic-root', 'child_briefs': [_well_formed_brief(s) for s in brief_slugs], 'child_slugs': list(child_slugs)}
    plan.update(extra)
    return plan

def test_coverage_uncovered_yields_advisory():
    plan = _epic_plan(child_slugs=['alpha'], brief_slugs=['alpha'], coverage_check={'uncovered': ['- orphan deliverable line']})
    violations = plan_validator.validate_epic_plan(plan)
    matches = [v for v in violations if v.code == 'coverage_gap_warning']
    assert matches, 'expected a coverage_gap_warning for non-empty uncovered'
    assert all((v.severity == 'advisory' for v in matches))

def test_slug_mismatch_still_fires():
    plan = _epic_plan(child_slugs=['alpha', 'ghost'], brief_slugs=['alpha'])
    violations = plan_validator.validate_epic_plan(plan)
    assert [v for v in violations if v.code == 'slug_mismatch']

def test_empty_uncovered_no_coverage_gap_warning():
    plan = _epic_plan(child_slugs=['alpha'], brief_slugs=['alpha'], coverage_check={'uncovered': []})
    violations = plan_validator.validate_epic_plan(plan)
    assert [v for v in violations if v.code == 'coverage_gap_warning'] == []