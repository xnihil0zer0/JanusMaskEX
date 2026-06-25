import pytest
from harness.planner.plan_validator import validate_plan, PlanViolation

def make_valid_task(task_id: str, **kwargs) -> dict:
    task = {'task_id': task_id, 'title': 'Dummy Title', 'meta_task_type': 'test_authoring', 'priority': 'high', 'dependencies': [], 'files_touched': [], 'acceptance_criteria': ['Criteria'], 'spec_author': 'gemini', 'estimated_complexity': 'low', 'verification_command': 'pytest tests/dummy_test.py', 'mutation_target': 'harness.planner.plan_validator', 'spec': {'objective': 'Objective', 'functional_requirements': ['Req'], 'interfaces': 'Interfaces', 'edge_cases': ['Edge'], 'non_goals': ['Integration tests on a real deployment are out of scope. The literal word integration must be here.'], 'implementation_notes': 'Notes'}, 'test_spec': {'unit_tests': [{'name': 'test_dummy'}], 'integration_tests': [], 'property_tests': [], 'regression_tests': [{'name': 'test_dummy'}], 'minimum_test_count': 2, 'test_data_requirements': 'None'}, 'token_budget_ratio': {'implementation_tokens': 0, 'test_tokens': 100, 'note': 'None'}, 'attribution_metadata': {'proposed_by': 'gemini', 'reconciled': False, 'diff_resolution': None}}
    task.update(kwargs)
    return task

def test_reject_circular_vcmd_downstream_testfile():
    task_a = make_valid_task('task_a', verification_command='pytest tests/planner/test_foo.py')
    task_b = make_valid_task('task_b', dependencies=['task_a'], files_touched=['tests/planner/test_foo.py'])
    plan = {'tasks': [task_a, task_b]}
    violations = validate_plan(plan)
    vcmd_violations = [v for v in violations if v.code == 'circular_vcmd_downstream_testfile']
    assert len(vcmd_violations) >= 1
    violation = vcmd_violations[0]
    assert 'task_a' in violation.message
    assert 'task_b' in violation.message
    assert 'tests/planner/test_foo.py' in violation.message

def test_reject_circular_vcmd_downstream_testfile_transitive():
    task_a = make_valid_task('task_a', verification_command='pytest tests/planner/test_foo.py')
    task_c = make_valid_task('task_c', dependencies=['task_a'])
    task_b = make_valid_task('task_b', dependencies=['task_c'], files_touched=['tests/planner/test_foo.py'])
    plan = {'tasks': [task_a, task_c, task_b]}
    violations = validate_plan(plan)
    vcmd_violations = [v for v in violations if v.code == 'circular_vcmd_downstream_testfile']
    assert len(vcmd_violations) >= 1
    violation = vcmd_violations[0]
    assert 'task_a' in violation.message
    assert 'task_b' in violation.message
    assert 'tests/planner/test_foo.py' in violation.message

def test_accept_narrowed_vcmd_downstream_testfile():
    task_a_nodeid = make_valid_task('task_a', verification_command='pytest tests/planner/test_foo.py::test_bar')
    task_b = make_valid_task('task_b', dependencies=['task_a'], files_touched=['tests/planner/test_foo.py'])
    plan = {'tasks': [task_a_nodeid, task_b]}
    violations = validate_plan(plan)
    vcmd_violations = [v for v in violations if v.code == 'circular_vcmd_downstream_testfile']
    assert len(vcmd_violations) == 0
    task_a_k = make_valid_task('task_a', verification_command='pytest tests/planner/test_foo.py -k test_bar')
    plan = {'tasks': [task_a_k, task_b]}
    violations = validate_plan(plan)
    vcmd_violations = [v for v in violations if v.code == 'circular_vcmd_downstream_testfile']
    assert len(vcmd_violations) == 0
    task_a_k_before = make_valid_task('task_a', verification_command='pytest -k test_bar tests/planner/test_foo.py')
    plan = {'tasks': [task_a_k_before, task_b]}
    violations = validate_plan(plan)
    vcmd_violations = [v for v in violations if v.code == 'circular_vcmd_downstream_testfile']
    assert len(vcmd_violations) == 0

def test_accept_upstream_oracle_testfile():
    task_b = make_valid_task('task_b', files_touched=['tests/planner/test_foo.py'])
    task_a = make_valid_task('task_a', dependencies=['task_b'], verification_command='pytest tests/planner/test_foo.py')
    plan = {'tasks': [task_b, task_a]}
    violations = validate_plan(plan)
    vcmd_violations = [v for v in violations if v.code == 'circular_vcmd_downstream_testfile']
    assert len(vcmd_violations) == 0

