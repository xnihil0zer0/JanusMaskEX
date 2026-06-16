"""Hermetic tests for harness.planner.cli._stamp_brief_metadata.

Regression coverage for the validate-before-persist fix: brief-derived
metadata (working_dir, required_task_ids, source_brief_path/sha256,
parent_epic_slug) must be stamped onto the plan BEFORE validate_plan runs so
the validator sees working_dir (so external EDIT leaves are not falsely flagged
module-creating) and required_task_ids (so missing_required_task enforcement is
live).

These tests are hermetic: they never run the planner end-to-end, spawn a
subprocess, or touch the network. They exercise the pure helper plus a direct
validate_plan / _is_module_creating call against in-memory plan dicts.
"""
from types import SimpleNamespace
from harness.planner.cli import _stamp_brief_metadata
from harness.planner.plan_validator import validate_plan, _is_module_creating

def _make_brief(**overrides):
    """Build a tiny stand-in brief carrying the attributes the helper reads."""
    attrs = {'source_path': 'briefs/brief_example.md', 'sha256': 'a' * 64, 'working_dir': '/some/external/project', 'required_task_ids': ['task-a', 'task-b'], 'parent_epic_slug': 'parent-epic'}
    attrs.update(overrides)
    return SimpleNamespace(**attrs)

def _existing_edit_task():
    """A one-task plan whose only task EDITs an EXISTING repo .py file.

    files_touched references harness/planner/cli.py (an existing module) and
    meta_task_type is harness_self_fix, so once working_dir='.' is stamped the
    path resolves on disk as an EDIT (not module-creating).
    """
    return {'tasks': [{'task_id': 'fix-cli', 'meta_task_type': 'harness_self_fix', 'files_touched': ['harness/planner/cli.py'], 'verification_command': 'python -m pytest tests/planner -q'}]}

def test_stamp_sets_working_dir_and_required_task_ids():
    brief = _make_brief(working_dir='/ext/proj', required_task_ids=['t1', 't2'])
    plan = {}
    returned = _stamp_brief_metadata(plan, brief)
    assert returned is plan
    assert plan['working_dir'] == '/ext/proj'
    assert plan['required_task_ids'] == ['t1', 't2']

def test_stamp_idempotent_does_not_overwrite_existing_working_dir():
    brief = _make_brief(working_dir='/from/brief')
    plan = {'working_dir': 'X'}
    _stamp_brief_metadata(plan, brief)
    assert plan['working_dir'] == 'X'

def test_stamp_with_none_brief_returns_plan_unchanged():
    plan = {'tasks': []}
    returned = _stamp_brief_metadata(plan, None)
    assert returned is plan
    assert plan == {'tasks': []}

def test_stamp_plan_not_dict_returns_unchanged():
    brief = _make_brief()
    sentinel = ['not', 'a', 'dict']
    returned = _stamp_brief_metadata(sentinel, brief)
    assert returned is sentinel

def test_stamp_sets_source_brief_path_and_sha256():
    brief = _make_brief(source_path='briefs/b.md', sha256='b' * 64)
    plan = {}
    _stamp_brief_metadata(plan, brief)
    assert plan['source_brief_path'] == 'briefs/b.md'
    assert plan['source_brief_sha256'] == 'b' * 64

def test_stamp_sets_parent_epic_slug_and_returns_plan():
    brief = _make_brief(parent_epic_slug='my-epic')
    plan = {}
    returned = _stamp_brief_metadata(plan, brief)
    assert returned is plan
    assert plan['parent_epic_slug'] == 'my-epic'

def test_stamp_skips_empty_or_none_required_task_ids():
    plan_none = {}
    _stamp_brief_metadata(plan_none, _make_brief(required_task_ids=None))
    assert 'required_task_ids' not in plan_none
    plan_empty = {}
    _stamp_brief_metadata(plan_empty, _make_brief(required_task_ids=()))
    assert 'required_task_ids' not in plan_empty
    plan_tuple = {}
    _stamp_brief_metadata(plan_tuple, _make_brief(required_task_ids=('x', 'y')))
    assert plan_tuple['required_task_ids'] == ['x', 'y']

def test_stamp_never_overwrites_any_preexisting_key():
    brief = _make_brief()
    preset = {'source_brief_path': 'PRE_path', 'source_brief_sha256': 'PRE_sha', 'working_dir': 'PRE_wd', 'required_task_ids': ['PRE_task'], 'parent_epic_slug': 'PRE_epic'}
    plan = dict(preset)
    _stamp_brief_metadata(plan, brief)
    assert plan == preset

def test_stamp_then_persist_style_second_stamp_is_noop_for_keys():
    brief = _make_brief(working_dir='/ext', required_task_ids=['t1'])
    plan = {}
    _stamp_brief_metadata(plan, brief)
    snapshot = dict(plan)
    _stamp_brief_metadata(plan, brief)
    assert plan == snapshot

def test_validate_plan_no_missing_wiring_oracle_after_stamp_with_working_dir():
    plan = _existing_edit_task()
    brief = _make_brief(working_dir='.', required_task_ids=())
    _stamp_brief_metadata(plan, brief)
    assert plan['working_dir'] == '.'
    violations = validate_plan(plan)
    codes = {v.code for v in violations}
    assert 'missing_wiring_oracle' not in codes

def test_external_edit_leaf_not_falsely_flagged_module_creating():
    task = _existing_edit_task()['tasks'][0]
    assert _is_module_creating(task, working_dir='.') is False

def test_required_task_ids_present_at_validation_time():
    plan = _existing_edit_task()
    brief = _make_brief(working_dir='.', required_task_ids=['absent-task'])
    _stamp_brief_metadata(plan, brief)
    assert plan['required_task_ids'] == ['absent-task']
    violations = validate_plan(plan)
    codes = {v.code for v in violations}
    assert 'missing_required_task' in codes