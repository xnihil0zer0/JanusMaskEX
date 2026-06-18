"""RED oracle for harness.orchestrator._validate_submission region-patch handling.

Drives _validate_submission directly with in-memory __JANUSMASK_PATCHES__ source
strings (integration excused: no end-to-end factory/orchestrator/daemon run).

Desired post-fix behaviour:
  * a kind=='region' entry whose code body is a bare control-flow FRAGMENT
    (no top-level def/class/import/assign) is ACCEPTED -- no incomplete_ast;
  * a kind=='symbol' entry with the SAME fragment body is STILL REJECTED with
    incomplete_ast (the fix is region-scoped);
  * a kind=='region' entry whose body IS a normal top-level def stays accepted.

test_region_body_control_flow_accepted is RED on HEAD (HEAD emits incomplete_ast
for the region-fragment body) and GREEN after the impl drops incomplete_ast for
region entries. The other two are unchanged-behaviour regression controls.
"""
from harness.orchestrator import _validate_submission
FRAGMENT_BODY = 'if True:\n    pass\nelse:\n    pass'
DEF_BODY = 'def helper(value):\n    return value + 1'

def _make_task():
    """Minimal task dict that routes the call into the per-entry patch branch.

    meta_task_type 'harness_self_fix' is a BYPASS_FUZZER_TYPES member, so
    _validate_submission reaches the __JANUSMASK_PATCHES__ per-entry
    validation branch. No declared_signature is supplied, so no return-type
    contract check runs.
    """
    return {'meta_task_type': 'harness_self_fix', 'files_touched': ['harness/orchestrator.py'], 'task_id': 'fix_region_patch_incomplete_ast-oracle'}

def _region_patch_src(code_body):
    """Build a __JANUSMASK_PATCHES__ source with ONE kind='region' entry."""
    return "__JANUSMASK_PATCHES__ = [\n    {\n        'file': 'harness/orchestrator.py',\n        'kind': 'region',\n        'marker': 'REGION_MARKER',\n        'code': " + repr(code_body) + ',\n    },\n]\n'

def _symbol_patch_src(code_body):
    """Build a __JANUSMASK_PATCHES__ source with ONE kind='symbol' entry."""
    return "__JANUSMASK_PATCHES__ = [\n    {\n        'file': 'harness/orchestrator.py',\n        'kind': 'symbol',\n        'name': 'some_symbol',\n        'code': " + repr(code_body) + ',\n    },\n]\n'

def test_region_body_control_flow_accepted():
    """RED on HEAD: a region entry with a bare control-flow fragment body must
    be accepted with NO incomplete_ast violation."""
    src = _region_patch_src(FRAGMENT_BODY)
    ok, violations = _validate_submission(src, 'claude', _make_task())
    assert ok is True
    assert all((v.rule != 'incomplete_ast' for v in violations))

def test_symbol_body_incomplete_still_rejected():
    """Regression control: a symbol entry with the SAME bare fragment body is
    STILL rejected with incomplete_ast (the fix is region-scoped)."""
    src = _symbol_patch_src(FRAGMENT_BODY)
    ok, violations = _validate_submission(src, 'claude', _make_task())
    assert ok is False
    assert any((v.rule == 'incomplete_ast' for v in violations))

def test_region_body_with_valid_def_accepted():
    """Regression control: a region entry whose body IS a normal top-level def
    is accepted before and after the fix (already a mergeable node)."""
    src = _region_patch_src(DEF_BODY)
    ok, violations = _validate_submission(src, 'claude', _make_task())
    assert ok is True
    assert all((v.rule != 'incomplete_ast' for v in violations))