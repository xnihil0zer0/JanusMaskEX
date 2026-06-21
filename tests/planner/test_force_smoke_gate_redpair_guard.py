"""RED oracle for the smoke-gate red-pair guard in
``harness.planner.plan_normalizer._force_smoke_gated_leaf_impl``.

``_force_smoke_gated_leaf_impl`` collapses every external-build leaf task that
shares a committed oracle-test set down to a SINGLE impl survivor (retyped to the
smoke-gated ``data_model`` type), removing the rest -- *including* any
``test_authoring`` oracle that happens to share that oracle-test set.

That collapse is too aggressive for a fix-forward red-pair: a ``test_authoring``
oracle that the operator pinned (its id is listed in ``plan['required_task_ids']``)
or that a same-group impl candidate explicitly depends on is a deliberate RED
oracle the impl must turn GREEN, and dropping it silently destroys the red-pair.

CONTRACT exercised by this file (the GUARD the impl must add):

  * KEEP a non-survivor ``test_authoring`` oracle when its ``task_id`` is a member
    of the plan-level ``plan['required_task_ids']`` list.
  * KEEP a non-survivor ``test_authoring`` oracle when a same-group impl candidate
    lists that oracle's ``task_id`` in its ``dependencies``.
  * Otherwise behave EXACTLY as before -- a control plan of plain redundant impls
    still collapses to one ``data_model`` survivor, the guard never broadens the
    keep set to ordinary impls, and every documented no-op (``repo_root`` None,
    ``repo_root`` == ``PROJECT_ROOT``, epic plan, no committed oracle on disk)
    plus purity/idempotency is preserved.

The guard tests assert the post-impl behaviour, so they are RED against the
current (un-guarded) module and GREEN once the impl lands -- the canonical
fix-forward red-pair shape the orchestrator's acceptance gate recognises. Every
test invokes the real module function, so the whole file FAILS the stripped
``NotImplementedError`` stub (non-vacuity).
"""
from __future__ import annotations
import copy
import pathlib
from harness.paths import PROJECT_ROOT
from harness.planner.plan_normalizer import normalize_plan, _force_smoke_gated_leaf_impl
_NON_IMPL = {'test_authoring', 'test_acceptance', 'test_unit', 'test_integration', 'test_e2e', 'validation'}

