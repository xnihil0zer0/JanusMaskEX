"""Adversarial README-vs-code regression locks (Agent D scope).

Locks the documented constant/table values in README.md §9 (taxonomy),
§10 (R-anchor allowed_extra), §12/§4.2 (_NEVER_AUTO_APPROVE), and §8
(control.pause_flag_path) against the REAL code so a future drift of
either side fails CI. Pure imports; no daemon, no subprocess.
"""
import ast
import yaml
from harness.planner.taxonomies import META_TASK_POLICY
from harness.planner.taxonomies import BYPASS_FUZZER_TYPES
from harness.planner.taxonomies import SIDE_EFFECT_META_TYPES
from harness.planner.taxonomies import SKIP_SMOKE_GATE_TYPES
from harness.orchestrator import _NEVER_AUTO_APPROVE
README_BYPASS_FUZZER = {'data_model': False, 'config_schema': True, 'validation': False, 'planner_tooling': False, 'orchestration': False, 'harness_plumbing': False, 'mcp_plumbing': True, 'mcp_server_change': True, 'hooks_integration': True, 'docs_writing': True, 'epic_planning': True, 'cli_tooling': False, 'refactor': False, 'logging_observability': False, 'io_adapter': False, 'state_machine': False, 'sandbox_infra': False, 'test_unit': True, 'test_integration': True, 'test_e2e': True, 'test_acceptance': True, 'test_authoring': False, 'harness_self_fix': False}

def test_readme_taxonomy_bypass_fuzzer_matches_policy():
    """Every meta_task_type documented in README §9 matches META_TASK_POLICY."""
    mismatches = []
    for mtt, doc in README_BYPASS_FUZZER.items():
        assert mtt in META_TASK_POLICY, f'README documents unknown meta_task_type {mtt!r}'
        actual = META_TASK_POLICY[mtt]['bypass_fuzzer']
        if actual != doc:
            mismatches.append((mtt, doc, actual))
    assert not mismatches, f'bypass_fuzzer drift README->code: {mismatches}'

def test_readme_documents_every_policy_type():
    """README §9 must not silently omit a meta_task_type that exists in code."""
    documented = set(README_BYPASS_FUZZER)
    actual = set(META_TASK_POLICY)
    assert documented == actual, f'missing from README: {actual - documented}; extra in README: {documented - actual}'

def test_derived_sets_consistent_with_policy():
    assert BYPASS_FUZZER_TYPES == frozenset((k for k, v in META_TASK_POLICY.items() if v['bypass_fuzzer']))
    assert SIDE_EFFECT_META_TYPES == frozenset((k for k, v in META_TASK_POLICY.items() if v['skip_structural_decomp']))
    assert SKIP_SMOKE_GATE_TYPES == frozenset((k for k, v in META_TASK_POLICY.items() if v.get('skip_smoke_gates', False)))

def test_implementation_is_not_a_meta_task_type():
    """README §9: 'implementation is not a member'."""
    assert 'implementation' not in META_TASK_POLICY
    assert 'implementation' not in BYPASS_FUZZER_TYPES

def test_never_auto_approve_matches_readme():
    documented = ('harness/agent_jail.py', 'harness/dbus_proxy.py', 'harness/paths.py', 'harness/git_integration.py', 'harness/orchestrator.py', 'harness/interceptors.py', 'harness/selfheal.py', 'harness/autowork_daemon.py', 'services/**')
    assert tuple(_NEVER_AUTO_APPROVE) == documented, f'_NEVER_AUTO_APPROVE drift: code={_NEVER_AUTO_APPROVE} doc={documented}'

def test_allowed_extra_node_kinds_match_readme():
    """README §10 lists exactly these ast node kinds for R-anchor extras."""
    src = open('harness/git_integration.py', encoding='utf-8').read()
    tree = ast.parse(src)
    found = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and (node.targets[0].id == 'allowed_extra') and isinstance(node.value, ast.Tuple):
            found = [elt.attr for elt in node.value.elts if isinstance(elt, ast.Attribute)]
            break
    assert found is not None, 'allowed_extra tuple not located in git_integration.py'
    documented = ['Import', 'ImportFrom', 'FunctionDef', 'AsyncFunctionDef', 'ClassDef', 'Assign', 'AnnAssign']
    assert found == documented, f'allowed_extra drift: code={found} doc={documented}'

def test_control_pause_flag_path_config_value():
    cfg = yaml.safe_load(open('harness/config.yaml', encoding='utf-8'))
    assert cfg['control']['pause_flag_path'] == 'state/control/orchestrator.flag'
    assert cfg['control']['decisions_dir'] == 'state/control/decisions'
    assert cfg['control']['autobrief_default_agent'] == 'claude'

def test_readme_section8_config_subtrees():
    cfg = yaml.safe_load(open('harness/config.yaml', encoding='utf-8'))
    assert cfg['agent_sandbox'] == {'bwrap': True}
    assert cfg['sandbox'] == {'cpu_time_limit_seconds': 10, 'memory_limit_mb': 256, 'network': False, 'filesystem_root': '/tmp/janusmask_sandbox'}
    assert cfg['fuzzing'] == {'engine': 'hypothesis', 'seed': 42, 'function_level_inputs': 2000, 'program_level_inputs': 1000, 'timeout_per_input_ms': 5000, 'float_tolerance': 1e-09}
    assert cfg['hierarchical_planning'] == {'enabled': True, 'max_planner_depth': 4, 'failure_propagation': True, 'symbol_ledger': True}
    assert cfg['autocompiler'] == {'enabled': True, 'population': True, 'determinism': True, 'decode': True, 'js': True}
    runtime = yaml.safe_load(open('config/autocompiler.yaml', encoding='utf-8'))
    assert runtime['autocompiler'] == cfg['autocompiler']

def test_readme_glossary_live_roots():
    from harness.wire_up import LIVE_ROOTS
    assert LIVE_ROOTS == ['harness/orchestrator.py', 'harness/orchestrator_worker.py', 'harness/autowork_daemon.py', 'harness/planner/cli.py']
'Adversarial README-vs-code regression locks (Agent D scope).\n\nLocks the documented constant/table values in README.md §9 (taxonomy),\n    §10 (R-anchor allowed_extra), §12/§4.2 (_NEVER_AUTO_APPROVE), and §8\n(control.pause_flag_path) against the REAL code so a future drift of\neither side fails CI. Pure imports; no daemon, no subprocess.\n'