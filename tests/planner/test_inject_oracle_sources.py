"""RED oracle for committed-oracle-source injection into leaf specs (NGv2 Epic-3 root-cause fix).

Root cause: an auto-decomposed IMPL-only leaf task carries a spec that DEFERS to
the committed oracle ("semantics defined by the committed oracle tests/test_<leaf>.py"),
but the blind synthesis agent is jailed and cannot READ the oracle file. So the
exact constants/schemas the oracle pins never reach the agent and it fails
systematically on precision-sensitive leaves.

Fix: `normalize_plan(plan, repo_root=...)` deterministically reads each IMPL
task's committed oracle (the pytest test file named in its verification_command,
resolved under repo_root) and embeds its source verbatim into
`spec['implementation_notes']` under a clear marker, so the agent — which already
sees the full task spec via inbox/task.json — gets the exact contract. Inert when
repo_root is None, when the test file is absent, and for test_authoring tasks
(which AUTHOR the oracle). Idempotent.
"""
from __future__ import annotations

import copy
import pathlib

from harness.planner.plan_normalizer import normalize_plan

ORACLE_MARKER = 'COMMITTED ORACLE CONTRACT'
ORACLE_SRC = (
    "from ngv2.widget import expected_payout\n\n"
    "def test_widget_exact_constant():\n"
    "    # The agent must reproduce this exact magic number.\n"
    "    assert expected_payout({'max_paid': 800}, 'low') == 8\n"
)


def _impl_task(vcmd='python -m pytest tests/test_widget.py -q'):
    return {
        'task_id': 'ngv2-widget-impl',
        'meta_task_type': 'data_model',
        'files_touched': ['ngv2/widget.py'],
        'verification_command': vcmd,
        'spec': {
            'objective': 'build ngv2/widget.py',
            'functional_requirements': ['expose expected_payout'],
            'interfaces': 'expected_payout(bounty, severity)',
            'implementation_notes': 'semantics defined by the committed oracle.',
        },
    }


def _write_oracle(tmp_path: pathlib.Path, rel='tests/test_widget.py', src=ORACLE_SRC):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src, encoding='utf-8')
    return p


def test_oracle_source_injected_into_implementation_notes(tmp_path):
    _write_oracle(tmp_path)
    plan = {'tasks': [_impl_task()]}
    out = normalize_plan(plan, repo_root=tmp_path)
    notes = out['tasks'][0]['spec']['implementation_notes']
    assert ORACLE_MARKER in notes, 'oracle contract marker missing from implementation_notes'
    assert 'expected_payout' in notes and "== 8" in notes, 'oracle source body not embedded'
    assert 'tests/test_widget.py' in notes, 'oracle filename not referenced in the embedded block'


def test_no_injection_when_repo_root_none(tmp_path):
    _write_oracle(tmp_path)
    plan = {'tasks': [_impl_task()]}
    out = normalize_plan(plan, repo_root=None)
    notes = out['tasks'][0]['spec']['implementation_notes']
    assert ORACLE_MARKER not in notes
    assert notes == 'semantics defined by the committed oracle.'


def test_no_injection_when_oracle_file_absent(tmp_path):
    # repo_root provided but the referenced test file does not exist on disk.
    plan = {'tasks': [_impl_task(vcmd='python -m pytest tests/test_absent.py -q')]}
    out = normalize_plan(plan, repo_root=tmp_path)
    notes = out['tasks'][0]['spec']['implementation_notes']
    assert ORACLE_MARKER not in notes


def test_test_authoring_task_not_injected(tmp_path):
    _write_oracle(tmp_path)
    task = _impl_task()
    task['meta_task_type'] = 'test_authoring'
    task['mutation_target'] = 'ngv2.widget'
    plan = {'tasks': [task]}
    out = normalize_plan(plan, repo_root=tmp_path)
    notes = out['tasks'][0]['spec'].get('implementation_notes', '')
    assert ORACLE_MARKER not in notes


def test_injection_is_idempotent(tmp_path):
    _write_oracle(tmp_path)
    plan = {'tasks': [_impl_task()]}
    once = normalize_plan(plan, repo_root=tmp_path)
    twice = normalize_plan(once, repo_root=tmp_path)
    assert once['tasks'][0]['spec']['implementation_notes'] == twice['tasks'][0]['spec']['implementation_notes']
    assert twice['tasks'][0]['spec']['implementation_notes'].count(ORACLE_MARKER) == 1


def test_input_plan_not_mutated(tmp_path):
    _write_oracle(tmp_path)
    plan = {'tasks': [_impl_task()]}
    snapshot = copy.deepcopy(plan)
    normalize_plan(plan, repo_root=tmp_path)
    assert plan == snapshot, 'normalize_plan must not mutate its input plan'