def _write_oracle(root: pathlib.Path, rel: str) -> None:
    """Materialise a committed oracle test file at ``root/rel`` so its path
    resolves on disk and the task is grouped by _force_smoke_gated_leaf_impl."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('def test_placeholder():\n    assert True\n', encoding='utf-8')

def _impl_task(task_id, leaf, meta='io_adapter', deps=None):
    """A non-test_authoring impl leaf that builds ``ngv2/<leaf>.py`` and is
    verified by the committed ``tests/test_<leaf>.py`` oracle."""
    return {'task_id': task_id, 'meta_task_type': meta, 'files_touched': ['ngv2/%s.py' % leaf], 'dependencies': list(deps or []), 'verification_command': 'python -m pytest tests/test_%s.py -q' % leaf, 'spec': {'objective': 'build ngv2/%s.py' % leaf, 'implementation_notes': ''}}

def _oracle_task(task_id, leaf, deps=None):
    """A ``test_authoring`` oracle for ``ngv2/<leaf>.py`` whose own authored test
    file is the committed ``tests/test_<leaf>.py`` (same oracle-test set as the
    paired impl, so they land in the same collapse group)."""
    return {'task_id': task_id, 'meta_task_type': 'test_authoring', 'mutation_target': 'ngv2.%s' % leaf, 'files_touched': ['tests/test_%s.py' % leaf], 'dependencies': list(deps or []), 'verification_command': 'python -m pytest tests/test_%s.py -q' % leaf, 'spec': {'objective': 'oracle for ngv2/%s.py' % leaf, 'implementation_notes': ''}}

def _ids(plan):
    return [t['task_id'] for t in plan['tasks']]

def test_required_task_id_member_is_kept(tmp_path):
    """A non-survivor test_authoring oracle whose id is in
    ``plan['required_task_ids']`` is NOT dropped by the smoke-gate collapse."""
    _write_oracle(tmp_path, 'tests/test_widget.py')
    oracle = _oracle_task('widget-oracle', 'widget')
    impl = _impl_task('widget-impl', 'widget')
    plan = {'required_task_ids': ['widget-oracle'], 'tasks': [oracle, impl]}
    out = _force_smoke_gated_leaf_impl(plan, tmp_path)
    ids = _ids(out)
    assert 'widget-oracle' in ids, "a non-survivor test_authoring oracle whose id is in plan['required_task_ids'] must NOT be dropped by the smoke-gate collapse; surviving ids were " + repr(ids)
    survivors = [t for t in out['tasks'] if t['task_id'] == 'widget-impl']
    assert survivors, 'the impl survivor must remain in the plan'
    assert survivors[0]['meta_task_type'] == 'data_model', 'the surviving impl must still be retyped to the smoke-gated data_model type even when an oracle is kept alongside it'

def test_depended_on_oracle_is_kept(tmp_path):
    """A non-survivor test_authoring oracle that a same-group impl candidate
    lists in its ``dependencies`` is NOT dropped by the smoke-gate collapse."""
    _write_oracle(tmp_path, 'tests/test_gadget.py')
    oracle = _oracle_task('gadget-oracle', 'gadget')
    impl = _impl_task('gadget-impl', 'gadget', deps=['gadget-oracle'])
    plan = {'tasks': [oracle, impl]}
    out = _force_smoke_gated_leaf_impl(plan, tmp_path)
    ids = _ids(out)
    assert 'gadget-oracle' in ids, 'a non-survivor test_authoring oracle that a same-group impl lists in its dependencies must NOT be dropped by the smoke-gate collapse; surviving ids were ' + repr(ids)
    survivors = [t for t in out['tasks'] if t['task_id'] == 'gadget-impl']
    assert survivors, 'the depending impl survivor must remain in the plan'
    assert survivors[0]['meta_task_type'] == 'data_model'

def test_external_redundant_impl_collapsed(tmp_path):
    """Control: plain redundant external-leaf impls (no required id, no oracle
    dependency) still collapse to a single data_model survivor -- the guard
    must NOT broaden the keep set to ordinary impls."""
    _write_oracle(tmp_path, 'tests/test_widget.py')
    plan = {'tasks': [_impl_task('widget-impl-a', 'widget'), _impl_task('widget-impl-b', 'widget')]}
    out = _force_smoke_gated_leaf_impl(plan, tmp_path)
    surviving = [t for t in out['tasks'] if t['task_id'] in ('widget-impl-a', 'widget-impl-b')]
    assert len(surviving) == 1, 'two redundant impls sharing a committed oracle must collapse to exactly one survivor; got ' + repr(_ids(out))
    assert surviving[0]['task_id'] == 'widget-impl-a', 'the lexicographically-smallest impl id must be the survivor'
    assert surviving[0]['meta_task_type'] == 'data_model', 'the survivor must be retyped to the smoke-gated data_model type'
    assert surviving[0]['meta_task_type'] not in _NON_IMPL

def test_force_smoke_gated_leaf_impl_retypes_survivor_to_data_model(tmp_path):
    """A single external impl leaf with a committed oracle is retyped from its
    fuzz-routed type to the smoke-gated ``data_model`` type."""
    _write_oracle(tmp_path, 'tests/test_z3_bridge.py')
    plan = {'tasks': [_impl_task('z3-bridge-impl', 'z3_bridge', meta='io_adapter')]}
    out = _force_smoke_gated_leaf_impl(plan, tmp_path)
    assert len(out['tasks']) == 1
    assert out['tasks'][0]['meta_task_type'] == 'data_model', 'an external io_adapter leaf with an existing committed oracle must be retyped to data_model (bypass_fuzzer + smoke-gated)'

def test_force_smoke_gated_leaf_impl_strips_dropped_dependency(tmp_path):
    """A surviving task's dependency on a collapsed sibling is stripped."""
    _write_oracle(tmp_path, 'tests/test_widget.py')
    plan = {'tasks': [_impl_task('aaa-impl', 'widget', deps=['bbb-impl']), _impl_task('bbb-impl', 'widget')]}
    out = _force_smoke_gated_leaf_impl(plan, tmp_path)
    assert _ids(out) == ['aaa-impl'], 'the redundant sibling must be dropped, leaving one survivor; got ' + repr(_ids(out))
    surv = out['tasks'][0]
    assert surv['meta_task_type'] == 'data_model'
    assert 'bbb-impl' not in surv.get('dependencies', []), 'a dependency on a dropped sibling must be stripped from the survivor'

