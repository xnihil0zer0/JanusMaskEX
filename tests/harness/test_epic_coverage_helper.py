"""RED oracle: compute_epic_coverage helper in harness.planner.plan_validator.

Hermetic, in-memory only. RED on HEAD (compute_epic_coverage absent) and GREEN
after the sibling implementation adds it. Only lines matching ^\\s*[-*+]\\s or
^\\s*\\d+[.)]\\s are deliverable candidates; prose/intro lines are never uncovered.
"""
from harness.planner import plan_validator

def _coverage(deliverables_text, child_briefs):
    assert hasattr(plan_validator, 'compute_epic_coverage'), 'compute_epic_coverage must be defined in harness.planner.plan_validator'
    return plan_validator.compute_epic_coverage(deliverables_text, child_briefs)

def test_helper_unmatched_bullet_in_uncovered():
    deliverables = 'This epic covers the platform work.\n- Implement the authentication flow\n- Frobnicate the zzqqx widget\n'
    child_briefs = [{'slug': 'authentication', 'title': 'Authentication'}, {'slug': 'database-layer', 'title': 'Database layer'}]
    result = _coverage(deliverables, child_briefs)
    assert isinstance(result, dict)
    uncovered = result.get('uncovered')
    assert isinstance(uncovered, list)
    joined = '\n'.join(uncovered)
    assert 'Frobnicate the zzqqx widget' in joined
    assert 'authentication flow' not in joined.lower()

def test_helper_prose_line_never_uncovered():
    prose = 'Quxzzy frobnicate wibble platform prose overview'
    deliverables = prose + '\n- authentication setup\n'
    child_briefs = [{'slug': 'authentication', 'title': 'Authentication'}]
    result = _coverage(deliverables, child_briefs)
    uncovered = result.get('uncovered')
    assert isinstance(uncovered, list)
    joined = '\n'.join(uncovered)
    assert prose not in joined
    assert 'Quxzzy' not in joined

def test_helper_all_matched_uncovered_empty():
    deliverables = 'Intro prose describing the epic.\n- authentication module work\n1. database migration step\n* telemetry dashboard rollout\n'
    child_briefs = [{'slug': 'authentication'}, {'slug': 'database'}, {'slug': 'telemetry'}]
    result = _coverage(deliverables, child_briefs)
    assert result.get('uncovered') == []

def test_helper_determinism_equal_results():
    deliverables = 'Overview line without a marker\n- authentication flow\n- unmatched alpha beta gamma\n2) database schema\n'
    child_briefs = [{'slug': 'authentication'}, {'slug': 'database'}]
    first = _coverage(deliverables, child_briefs)
    second = _coverage(deliverables, child_briefs)
    assert first == second
    assert any(('unmatched alpha beta gamma' in line for line in first.get('uncovered', [])))

def test_helper_idempotent_under_repeat_calls():
    deliverables = 'Plain prose overview\n- authentication flow\n- orphaned frobnicator zzqqx\n3. database schema change\n'
    child_briefs = [{'slug': 'authentication'}, {'slug': 'database'}]
    results = [_coverage(deliverables, child_briefs) for _ in range(3)]
    assert results[0] == results[1] == results[2]
    assert any(('orphaned frobnicator zzqqx' in line for line in results[0].get('uncovered', [])))