def test_accept_plain_valid_plan():
    task_a = make_valid_task('task_a', verification_command='pytest tests/planner/test_foo.py')
    task_b = make_valid_task('task_b', dependencies=['task_a'], files_touched=['tests/planner/test_other.py'])
    plan = {'tasks': [task_a, task_b]}
    violations = validate_plan(plan)
    vcmd_violations = [v for v in violations if v.code == 'circular_vcmd_downstream_testfile']
    assert len(vcmd_violations) == 0

def test_validation_robustness():
    task_a = make_valid_task('task_a')
    if 'verification_command' in task_a:
        del task_a['verification_command']
    task_b = make_valid_task('task_b', dependencies=['task_a'], files_touched=['tests/planner/test_foo.py'])
    plan = {'tasks': [task_a, task_b]}
    validate_plan(plan)
    task_a = make_valid_task('task_a', verification_command='pytest tests/planner/test_foo.py')
    task_b = make_valid_task('task_b', dependencies=['task_a'])
    if 'files_touched' in task_b:
        del task_b['files_touched']
    plan = {'tasks': [task_a, task_b]}
    validate_plan(plan)
    task_a = make_valid_task('task_a', verification_command=12345)
    task_b = make_valid_task('task_b', dependencies=['task_a'], files_touched=['tests/planner/test_foo.py'])
    plan = {'tasks': [task_a, task_b]}
    validate_plan(plan)
    task_a = make_valid_task('task_a', verification_command='pytest tests/planner/test_foo.py')
    task_b = make_valid_task('task_b', dependencies=['task_a'], files_touched='tests/planner/test_foo.py')
    plan = {'tasks': [task_a, task_b]}
    validate_plan(plan)

def test_reject_circular_vcmd_downstream_testfile_multiple_violations():
    task_a = make_valid_task('task_a', verification_command='pytest tests/planner/test_foo.py')
    task_b = make_valid_task('task_b', dependencies=['task_a'], files_touched=['tests/planner/test_foo.py'])
    task_c = make_valid_task('task_c', verification_command='pytest tests/planner/test_bar.py')
    task_d = make_valid_task('task_d', dependencies=['task_c'], files_touched=['tests/planner/test_bar.py'])
    plan = {'tasks': [task_a, task_b, task_c, task_d]}
    violations = validate_plan(plan)
    vcmd_violations = [v for v in violations if v.code == 'circular_vcmd_downstream_testfile']
    assert len(vcmd_violations) >= 2

def test_accept_narrowed_vcmd_downstream_testfile_double_colon():
    task_a = make_valid_task('task_a', verification_command='pytest tests/planner/test_foo.py::TestClass::test_method')
    task_b = make_valid_task('task_b', dependencies=['task_a'], files_touched=['tests/planner/test_foo.py'])
    plan = {'tasks': [task_a, task_b]}
    violations = validate_plan(plan)
    vcmd_violations = [v for v in violations if v.code == 'circular_vcmd_downstream_testfile']
    assert len(vcmd_violations) == 0

def test_accept_narrowed_vcmd_downstream_testfile_dash_k_complex():
    task_a = make_valid_task('task_a', verification_command="pytest tests/planner/test_foo.py -k 'test_one or test_two'")
    task_b = make_valid_task('task_b', dependencies=['task_a'], files_touched=['tests/planner/test_foo.py'])
    plan = {'tasks': [task_a, task_b]}
    violations = validate_plan(plan)
    vcmd_violations = [v for v in violations if v.code == 'circular_vcmd_downstream_testfile']
    assert len(vcmd_violations) == 0

def test_validation_robustness_empty_dependencies():
    task_a = make_valid_task('task_a', verification_command='pytest tests/planner/test_foo.py')
    task_b = make_valid_task('task_b', files_touched=['tests/planner/test_foo.py'])
    if 'dependencies' in task_b:
        del task_b['dependencies']
    plan = {'tasks': [task_a, task_b]}
    validate_plan(plan)
    task_b['dependencies'] = None
    validate_plan(plan)

def test_validation_robustness_invalid_types():
    task_a = make_valid_task('task_a', verification_command='pytest tests/planner/test_foo.py')
    task_b = make_valid_task('task_b', dependencies=['task_a'], files_touched=[123, None, {}])
    plan = {'tasks': [task_a, task_b]}
    validate_plan(plan)