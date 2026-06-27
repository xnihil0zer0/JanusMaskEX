import importlib.util
from pathlib import Path
from harness.paths import PROJECT_ROOT
from harness.planner.taxonomies import BYPASS_FUZZER_TYPES
worker_path = Path(PROJECT_ROOT) / 'harness' / 'orchestrator_worker.py'
spec = importlib.util.spec_from_file_location('orchestrator_worker', worker_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def test_smoke_gated_true_overrides_fuzzed_type() -> None:
    task = {'smoke_gated': True}
    assert module._task_bypasses_fuzz(task, 'data_model') is True

def test_no_smoke_gated_fuzzed_type_preserved() -> None:
    task = {}
    assert module._task_bypasses_fuzz(task, 'data_model') is False

def test_bypass_type_is_preserved() -> None:
    bypass_mtt = next(iter(BYPASS_FUZZER_TYPES))
    task = {}
    assert module._task_bypasses_fuzz(task, bypass_mtt) is True

def test_smoke_gated_false_does_not_trigger_bypass() -> None:
    task = {'smoke_gated': False}
    assert module._task_bypasses_fuzz(task, 'data_model') is False

def test_equivalence_invariant_when_smoke_gated_absent() -> None:
    bypass_mtt = next(iter(BYPASS_FUZZER_TYPES))
    assert module._task_bypasses_fuzz({}, bypass_mtt) == (bypass_mtt in BYPASS_FUZZER_TYPES)
    assert module._task_bypasses_fuzz({}, 'data_model') == ('data_model' in BYPASS_FUZZER_TYPES)

def test_non_dict_task_tolerated() -> None:
    assert module._task_bypasses_fuzz(None, 'data_model') is False
    bypass_mtt = next(iter(BYPASS_FUZZER_TYPES))
    assert module._task_bypasses_fuzz(123, bypass_mtt) is True

def test_import_from_file_succeeds() -> None:
    assert module is not None
    assert hasattr(module, '_task_bypasses_fuzz')
    assert callable(module._task_bypasses_fuzz)

def test_pure_predicate_no_side_effects() -> None:
    task = {'smoke_gated': True}
    task_copy = dict(task)
    original_bypass_types = list(BYPASS_FUZZER_TYPES)
    res1 = module._task_bypasses_fuzz(task, 'data_model')
    res2 = module._task_bypasses_fuzz(task, 'data_model')
    assert res1 is True
    assert res2 is True
    assert task == task_copy
    assert list(BYPASS_FUZZER_TYPES) == original_bypass_types

def test_regression_under_fuzz_invariant() -> None:
    bypass_mtt = next(iter(BYPASS_FUZZER_TYPES))
    assert module._task_bypasses_fuzz({'smoke_gated': True, 'other_key': 123}, 'data_model') is True
    assert module._task_bypasses_fuzz({'smoke_gated': True, 'other_key': 123}, bypass_mtt) is True
    assert module._task_bypasses_fuzz({'smoke_gated': False, 'other_key': 123}, 'data_model') is False
    assert module._task_bypasses_fuzz({'smoke_gated': False, 'other_key': 123}, bypass_mtt) is True
    assert module._task_bypasses_fuzz({'other_key': 'value'}, 'data_model') is False
    assert module._task_bypasses_fuzz({'other_key': 'value'}, bypass_mtt) is True

def test_regression_no_unapproved_or_manifest_files_created() -> None:
    import os
    paths_to_check = [Path('.'), Path(PROJECT_ROOT)]
    for p in paths_to_check:
        if p.exists():
            for f in p.glob('**/*'):
                if f.is_file():
                    assert 'manifest' not in f.name.lower()
                    assert 'unapproved' not in f.name.lower()
regression_under_fuzz_invariant = test_regression_under_fuzz_invariant
regression_no_unapproved_or_manifest_files_created = test_regression_no_unapproved_or_manifest_files_created