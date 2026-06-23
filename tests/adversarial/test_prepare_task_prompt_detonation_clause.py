"""Adversarial oracle for the contract-gated LIVE-ROOT detonation clause.

Pins the observable behaviour of
``harness.orchestrator.prepare_task_prompt``: a ``test_authoring`` task that
carries a VALID ``constraints.integration_contract`` (entrypoints a non-empty
list whose every entry is in ``harness.wire_up.LIVE_ROOTS``, non-empty
``symbols``, and a non-empty ``runtime_oracle`` string) gets the five
LIVE-ROOT detonation markers appended to its worker prompt. A no-contract
task, a non-``test_authoring`` task, and every flavour of INVALID contract
get NONE of the markers while keeping the base ``TEST-AUTHORING DISPATCH``
framing -- so the tests pin the full entrypoints-subset-of-LIVE_ROOTS +
non-empty-symbols + non-empty-runtime_oracle validity predicate, not a
presence-only ``if contract:`` check.

The task declares ``mutation_target harness.orchestrator``; the stub_target
gate rewrites every function body in ``harness/orchestrator.py`` to
``raise NotImplementedError``, so ``prepare_task_prompt`` raises on every
call below and the whole suite errors on the mutant (non-vacuity).
"""
from harness.orchestrator import prepare_task_prompt
from harness.wire_up import LIVE_ROOTS
MARKERS = ('LIVE-ROOT DETONATION ORACLE', 'executed_with_live_root_ancestor', '_drive_run_pipeline', 'UNMOCKED', 'pure_helper')
BASE_FRAMING = 'TEST-AUTHORING DISPATCH'
VALID_ENTRYPOINT = LIVE_ROOTS[0]
VALID_SYMBOL = '_save_final_output'
VALID_RUNTIME_ORACLE = 'drive harness/orchestrator.py for one bounded iteration'
NON_LIVE_ROOT = 'harness/not_a_live_root.py'

def _valid_contract():
    """Return a fresh, fully VALID integration_contract dict."""
    return {'entrypoints': [VALID_ENTRYPOINT], 'symbols': [VALID_SYMBOL], 'runtime_oracle': VALID_RUNTIME_ORACLE}

def _test_authoring_task(contract=None):
    """Build a test_authoring task dict, optionally carrying *contract*.

    When *contract* is None the task has no ``constraints`` key at all, which
    exercises the ``task.get('constraints') is None`` path.
    """
    task = {'task_id': 'detonation-oracle-probe', 'meta_task_type': 'test_authoring'}
    if contract is not None:
        task['constraints'] = {'integration_contract': contract}
    return task

def _assert_all_markers(prompt):
    """Assert every detonation marker is present in *prompt*."""
    for marker in MARKERS:
        assert marker in prompt, 'expected detonation marker missing: ' + marker

def _assert_no_markers(prompt):
    """Assert no detonation marker is present in *prompt*."""
    for marker in MARKERS:
        assert marker not in prompt, 'unexpected detonation marker present: ' + marker

def test_prepare_task_prompt_valid_contract_emits_all_detonation_markers():
    """(A) A valid integration_contract emits all five detonation markers."""
    prompt = prepare_task_prompt(_test_authoring_task(_valid_contract()))
    _assert_all_markers(prompt)

def test_prepare_task_prompt_valid_contract_interpolates_entrypoints_and_symbols():
    """(A) The detonation clause interpolates the contract entrypoint and symbol."""
    prompt = prepare_task_prompt(_test_authoring_task(_valid_contract()))
    assert VALID_ENTRYPOINT in prompt
    assert VALID_SYMBOL in prompt

def test_prepare_task_prompt_valid_contract_keeps_base_dispatch_framing():
    """(A) The valid-contract prompt still carries the base dispatch framing."""
    prompt = prepare_task_prompt(_test_authoring_task(_valid_contract()))
    assert BASE_FRAMING in prompt
    _assert_all_markers(prompt)

