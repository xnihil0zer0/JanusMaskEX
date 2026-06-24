"""Oracle: check if fuzzer routing works properly.

Assert that should_bypass_fuzzer returns False for:
- harness_self_fix
- harness_plumbing
Assert that should_bypass_fuzzer returns True/False as expected for controls:
- config_schema (True)
- mcp_plumbing (True)
- test_authoring (False)
"""
from typing import Optional, Any, Dict
from harness.orchestrator import should_bypass_fuzzer, Task

def test_flipped_routing_harness_self_fix():
    assert should_bypass_fuzzer(Task(task_id='t1', meta_task_type='harness_self_fix')) is False

def test_flipped_routing_harness_plumbing():
    assert should_bypass_fuzzer(Task(task_id='t2', meta_task_type='harness_plumbing')) is False

def test_control_config_schema():
    assert should_bypass_fuzzer(Task(task_id='t3', meta_task_type='config_schema')) is True

def test_control_mcp_plumbing():
    assert should_bypass_fuzzer(Task(task_id='t4', meta_task_type='mcp_plumbing')) is True

def test_control_test_authoring():
    assert should_bypass_fuzzer(Task(task_id='t5', meta_task_type='test_authoring')) is False

def test_control_sandbox_infra():
    assert should_bypass_fuzzer(Task(task_id='t6', meta_task_type='sandbox_infra')) is False

def test_control_mcp_server_change():
    assert should_bypass_fuzzer(Task(task_id='t7', meta_task_type='mcp_server_change')) is True

def test_control_data_model():
    assert should_bypass_fuzzer(Task(task_id='t8', meta_task_type='data_model')) is False

def test_control_cli_tooling():
    assert should_bypass_fuzzer(Task(task_id='t9', meta_task_type='cli_tooling')) is False

def test_control_test_unit():
    assert should_bypass_fuzzer(Task(task_id='t10', meta_task_type='test_unit')) is True

def test_control_missing_meta_task_type():
    assert should_bypass_fuzzer(Task(task_id='t11', meta_task_type=None)) is False

def test_control_unrecognized_meta_task_type():
    assert should_bypass_fuzzer(Task(task_id='t12', meta_task_type='unknown_type')) is False