def test_force_smoke_gated_leaf_impl_repo_root_none_is_noop(tmp_path):
    """``repo_root`` None is a strict no-op: the fuzz-routed type is preserved."""
    plan = {'tasks': [_impl_task('backtrack-impl', 'backtrack', meta='state_machine')]}
    out = _force_smoke_gated_leaf_impl(plan, None)
    assert len(out['tasks']) == 1
    assert out['tasks'][0]['meta_task_type'] == 'state_machine', 'repo_root None must leave meta_task_type untouched'

def test_force_smoke_gated_leaf_impl_project_root_is_noop():
    """``repo_root`` == PROJECT_ROOT (a JM-internal self-fix) must NOT be retyped."""
    plan = {'tasks': [_impl_task('self-fix', 'backtrack', meta='harness_self_fix')]}
    out = _force_smoke_gated_leaf_impl(plan, PROJECT_ROOT)
    assert len(out['tasks']) == 1
    assert out['tasks'][0]['meta_task_type'] == 'harness_self_fix', 'a JM-internal plan (repo_root == PROJECT_ROOT) must never be retyped to data_model; that would corrupt every harness self-fix'

def test_force_smoke_gated_leaf_impl_epic_plan_is_noop(tmp_path):
    """An epic plan (``child_slugs`` truthy) is left untouched."""
    _write_oracle(tmp_path, 'tests/test_backtrack.py')
    plan = {'child_slugs': ['a', 'b'], 'tasks': [_impl_task('backtrack-impl', 'backtrack', meta='state_machine')]}
    out = _force_smoke_gated_leaf_impl(plan, tmp_path)
    assert out['tasks'][0]['meta_task_type'] == 'state_machine', 'an epic plan must not be retyped'

def test_force_smoke_gated_leaf_impl_no_existing_oracle_untouched(tmp_path):
    """When no committed oracle file exists under repo_root the task is not
    grouped and is left untouched (empty oracle-test set)."""
    plan = {'tasks': [_impl_task('backtrack-impl', 'backtrack', meta='state_machine')]}
    out = _force_smoke_gated_leaf_impl(plan, tmp_path)
    assert len(out['tasks']) == 1
    assert out['tasks'][0]['meta_task_type'] == 'state_machine', 'no existing oracle => not an identifiable external leaf => untouched'

def test_force_smoke_gated_leaf_impl_is_idempotent(tmp_path):
    """Normalising twice equals normalising once."""
    _write_oracle(tmp_path, 'tests/test_backtrack.py')
    plan = {'tasks': [_impl_task('backtrack-impl-a', 'backtrack'), _impl_task('backtrack-impl-b', 'backtrack')]}
    once = _force_smoke_gated_leaf_impl(plan, tmp_path)
    twice = _force_smoke_gated_leaf_impl(copy.deepcopy(once), tmp_path)
    assert _ids(once) == _ids(twice)
    assert once['tasks'][0]['meta_task_type'] == twice['tasks'][0]['meta_task_type'] == 'data_model'

def test_force_smoke_gated_leaf_impl_does_not_mutate_input(tmp_path):
    """The pass is pure: it deep-copies and never mutates the input plan."""
    _write_oracle(tmp_path, 'tests/test_backtrack.py')
    plan = {'tasks': [_impl_task('backtrack-impl-a', 'backtrack'), _impl_task('backtrack-impl-b', 'backtrack')]}
    snapshot = copy.deepcopy(plan)
    out = _force_smoke_gated_leaf_impl(plan, tmp_path)
    assert plan == snapshot, 'the input plan must not be mutated (pure deep-copy pass)'
    assert out is not plan
    assert len([t for t in out['tasks'] if t['task_id'] in ('backtrack-impl-a', 'backtrack-impl-b')]) == 1

def test_normalize_plan_collapses_redundant_external_impls(tmp_path):
    """End-to-end through the public ``normalize_plan`` interface: an external
    leaf of redundant impls collapses to a single smoke-gated data_model task."""
    _write_oracle(tmp_path, 'tests/test_widget.py')
    plan = {'tasks': [_impl_task('widget-impl-a', 'widget'), _impl_task('widget-impl-b', 'widget')]}
    out = normalize_plan(plan, repo_root=tmp_path)
    surviving = [t for t in out['tasks'] if t['task_id'] in ('widget-impl-a', 'widget-impl-b')]
    assert len(surviving) == 1, 'normalize_plan must collapse redundant external impls to one survivor; got ' + repr(_ids(out))
    assert surviving[0]['meta_task_type'] == 'data_model'