def test_prepare_task_prompt_no_contract_omits_markers_keeps_base():
    """(B) No integration_contract -> no markers, base framing still present."""
    prompt = prepare_task_prompt(_test_authoring_task())
    _assert_no_markers(prompt)
    assert BASE_FRAMING in prompt

def test_prepare_task_prompt_non_test_authoring_omits_markers():
    """(C) A non-test_authoring task never gets the detonation markers.

    The task carries a fully VALID contract on purpose, so a missing
    meta_task_type gate (markers emitted on contract validity alone) is caught.
    """
    task = {'task_id': 'detonation-oracle-probe', 'meta_task_type': 'harness_self_fix', 'constraints': {'integration_contract': _valid_contract()}}
    prompt = prepare_task_prompt(task)
    _assert_no_markers(prompt)

def test_prepare_task_prompt_entrypoint_not_in_live_roots_omits_markers():
    """(d1) An entrypoint not in LIVE_ROOTS invalidates the contract."""
    contract = _valid_contract()
    contract['entrypoints'] = [NON_LIVE_ROOT]
    prompt = prepare_task_prompt(_test_authoring_task(contract))
    _assert_no_markers(prompt)
    assert BASE_FRAMING in prompt

def test_prepare_task_prompt_empty_symbols_omits_markers():
    """(d2) An empty symbols list invalidates the contract."""
    contract = _valid_contract()
    contract['symbols'] = []
    prompt = prepare_task_prompt(_test_authoring_task(contract))
    _assert_no_markers(prompt)
    assert BASE_FRAMING in prompt

def test_prepare_task_prompt_missing_runtime_oracle_omits_markers():
    """(d3) A missing or empty runtime_oracle invalidates the contract."""
    empty_oracle = _valid_contract()
    empty_oracle['runtime_oracle'] = ''
    prompt_empty = prepare_task_prompt(_test_authoring_task(empty_oracle))
    _assert_no_markers(prompt_empty)
    assert BASE_FRAMING in prompt_empty
    missing_oracle = _valid_contract()
    del missing_oracle['runtime_oracle']
    prompt_missing = prepare_task_prompt(_test_authoring_task(missing_oracle))
    _assert_no_markers(prompt_missing)
    assert BASE_FRAMING in prompt_missing

def test_prepare_task_prompt_empty_entrypoints_omits_markers():
    """(d4) An empty entrypoints list invalidates the contract."""
    contract = _valid_contract()
    contract['entrypoints'] = []
    prompt = prepare_task_prompt(_test_authoring_task(contract))
    _assert_no_markers(prompt)
    assert BASE_FRAMING in prompt

def test_prepare_task_prompt_mixed_entrypoints_omits_markers():
    """(d5) A mixed good/bad entrypoint list invalidates the contract.

    Every entry must be in LIVE_ROOTS; one valid plus one non-LIVE_ROOT entry
    is still invalid, so no markers are emitted.
    """
    contract = _valid_contract()
    contract['entrypoints'] = [VALID_ENTRYPOINT, NON_LIVE_ROOT]
    prompt = prepare_task_prompt(_test_authoring_task(contract))
    _assert_no_markers(prompt)
    assert BASE_FRAMING in prompt

def test_prepare_task_prompt_base_dispatch_present_when_no_contract():
    """Regression: the base dispatch framing survives when no contract is given."""
    prompt = prepare_task_prompt(_test_authoring_task())
    assert BASE_FRAMING in prompt
    _assert_no_markers(prompt)

def test_prepare_task_prompt_base_dispatch_present_when_contract_invalid():
    """Regression: the base dispatch framing survives an invalid contract."""
    contract = _valid_contract()
    contract['entrypoints'] = [NON_LIVE_ROOT]
    prompt = prepare_task_prompt(_test_authoring_task(contract))
    assert BASE_FRAMING in prompt
    _assert_no_markers(prompt)