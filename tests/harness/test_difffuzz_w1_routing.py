from harness.orchestrator import should_bypass_fuzzer, Task

def test_should_bypass_fuzzer_flipped_orchestration():
    assert should_bypass_fuzzer(Task(task_id='t1', meta_task_type='orchestration')) is False

def test_should_bypass_fuzzer_flipped_planner_tooling():
    assert should_bypass_fuzzer(Task(task_id='t2', meta_task_type='planner_tooling')) is False

def test_should_bypass_fuzzer_flipped_sandbox_infra():
    assert should_bypass_fuzzer(Task(task_id='t3', meta_task_type='sandbox_infra')) is False

def test_should_bypass_fuzzer_flipped_validation():
    assert should_bypass_fuzzer(Task(task_id='t4', meta_task_type='validation')) is False

def test_should_bypass_fuzzer_controls_config_schema():
    assert should_bypass_fuzzer(Task(task_id='c1', meta_task_type='config_schema')) is True

def test_should_bypass_fuzzer_controls_test_authoring():
    assert should_bypass_fuzzer(Task(task_id='c2', meta_task_type='test_authoring')) is False

def test_should_bypass_fuzzer_generic():
    assert isinstance(should_bypass_fuzzer(Task(task_id='g1', meta_task_type='refactor')), bool)
    assert should_bypass_fuzzer(Task(task_id='g2', meta_task_type='nonexistent')) is False

def test_should_bypass_fuzzer_controls_data_model():
    assert should_bypass_fuzzer(Task(task_id='c3', meta_task_type='data_model')) is False

def test_should_bypass_fuzzer_controls_cli_tooling():
    assert should_bypass_fuzzer(Task(task_id='c4', meta_task_type='cli_tooling')) is False

def test_should_bypass_fuzzer_controls_refactor():
    assert should_bypass_fuzzer(Task(task_id='c5', meta_task_type='refactor')) is False

def test_should_bypass_fuzzer_controls_logging_observability():
    assert should_bypass_fuzzer(Task(task_id='c6', meta_task_type='logging_observability')) is False

def test_should_bypass_fuzzer_controls_state_machine():
    assert should_bypass_fuzzer(Task(task_id='c7', meta_task_type='state_machine')) is False