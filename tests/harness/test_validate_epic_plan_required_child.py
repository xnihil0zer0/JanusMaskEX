"""RED oracle: required_child_slugs -> missing_required_child error in
harness.planner.plan_validator.validate_epic_plan.

Hermetic, in-memory only. RED on HEAD (missing_required_child never emitted),
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

def test_required_child_missing_yields_error():
    plan = _epic_plan(child_slugs=['alpha'], brief_slugs=['alpha'], required_child_slugs=['alpha', 'beta'])
    violations = plan_validator.validate_epic_plan(plan)
    matches = [v for v in violations if v.code == 'missing_required_child']
    assert matches, "expected a missing_required_child violation for absent 'beta'"
    assert all((v.severity == 'error' for v in matches))

def test_required_child_all_present_clean():
    plan = _epic_plan(child_slugs=['alpha', 'beta'], brief_slugs=['alpha', 'beta'], required_child_slugs=['alpha', 'beta'])
    violations = plan_validator.validate_epic_plan(plan)
    assert [v for v in violations if v.code == 'missing_required_child'] == []

def test_required_child_absent_clean():
    plan = _epic_plan(child_slugs=['alpha'], brief_slugs=['alpha'])
    violations = plan_validator.validate_epic_plan(plan)
    assert [v for v in violations if v.code == 'missing_required_child'] == []