"""RED oracle — strip in-plan-unresolvable task dependencies (planner-strip-unresolvable-deps).

DEFECT (2026-06-09, autocompiler Phase A): an epic child brief carries
frontmatter ``dependencies:`` listing SIBLING brief SLUGS (e.g. ``ac_flags``,
``ac_population_db``). When that child is planned in isolation as a leaf, the
slug strings land in the generated task's ``dependencies`` — but the autowork
daemon gates dispatch on dependency strings being real, ACCEPTED ``task_id``s
(``autowork_daemon.py`` collect_dispatchable_tasks ~:246). A slug that matches
no task_id in the SAME plan is unsatisfiable by construction, so the task is
permanently undispatchable (observed: ``autocompiler_loop_impl`` wedged on
8 sibling slug-deps after all 8 modules were already built+committed).

Cross-brief / cross-epic sequencing is a BRIEF-level concern (held briefs,
allowlist, epic child ordering) — intra-plan task ``dependencies`` may only name
sibling tasks in the same plan. Therefore: a normalizer pass
``_strip_unresolvable_dependencies(tasks) -> None`` (mutates in place) drops, from
each task's ``dependencies``, every entry that is not the ``task_id`` of another
task in the same plan. ``normalize_plan`` runs this pass; legit intra-plan deps
and all other fields are preserved byte-for-byte; the pass is idempotent and a
strict no-op for already-clean plans.
"""
import copy

from harness.planner.plan_normalizer import (normalize_plan,
                                             _strip_unresolvable_dependencies)


def _task(tid, deps=None, **extra):
    t = {'task_id': tid, 'meta_task_type': 'data_model', 'files_touched': [f'{tid}.py'],
         'dependencies': list(deps or [])}
    t.update(extra)
    return t


def test_drops_dep_not_in_plan():
    tasks = [_task('loop_impl', deps=['ac_flags', 'ac_population_db'])]
    _strip_unresolvable_dependencies(tasks)
    assert tasks[0]['dependencies'] == []


def test_keeps_real_intra_plan_dep():
    tasks = [_task('a'), _task('b', deps=['a'])]
    _strip_unresolvable_dependencies(tasks)
    assert tasks[1]['dependencies'] == ['a']


def test_mixed_keeps_only_resolvable_preserving_order():
    tasks = [_task('a'), _task('c', deps=['a', 'ac_flags', 'a_missing'])]
    _strip_unresolvable_dependencies(tasks)
    assert tasks[1]['dependencies'] == ['a']


def test_inplace_returns_none():
    tasks = [_task('b', deps=['nope'])]
    assert _strip_unresolvable_dependencies(tasks) is None


def test_idempotent_noop_on_clean_plan():
    tasks = [_task('a'), _task('b', deps=['a'])]
    before = copy.deepcopy(tasks)
    _strip_unresolvable_dependencies(tasks)
    _strip_unresolvable_dependencies(tasks)
    assert tasks == before


def test_malformed_deps_tolerated():
    tasks = [_task('a', deps=None), {'task_id': 'b'}, _task('c', deps=['a', 123, None])]
    _strip_unresolvable_dependencies(tasks)
    assert tasks[2]['dependencies'] == ['a']


def test_normalize_plan_runs_the_pass():
    plan = {'tasks': [
        {'task_id': 'loop_impl', 'meta_task_type': 'orchestration',
         'files_touched': ['autocompiler/loop.py'], 'dependencies': ['ac_flags', 'ac_elo']},
    ]}
    out = normalize_plan(plan)
    assert out['tasks'][0]['dependencies'] == []


def test_normalize_plan_preserves_resolvable_dep():
    plan = {'tasks': [
        {'task_id': 'mod_a', 'meta_task_type': 'data_model', 'files_touched': ['a.py'], 'dependencies': []},
        {'task_id': 'mod_b', 'meta_task_type': 'data_model', 'files_touched': ['b.py'], 'dependencies': ['mod_a']},
    ]}
    out = normalize_plan(plan)
    deps = {t['task_id']: t['dependencies'] for t in out['tasks']}
    assert deps['mod_b'] == ['mod_a']
