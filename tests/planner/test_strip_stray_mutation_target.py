"""RED oracle: normalize_plan must strip a stray ``mutation_target`` from any
NON-``test_authoring`` task.

Root cause this pins: the blind planner reflexively attaches
``mutation_target = "<module>.<function>"`` to NEW-FILE *implementation* tasks
(it omits it for edit-tasks). The orchestrator non-vacuity mutation gate then
TRIGGERS on that stray field for a non-test_authoring task, maps the dotted
value to a path via ``value.replace('.', '/') + '.py'`` -> e.g.
``ngv2/source_localize/localize_source.py`` -- a path that does not exist
(the real module is ``ngv2/source_localize.py``, ``localize_source`` is a
function inside it) -- and fails the task closed with ``mutation_gate_error``.

The planner schema already states "Omit mutation_target for all
non-test_authoring tasks", so the normalizer must enforce that invariant: drop
``mutation_target`` from tasks whose FINAL ``meta_task_type`` is not
``test_authoring``, while preserving it on genuine ``test_authoring`` oracles
(the non-vacuity gate legitimately needs it there).
"""
from __future__ import annotations

import copy

from harness.planner.plan_normalizer import normalize_plan


def _impl_with_stray_muttarget() -> dict:
    return {
        'tasks': [
            {
                'task_id': 'impl-new-module',
                'meta_task_type': 'implementation',
                # stray module.function on an IMPLEMENTATION task (planner reflex)
                'mutation_target': 'ngv2.foo.bar',
                'files_touched': ['ngv2/foo.py'],
                'dependencies': [],
                'verification_command': 'python -m pytest tests/test_foo.py -q',
            }
        ]
    }


def test_strips_mutation_target_from_implementation_task() -> None:
    out = normalize_plan(_impl_with_stray_muttarget())
    t = out['tasks'][0]
    assert t.get('task_id') == 'impl-new-module'
    assert 'mutation_target' not in t, (
        'a stray mutation_target on a non-test_authoring task must be stripped '
        'so the orchestrator mutation gate is not triggered against a '
        'nonexistent module path'
    )


def test_strips_mutation_target_from_data_model_task() -> None:
    plan = _impl_with_stray_muttarget()
    plan['tasks'][0]['meta_task_type'] = 'data_model'
    out = normalize_plan(plan)
    assert 'mutation_target' not in out['tasks'][0]


def test_keeps_mutation_target_on_test_authoring_task() -> None:
    plan = {
        'tasks': [
            {
                'task_id': 'oracle-x',
                'meta_task_type': 'test_authoring',
                'mutation_target': 'harness.planner.x',
                'files_touched': ['tests/planner/test_x.py'],
                'dependencies': [],
                'verification_command': 'python -m pytest tests/planner/test_x.py -q',
            }
        ]
    }
    out = normalize_plan(plan)
    t = out['tasks'][0]
    assert t.get('mutation_target') == 'harness.planner.x', (
        'a genuine test_authoring oracle MUST retain its mutation_target; the '
        'non-vacuity gate needs it'
    )


def test_input_not_mutated_and_idempotent() -> None:
    plan = _impl_with_stray_muttarget()
    original = copy.deepcopy(plan)
    out1 = normalize_plan(plan)
    assert plan == original, 'normalize_plan must not mutate its input'
    out2 = normalize_plan(copy.deepcopy(out1))
    assert out2 == out1, 'stripping mutation_target must be idempotent'
